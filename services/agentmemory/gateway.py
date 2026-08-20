"""agentmemory → ethos 认证网关（宿主侧，黑盒 iii-engine 前置）。

形态（网关协议 §1.5 / §4 对齐，与 Tatha、DemoPeter 同一把 ETHOS_AUTH_SECRET）：
- 认证：ethos `HmacJwtVerifier` 验签标准 JWT（无 ETHOS_AUTH_SECRET → Stub 放行，本地联调）；
- 鉴权：GET → `memory.read`（pro 起），POST/PUT/DELETE → `memory.write`（pro 起），管理路径 → `admin`；
- 审计：每次调用落 `data/ethos_audit.db`（ethos 统一结构，旧 tenet 表启动自动迁移）；
- 转发：写操作（POST/PUT/DELETE/PATCH）→ agentmemory 桥 :3220（无损 JSON body → mem::* 跨 worker 直调，
  规避 iii-engine http worker 丢弃 POST body 的缺陷）；读操作（GET）→ iii-engine :3111；SSE → :3112 流式透传；
- 保护：简单进程内限流（默认 60 req/min/IP）+ 60s 上游超时兜底（SSE 不限时）。

运行：uvicorn gateway:app --host 127.0.0.1 --port 3210
说明：`/{path:path}` 全路径透传，无需理解 iii 内部协议（黑盒边界）。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ethos.security import init_security

ENGINE_HTTP = os.getenv("AM_ENGINE_HTTP", "http://127.0.0.1:3111")
ENGINE_STREAM = os.getenv("AM_ENGINE_STREAM", "http://127.0.0.1:3112")
BRIDGE_HTTP = os.getenv("AM_BRIDGE_HTTP", "http://127.0.0.1:3220")
AUDIT_DB = os.getenv("AM_AUDIT_DB", os.path.join(os.path.dirname(__file__), "data", "ethos_audit.db"))
UPSTREAM_TIMEOUT = float(os.getenv("AM_UPSTREAM_TIMEOUT", "60"))
RATE_LIMIT_PER_MIN = int(os.getenv("AM_RATE_LIMIT", "60"))

# 档位策略（与 Tatha `_TIER_POLICY`、DemoPeter `TIER_POLICY` 对齐）
TIER_POLICY: dict[str, str] = {
    "memory.read": "pro",
    "memory.write": "pro",
    "admin": "admin",
}

# 管理路径前缀 → admin（其余按方法映射 read/write）
_ADMIN_PREFIXES = ("/config", "/admin", "/workers", "/debug", "/reset")
# 豁免：健康探针（供 compose healthcheck / 本地探测）
_EXEMPT_PATHS = ("/healthz", "/health", "/metrics")

app = FastAPI(title="agentmemory ethos gateway", version="0.1.0")

# 惰性装配（测试可 cache_clear 重建）
_SEC: Optional[object] = None


def get_security():
    global _SEC
    if _SEC is None:
        _SEC = init_security(
            secret=os.getenv("ETHOS_AUTH_SECRET") or None,
            tier_policy=TIER_POLICY,
            audit_db=AUDIT_DB,
        )
    return _SEC


# ---- 进程内限流（简单滑动窗口，按客户端 IP）----
_rate_lock = threading.Lock()
_rate: dict[str, list[float]] = {}


def _rate_limit(ip: str) -> None:
    now = time.time()
    with _rate_lock:
        window = _rate.setdefault(ip, [])
        window[:] = [t for t in window if t > now - 60]
        if len(window) >= RATE_LIMIT_PER_MIN:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        window.append(now)


def _action_for(method: str, path: str) -> str:
    if path.startswith(_ADMIN_PREFIXES):
        return "admin"
    return "memory.write" if method in ("POST", "PUT", "DELETE", "PATCH") else "memory.read"


def _extract_token(authorization: str) -> str:
    if authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return ""


def _check(request: Request, action: str, token: str) -> object:
    """认证 → 鉴权 → 审计，任一失败抛 HTTPException。返回 principal。"""
    sec = get_security()
    ctx = sec.verify(token)
    if not ctx.ok or ctx.principal is None:
        raise HTTPException(status_code=401, detail=ctx.error or "missing or invalid authorization")
    try:
        sec.require(ctx, action)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    sec.audit(
        action=action,
        principal=ctx.principal,
        resource=str(request.url.path),
        meta={"method": request.method},
    )
    return ctx.principal


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "agentmemory-gateway"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(
    path: str,
    request: Request,
    authorization: str = Header(default=""),
) -> object:
    full_path = f"/{path}"
    if full_path.startswith(_EXEMPT_PATHS):
        return JSONResponse({"ok": True, "path": full_path})

    _rate_limit(request.client.host if request.client else "local")
    token = _extract_token(authorization)
    action = _action_for(request.method, full_path)
    _check(request, action, token)

    is_sse = request.headers.get("accept", "").startswith("text/event-stream")
    if is_sse:
        target = ENGINE_STREAM
    elif request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # 写操作 → 桥（无损 JSON body；GET 保持引擎 REST，因其无 body 无损）
        target = BRIDGE_HTTP
    else:
        target = ENGINE_HTTP
    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "authorization", "accept-encoding")
    }
    # 到上游不再带原始 Authorization（黑盒无认证；隔离靠 127.0.0.1 绑定）
    url = f"{target}{full_path}"
    if request.query_params:
        url = f"{url}?{request.query_params}"

    try:
        if is_sse:
            upstream = httpx.stream(
                "POST", url, content=body, headers=headers, timeout=None
            )
            return StreamingResponse(upstream.aiter_raw(), media_type="text/event-stream")
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            resp = await client.request(
                request.method, url, content=body, headers=headers
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="upstream timeout") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}") from exc

    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        return JSONResponse(resp.json(), status_code=resp.status_code)
    return JSONResponse(
        {"detail": "non-json upstream response", "body": resp.text[:2000]},
        status_code=resp.status_code,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=3210)
