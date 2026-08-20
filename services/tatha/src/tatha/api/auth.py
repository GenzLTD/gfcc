"""
V1 认证：从请求头取 token，调量子认证校验（或 stub），将 user_id、tier 注入请求上下文。

认证链（按优先级）：
1. Ethos HMAC 严格模式（配置了 ETHOS_AUTH_SECRET）：仅认外部签发方签发的标准 JWT（HS256），失败即 401，不回退。
2. 未配置 ETHOS_AUTH_SECRET：保留现状 —— 远程量子认证（QUANTUM_AUTH_URL），否则 stub（任意 token 视为 free 档）。
"""
import os
import re
from dataclasses import dataclass
from typing import Literal

from fastapi import Header, HTTPException

Tier = Literal["free", "basic", "pro"]


@dataclass
class AuthContext:
    """请求上下文中的用户身份与档位，供业务与配额使用。"""
    user_id: str
    tier: Tier


def get_bearer_token(authorization: str | None = Header(None, alias="Authorization")) -> str | None:
    """从请求头取出 Bearer token；无头或格式不对返回 None。"""
    if not authorization or not isinstance(authorization, str):
        return None
    auth = authorization.strip()
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token if token else None


def _verify_token_stub(token: str) -> AuthContext:
    """Stub：任意非空 token 视为 free 档，user_id 由 token 派生。"""
    safe = re.sub(r"[^a-zA-Z0-9\-]", "", token[:32]) or "anon"
    return AuthContext(user_id=f"stub-{safe}", tier="free")


def _verify_token_remote(token: str) -> AuthContext | None:
    """调用量子认证服务校验 token；失败或非 200 返回 None。"""
    url = os.environ.get("QUANTUM_AUTH_URL", "").strip()
    if not url:
        return None
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode())
            user_id = data.get("user_id")
            tier_raw = (data.get("tier") or "free").lower()
            tier: Tier = "free" if tier_raw not in ("basic", "pro") else tier_raw
            if not user_id:
                return None
            return AuthContext(user_id=str(user_id), tier=tier)
    except Exception:
        return None


def verify_token(token: str) -> AuthContext | None:
    """
    校验 token（认证链，见模块 docstring）：
    1. Ethos HMAC 模式：严格验签标准 JWT（含运行时 SystemMinter 签发的系统令牌）；失败返回 None（不回退）。
    2. 否则：远程量子认证（QUANTUM_AUTH_URL）→ stub 兜底。
    """
    from .security import security

    ctx = security.authenticate(token)
    if ctx is not None:
        return ctx
    if security.hmac_enabled:
        return None  # HMAC 严格模式：不回落 stub/远程
    ctx = _verify_token_remote(token)
    if ctx is not None:
        return ctx
    return _verify_token_stub(token)


def get_auth(authorization: str | None = Header(None, alias="Authorization")) -> AuthContext:
    """
    依赖项：从请求头取 token，校验后返回 AuthContext；无 token 或校验失败抛出 401。
    用于需要鉴权的路由：/v1/ask、/v1/jobs/match、/v1/documents/convert、/v1/rag/query。
    """
    token = get_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing or invalid authorization")
    ctx = verify_token(token)
    if ctx is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return ctx
