"""认证：验证凭据 → Principal。

实现：
- HmacAuthenticator：HMAC-SHA256 签名 token（纯标准库，本地签发/校验，零外部依赖）。
- StubAuthenticator：联调用，显式配置才启用（任何 token 放行为固定身份）。

Token 格式（类 JWT，简化版）：
    base64url(header) . base64url(payload) . hex(hmac-sha256(signing_input))
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import List, Optional, Protocol, Sequence

from .models import Principal


class Authenticator(Protocol):
    def authenticate(self, token: str) -> Optional[Principal]:
        """验证 token，通过返回 Principal，否则返回 None。"""
        ...


class HmacAuthenticator:
    """HMAC 签名 token 的本地签发 / 校验。密钥来自构造参数或环境变量 TENET_AUTH_SECRET。"""

    _ALGO = "HS256"

    def __init__(self, secret: Optional[str] = None, ttl_seconds: int = 86400) -> None:
        self._secret = (secret or os.getenv("TENET_AUTH_SECRET") or "").encode("utf-8")
        if not self._secret:
            raise ValueError("缺少 HMAC 密钥：请传 secret 或设置环境变量 TENET_AUTH_SECRET")
        self._ttl = ttl_seconds

    # ---- 签发 ----
    def issue(
        self,
        user_id: str,
        tier: str = "free",
        scopes: Sequence[str] = (),
        ttl_seconds: Optional[int] = None,
    ) -> str:
        now = time.time()
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        payload: dict = {
            "sub": user_id,
            "tier": tier,
            "scopes": list(scopes),
            "iat": now,
            "exp": now + ttl,
        }
        signing_input = _b64({"alg": self._ALGO, "typ": "JWT"}) + "." + _b64(payload)
        return f"{signing_input}.{self._sign(signing_input)}"

    # ---- 校验 ----
    def authenticate(self, token: str) -> Optional[Principal]:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            signing_input, signature = ".".join(parts[:2]), parts[2]
            if not hmac.compare_digest(signature, self._sign(signing_input)):
                return None
            payload = _unb64(parts[1])
            principal = Principal(
                user_id=payload["sub"],
                tier=payload.get("tier", "free"),
                scopes=tuple(payload.get("scopes", [])),
                issued_at=payload.get("iat", 0.0),
                expires_at=payload.get("exp"),
            )
            return None if principal.expired else principal
        except Exception:
            return None

    def _sign(self, signing_input: str) -> str:
        return hmac.new(self._secret, signing_input.encode("utf-8"), hashlib.sha256).hexdigest()


class StubAuthenticator:
    """联调模式：任何 token 都放行为固定身份。仅限本地开发显式启用。"""

    def __init__(self, user_id: str = "local-dev", tier: str = "admin") -> None:
        self._principal = Principal(user_id=user_id, tier=tier)

    def authenticate(self, token: str) -> Optional[Principal]:
        return self._principal


def _b64(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> dict:
    padding = "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode(value + padding)
    return json.loads(raw)
