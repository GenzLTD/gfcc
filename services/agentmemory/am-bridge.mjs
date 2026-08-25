// agentmemory REST 桥接（引擎 v0.11.2 补丁）
// -----------------------------------------------------------------------------
// 背景：iii-engine v0.11.2 的内置 iii-http worker 无法把 application/json 的
//       POST body 传给 agentmemory 注册的 http trigger 函数（body 被丢弃），
//       text/plain 又会被命令解析破坏（引号丢失/编码错乱）。
// 方案：本桥自带 HTTP server 无损解析 JSON body，再通过 iii-sdk 跨 worker
//       直调 agentmemory 注册的 mem::* 函数（绕过损坏的 HTTP 传输层）。
// 部署：宿主侧常驻进程（node am-bridge.mjs），监听 127.0.0.1:3220。
//       网关（gateway.py）将 POST/PUT/DELETE 转发到此桥，GET/SSE 维持原样。
// -----------------------------------------------------------------------------
import http from "node:http";
import { registerWorker } from "iii-sdk";

const ENGINE_URL = process.env.AM_ENGINE_URL || "ws://localhost:49134";
const PORT = parseInt(process.env.AM_BRIDGE_PORT || "3220", 10);
const REST_URL = process.env.AM_REST_URL || "http://127.0.0.1:3111";
const LOOPBACK = process.env.AM_BRIDGE_HOST || "127.0.0.1";

// POST 路径 → mem::* 函数映射（与 agentmemory dist/index.mjs 中 api::* 的 payload 一致）
const ROUTES = {
  "/agentmemory/search": "mem::search",
  "/agentmemory/smart-search": "mem::smart-search",
  "/agentmemory/remember": "mem::remember",
  "/agentmemory/forget": "mem::forget",
  "/agentmemory/context": "mem::context",
  "/agentmemory/summarize": "mem::summarize",
  "/agentmemory/consolidate": "mem::consolidate",
  "/agentmemory/patterns": "mem::patterns",
  "/agentmemory/generate-rules": "mem::generate-rules",
  "/agentmemory/timeline": "mem::timeline",
  "/agentmemory/profile": "mem::profile",
  "/agentmemory/observe": "mem::observe",
  "/agentmemory/enrich": "mem::enrich",
  "/agentmemory/session/start": "mem::session::start",
  "/agentmemory/session/end": "mem::session::end",
  "/agentmemory/session/commit": "mem::session::commit",
  // 调试路由：直接跨 worker 调引擎内部 state worker，对照验证调用通道
  "/debug/state-list": "state::list",
  "/debug/state-get": "state::get",
  "/debug/state-set": "state::set",
};

// 引擎为 distroless 镜像，compose 无法对其做容器内 healthcheck（无 shell/node）。
// 依赖链改为 service_started，由本桥在启动时轮询引擎 REST 就绪后再注册 worker，
// 避免竞态（engine 容器已 started 但 49134/3111 尚未监听）。
async function waitForEngine(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let lastErr;
  while (Date.now() < deadline) {
    try {
      await fetch(`${url}/`);
      return;
    } catch (e) {
      lastErr = e;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`engine not ready at ${url}: ${lastErr?.message}`);
}

await waitForEngine(REST_URL);

// agentmemory 应用 worker（mem::* 函数 + /agentmemory/* REST 路由）由本容器代跑。
// 引擎镜像 iiidev/iii:0.11.2（distroless，无 node）不含应用代码——官方形态是独立
// node 进程执行 dist/index.mjs。此处动态 import 包入口（import 即 boot），它经
// III_ENGINE_URL 连接引擎 49134，注册 worker "agentmemory" 与 mem::* 函数；
// 其自起 REST(3111)/viewer(3113) 为容器内端口，与桥的 3220 互不冲突。
process.env.III_ENGINE_URL = process.env.III_ENGINE_URL ?? ENGINE_URL;
await import("@agentmemory/agentmemory");

const iii = registerWorker(ENGINE_URL, {
  workerName: "am-bridge",
  invocationTimeoutMs: 180000,
  telemetry: { project_name: "am-bridge", language: "node", framework: "iii-sdk" }
});

function json(res, code, obj) {
  const payload = JSON.stringify(obj);
  res.writeHead(code, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return Buffer.concat(chunks).toString("utf8");
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;

  // GET/HEAD/OPTIONS 等无 body 语义的请求 → 直接代理到引擎 3111（该链路正常）
  if (req.method !== "POST" && req.method !== "PUT" && req.method !== "DELETE") {
    try {
      const headers = { ...req.headers };
      delete headers["host"];
      delete headers["authorization"];
      const upstream = await fetch(`${REST_URL}${path}${url.search}`, {
        method: req.method,
        headers,
      });
      const text = await upstream.text();
      res.writeHead(upstream.status, {
        "content-type": upstream.headers.get("content-type") || "application/json",
      });
      res.end(text);
    } catch (e) {
      json(res, 502, { error: `upstream error: ${e.message}` });
    }
    return;
  }

  const fn = ROUTES[path];
  if (!fn) {
    json(res, 501, { error: `no mem:: mapping for POST ${path}` });
    return;
  }

  let body;
  try {
    const raw = await readBody(req);
    body = raw ? JSON.parse(raw) : {};
  } catch (e) {
    json(res, 400, { error: `invalid json body: ${e.message}` });
    return;
  }

  try {
    const result = await iii.trigger({ function_id: fn, payload: body });
    json(res, 200, result);
  } catch (e) {
    json(res, 502, { error: `${fn} failed: ${e.message}` });
  }
});

server.listen(PORT, LOOPBACK, () => {
  console.log(`[am-bridge] listening on http://${LOOPBACK}:${PORT} (engine ${ENGINE_URL})`);
});
