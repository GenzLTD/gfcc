"""格契内核 FastAPI 入口。

- GET  /health            健康检查（对齐契约：无鉴权）。
- POST /v1/ask            单入口（AskRequest → AskResponse 信封，严格契约）。
- POST /v1/knowledge/query   L3 工具入口（knowledge.demopeter RAG；默认 404）。
- 认证：ethos 纯验证者；401 未认证 / 403 无权限 / 429 配额。
- 五槽装配 + 五端口默认 stub 组合（gfcc.default）；
  GFCC_MODE=profile.demo 时经 adapters.bind_profile_demo() 接入本地组件
  （store 槽 → agentmemory_iii、注册 knowledge.demopeter），可卸载。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .adapters import bind_profile_demo
from .adapters.agentmemory_store import AgentMemoryIIIStore
from .circle_flow import get_store as build_circle_flow
from .circle_web import router as circle_web_router
from .dispatcher import parse_then_dispatch
from .envelope import AskRequest, AskResponse
from .registry import PortRegistry
from .security import KernelPolicy, build_security
from .signal import (
    PayloadError,
    SIGNAL_ROUTE,
    SignalEnvelope,
    route_signal,
    validate_payload,
    verify_signature,
)
from .slots import OllamaLLM, SQLiteStore, build_llm, build_store

load_dotenv()

logger = logging.getLogger("gfcc_kernel")

app = FastAPI(
    title="GFCC Kernel",
    version="1.1.0",
    description="格契内核：POST /v1/ask 单入口 + 五槽 + 五端口默认 stub 组合",
)

# --------------------------------------------------------------------------- #
# 装配（模块级单例）
# --------------------------------------------------------------------------- #

_store = build_store()
_registry = PortRegistry(
    threshold=int(os.getenv("CONSENSUS_THRESHOLD", "85")),
    store=_store,
    flow=build_circle_flow(),
)
_security = build_security()
_policy = KernelPolicy(_security)
_llm = build_llm()

# L3 profile.demo：总装 + 本地组件（agentmemory / demopeter）联调装配。
# 默认 gfcc.default（禁止厂商适配器）；切换只靠 GFCC_MODE，可随时卸掉回默认栈。
_mode = os.getenv("GFCC_MODE", "gfcc.default").strip().lower()
if _mode == "profile.demo":
    _store = bind_profile_demo(_registry)

_store_provider = (
    "agentmemory_iii" if isinstance(_store, AgentMemoryIIIStore)
    else "sqlite" if isinstance(_store, SQLiteStore)
    else "stub"
)
_llm_provider = "ollama" if isinstance(_llm, OllamaLLM) else "stub"


@app.on_event("startup")
async def _startup() -> None:
    logger.info(
        "gfcc_kernel ready: ports=%s store=%s llm=%s empty_on_boot=%s",
        _registry.list_ports(),
        _store_provider,
        _llm_provider,
        _store_provider == "stub",
    )


# --------------------------------------------------------------------------- #
# 健康检查
# --------------------------------------------------------------------------- #

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "gfcc_kernel",
        "version": "1.1.0",
        "ports": _registry.list_ports(),
        "mode": _mode,
        "store": _store_provider,
        "llm": _llm_provider,
        "tools_extra": _registry.list_tools(),
        "empty_on_boot": _store_provider == "stub",
    }


# --------------------------------------------------------------------------- #
# /v1/ask 单入口
# --------------------------------------------------------------------------- #

def _verify_request(request: Request) -> None:
    """ethos 认证：Bearer token → AuthContext；未认证 401。

    HS256 模式下 verify 失败不抛异常（ctx.error / principal=None）→ 必须显式 401。
    stub 模式（无 ETHOS_AUTH_SECRET）下空 token 返回 stub-anon 主体，仅本地联调用。
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    else:
        token = ""
    try:
        ctx = _security.verify(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"unauthorized: {exc}") from exc
    if getattr(ctx, "error", None) or getattr(ctx, "principal", None) is None:
        raise HTTPException(
            status_code=401,
            detail=f"unauthorized: {getattr(ctx, 'error', None) or 'missing valid principal'}",
        )
    _policy.bind(ctx)


@app.post("/v1/ask")
async def v1_ask(request: Request, body: AskRequest) -> AskResponse:
    """单入口：信封入 → 信封出。内部实现可替换，信封不可变。"""
    _verify_request(request)
    _policy.audit("ask", resource=body.context.circle_id or "", meta={"session": body.context.session_id})

    ctx = _registry.build_context(
        session_id=body.context.session_id,
        circle_id=body.context.circle_id,
        dialog_mode=body.context.dialog_mode or "collaboration",
        policy=_policy,
        llm=_llm,
    )
    return parse_then_dispatch(body, ctx)


# --------------------------------------------------------------------------- #
# /circle 围坐会场（公网入口：GET /circle/ + /circle/api/*）
# --------------------------------------------------------------------------- #

app.include_router(circle_web_router)


# --------------------------------------------------------------------------- #
# 品牌门面（GET /）+ 静态资源（/static/*，含 LOGO / 围坐会场 HTML 等）
# --------------------------------------------------------------------------- #

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_ROOT_FILE = _STATIC_DIR / "root.html"

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_index() -> HTMLResponse:
    """品牌门页：定位、四轴、围坐入口、五条判据。

    纯展示、无业务接口；不动 `/v1/ask` / `/v1/signal-ingest` / `/circle/*`。
    契约真源见 `docs/`，工程口径见 `docs/ports/README.md`。
    """
    return HTMLResponse(_ROOT_FILE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# /v1/signal-ingest（Step3 W1-W3：机机事件入口）
# --------------------------------------------------------------------------- #

def _dispatch_signal(signal_id: str, user_id_hash: str, signal_type: str,
                     payload: Dict[str, Any], port: str) -> None:
    """把新信号下发给对应端口适配器。

    信号已先落 signal_log（幂等），端口处理失败只记 WARNING，不阻塞摄入
    （重放安全：同 nonce 重发会走 duplicate 分支，不重复下发）。
    """
    adapter = _registry.get(port)
    if adapter is None or not hasattr(adapter, "ingest_signal"):
        logger.warning("signal-ingest: port %s has no ingest_signal, signal_id=%s dropped at port", port, signal_id)
        return
    try:
        if port == "identity":
            result = adapter.ingest_signal(
                signal_id, user_id_hash, payload, signal_type=signal_type,
            )
        else:
            result = adapter.ingest_signal(signal_id, user_id_hash, payload)
        if not result.ok:
            logger.warning("signal-ingest: port %s rejected signal_id=%s: %s", port, signal_id, result.error)
    except Exception:  # noqa: BLE001
        logger.exception("signal-ingest: port %s ingest failed for signal_id=%s", port, signal_id)


@app.post("/v1/signal-ingest")
async def v1_signal_ingest(request: Request) -> JSONResponse:
    """信号摄入：验签 → 严格信封校验 → 幂等落库 → 端口路由。

    - 401 invalid_signature：SIGNAL_INGEST_SECRET 已配但 X-Signature 不匹配。
    - 422 invalid_envelope：信封缺/多余字段、格式错误、payload 不符契约。
    - 200 stored / duplicate：幂等键 (signal_type, user_id_hash, nonce)。
    """
    raw = await request.body()

    # 1) 验签：SIGNAL_INGEST_SECRET 留空 = dev 免签 + WARNING（本地联调）
    secret = os.getenv("SIGNAL_INGEST_SECRET", "").strip()
    if secret:
        header_sig = request.headers.get("X-Signature", "")
        if not verify_signature(secret, raw, header_sig):
            return JSONResponse(
                status_code=401,
                content={"code": "invalid_signature", "detail": "X-Signature HMAC mismatch"},
            )
    else:
        logger.warning("signal-ingest: SIGNAL_INGEST_SECRET unset — dev no-auth mode (local integration only)")

    # 2) 信封严格校验（additionalProperties=false）
    try:
        env = SignalEnvelope.model_validate_json(raw or b"{}")
    except Exception:  # noqa: BLE001
        # 契约语义（Phase2_Step3 §3.3）：未知 signal_type → 422 unsupported_signal；
        # 其余信封错误（缺/多余字段、格式不符）→ 422 invalid_envelope
        try:
            raw_obj = json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            raw_obj = {}
        st = raw_obj.get("signal_type")
        if isinstance(st, str) and st not in SIGNAL_ROUTE:
            return JSONResponse(
                status_code=422,
                content={"code": "unsupported_signal",
                         "detail": f"unknown signal_type: {st}"},
            )
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_envelope",
                     "detail": "envelope must conform to signal.envelope.v1 (no extra/missing fields)"},
        )

    # 3) payload 契约校验
    try:
        validate_payload(env.signal_type, env.payload)
    except PayloadError as exc:
        return JSONResponse(status_code=422, content={"code": "invalid_envelope", "detail": str(exc)})

    # 4) 幂等落库（signal_log，经 store 槽）
    result = _store.record_signal(env.signal_type, env.user_id_hash, env.nonce, env.payload)
    signal_id = result["signal_id"]

    # 5) 端口路由（仅新信号下发；duplicate 直接返回，不重复触发端口）
    port = route_signal(env.signal_type)
    if not result["duplicate"]:
        _dispatch_signal(signal_id, env.user_id_hash, env.signal_type, env.payload, port)

    return JSONResponse(
        status_code=200,
        content={
            "status": "duplicate" if result["duplicate"] else "stored",
            "signal_id": signal_id,
            "port": port,
        },
    )


# --------------------------------------------------------------------------- #
# /v1/knowledge/query（L3 profile.demo：knowledge.demopeter RAG 工具入口）
# --------------------------------------------------------------------------- #
# 非一等端口（registry.v1.json：Not a 格契 first-class port），对标 signal-ingest
# 的并列工具入口。默认模式（工具未注册）一律 404；装配后才可查询。
# 红线：输出只作参考证据，不进 identity/memory 主存；洞察走 memory.observe。

@app.post("/v1/knowledge/query")
async def v1_knowledge_query(request: Request) -> JSONResponse:
    _verify_request(request)
    tool = _registry.get_tool("knowledge.demopeter")
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail="knowledge.demopeter not registered (GFCC_MODE != profile.demo)",
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="request body must be JSON")
    question = str((body or {}).get("question", "")).strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is required")
    top_k = int((body or {}).get("top_k", 5))
    threshold = float((body or {}).get("threshold", 0.5))
    _policy.audit("knowledge_query", resource="", meta={"top_k": top_k})
    result = tool.query(question, top_k=top_k, threshold=threshold)
    if not result.ok:
        return JSONResponse(status_code=502, content={"detail": result.error})
    return JSONResponse(content=result.data)


# --------------------------------------------------------------------------- #
# 错误处理
# --------------------------------------------------------------------------- #

@app.exception_handler(HTTPException)
async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"internal error: {type(exc).__name__}"})
