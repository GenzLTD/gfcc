"""格契内核 FastAPI 入口。

- GET  /health            健康检查（对齐契约：无鉴权）。
- POST /v1/ask            单入口（AskRequest → AskResponse 信封，严格契约）。
- 认证：ethos 纯验证者；401 未认证 / 403 无权限 / 429 配额。
- 五槽装配 + 五端口默认 stub 组合（gfcc.default）。
"""

from __future__ import annotations

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
from .slots import LLMProvider

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

_registry = PortRegistry(threshold=int(os.getenv("CONSENSUS_THRESHOLD", "85")))
_security = build_security()
_policy = KernelPolicy(_security)
_llm = LLMProvider(model=os.getenv("LLM_MODEL", "providers/default"), endpoint=os.getenv("LLM_ENDPOINT") or None)


@app.on_event("startup")
async def _startup() -> None:
    logger.info(
        "gfcc_kernel ready: ports=%s store=stub empty_on_boot=true",
        _registry.list_ports(),
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
        "store": "stub",
        "empty_on_boot": True,
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
# 错误处理
# --------------------------------------------------------------------------- #

@app.exception_handler(HTTPException)
async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"internal error: {type(exc).__name__}"})
