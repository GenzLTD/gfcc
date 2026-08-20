"""安全域模型：Principal / AuthDecision / AuditEvent。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class Principal:
    """通过认证后的调用方身份。tier: free / pro / admin。"""

    user_id: str
    tier: str = "free"
    scopes: Tuple[str, ...] = ()
    issued_at: float = 0.0
    expires_at: Optional[float] = None

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


@dataclass(frozen=True)
class AuthDecision:
    """鉴权结果。"""

    allowed: bool
    reason: str = ""

    @classmethod
    def allow(cls, reason: str = "") -> "AuthDecision":
        return cls(True, reason)

    @classmethod
    def deny(cls, reason: str) -> "AuthDecision":
        return cls(False, reason)


@dataclass(frozen=True)
class AuditEvent:
    """一条审计记录：谁 / 何时 / 调了什么 / 结果 / 配额。"""

    action: str
    user_id: str
    tier: str = ""
    resource: str = ""
    intent: str = ""
    status: str = "ok"  # ok / denied / error
    latency_ms: int = 0
    quota_after: int = -1
    request_id: str = ""
    ts: float = field(default_factory=time.time)
    detail: str = ""
