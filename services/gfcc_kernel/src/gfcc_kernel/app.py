"""格契内核 FastAPI 入口。

- GET  /health            健康检查（对齐契约：无鉴权）。
- POST /v1/ask            单入口（AskRequest → AskResponse 信封，严格契约）。
- 认证：ethos 纯验证者；401 未认证 / 403 无权限 / 429 配额。
- 五槽装配 + 五端口默认 stub 组合（gfcc.default）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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
)
_security = build_security()
_policy = KernelPolicy(_security)
_llm = build_llm()

_store_provider = "sqlite" if isinstance(_store, SQLiteStore) else "stub"
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
        "mode": "gfcc.default",
        "store": _store_provider,
        "llm": _llm_provider,
        "empty_on_boot": _store_provider == "stub",
    }


# --------------------------------------------------------------------------- #
# /v1/ask 单入口
# --------------------------------------------------------------------------- #

def _verify_request(request: Request) -> None:
    """ethos 认证：Bearer token → AuthContext；未认证 401。"""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    else:
        token = ""
    try:
        ctx = _security.verify(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"unauthorized: {exc}") from exc
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
# 错误处理
# --------------------------------------------------------------------------- #

@app.exception_handler(HTTPException)
async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"internal error: {type(exc).__name__}"})
