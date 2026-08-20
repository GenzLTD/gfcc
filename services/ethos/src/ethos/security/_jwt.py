"""JWT base64url 工具（零依赖）。"""

from __future__ import annotations

import base64
import json
from typing import Any


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """还原 base64url（自动补齐 padding）。"""
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def split_jwt(token: str) -> tuple[str, str, str]:
    """拆 JWT → (header_b64, payload_b64, signature_b64)；非法格式抛 ValueError。"""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWT 必须是三段式 header.payload.signature")
    return parts[0], parts[1], parts[2]


def encode_token(header: dict[str, Any], payload: dict[str, Any], signature: bytes) -> str:
    """拼装 JWT 字符串（供测试/签发方使用；ethos 本身不签发）。"""
    h = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{h}.{p}.{b64url_encode(signature)}"
