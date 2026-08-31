"""HS256 会话 JWT 签发（redeem 端点与 issue_persona_tokens.py 共用）。

保证「redeem 签发的 JWT 与 CLI 脚本相同」：同一份 issue_token，同一把
ETHOS_AUTH_SECRET，payload 结构 sub/tier/iat/exp 一致，ethos HmacJwtVerifier 可验。

- 有 ETHOS_AUTH_SECRET：标准 HS256（生产/天翼）。
- 无密钥（stub 联调）：签名段写占位字节——StubVerifier 不验签、只解析
  payload.sub，保证本地无密钥环境 redeem → /api/me 全链路可走通。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def issue_token(sub: str, secret: str, days: int = 30, tier: str = "pro", now: Optional[int] = None) -> str:
    """HS256 JWT：{alg:HS256, typ:JWT} + {sub, tier, iat, exp}，与 ethos._jwt 兼容。

    secret 为空 → 签名段为占位字节（仅 stub 联调，StubVerifier 不验签）。
    """
    now = int(time.time()) if now is None else int(now)
    header: Dict[str, Any] = {"alg": "HS256", "typ": "JWT"}
    payload: Dict[str, Any] = {
        "sub": sub,
        "tier": tier,
        "iat": now,
        "exp": now + days * 86400,
    }
    h = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    if secret:
        sig = hmac.new(secret.encode("utf-8"), f"{h}.{p}".encode("utf-8"), hashlib.sha256).digest()
    else:
        sig = b"stub"  # 本地联调：ethos stub 模式不验签
    return f"{h}.{p}.{b64url(sig)}"


def load_secret(secret_arg: Optional[str] = None, kernel_root: Optional[Path] = None) -> str:
    """取 ETHOS_AUTH_SECRET：--secret 参数 > 内核根 .env > 环境变量。

    找不到返回 ""（redeem 走 stub 联调签名；CLI 侧自行决定是否拒绝签发）。
    """
    if secret_arg:
        return secret_arg
    root = kernel_root or Path(__file__).resolve().parents[2]
    env_file = root / ".env"
    if env_file.exists():
        # .env 含中文注释（UTF-8）；Windows 默认 GBK，必须显式 encoding
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ETHOS_AUTH_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("ETHOS_AUTH_SECRET", "").strip()
