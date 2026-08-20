"""Tenet Security —— 认证 / 鉴权 / 审计三件套。

一键装配：
    from tenet.security import init_security

    ctx = init_security()               # auto：有 TENET_AUTH_SECRET 走 HMAC，否则 Stub
    principal = ctx["authenticator"].authenticate(token)
    decision = ctx["authorizer"].authorize(principal, "rag.query")
    if decision.allowed:
        ctx["auditor"].record(AuditEvent(action="rag.query", user_id=principal.user_id))
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from ..registry import Registry
from .authenticator import (
    Authenticator,
    HmacAuthenticator,
    StubAuthenticator,
)
from .authorizer import DEFAULT_POLICY, Authorizer, TierAuthorizer
from .auditor import Auditor, JsonlAuditor, NullAuditor, SqliteAuditor
from .models import AuditEvent, AuthDecision, Principal

__all__ = [
    "Registry",
    "Authenticator",
    "HmacAuthenticator",
    "StubAuthenticator",
    "Authorizer",
    "TierAuthorizer",
    "DEFAULT_POLICY",
    "Auditor",
    "NullAuditor",
    "JsonlAuditor",
    "SqliteAuditor",
    "Principal",
    "AuthDecision",
    "AuditEvent",
    "init_security",
]

# 可插拔注册表：安全组件按名切换实现
registry = Registry("tenet.security")
registry.register("hmac", HmacAuthenticator)
registry.register("stub", StubAuthenticator)
registry.register("tier", TierAuthorizer)
registry.register("sqlite", SqliteAuditor)
registry.register("jsonl", JsonlAuditor)
registry.register("null", NullAuditor)


def init_security(
    *,
    auth: str = "auto",
    audit: str = "auto",
    audit_path: Optional[Path] = None,
    policy: Optional[Mapping[str, str]] = None,
) -> dict:
    """一键装配 security 三件套。

    auth: "hmac" | "stub" | "auto"（有 TENET_AUTH_SECRET 走 HMAC，否则 Stub）
    audit: "sqlite" | "jsonl" | "null" | "auto"（默认 sqlite）
    """
    # 认证
    if auth == "hmac":
        authenticator: Authenticator = HmacAuthenticator()
    elif auth == "stub":
        authenticator = StubAuthenticator()
    elif auth == "auto":
        authenticator = HmacAuthenticator() if os.getenv("TENET_AUTH_SECRET") else StubAuthenticator()
    else:
        raise ValueError(f"未知认证方式: {auth}")

    # 鉴权
    authorizer: Authorizer = TierAuthorizer(policy)

    # 审计
    if audit == "sqlite":
        auditor: Auditor = SqliteAuditor(audit_path)
    elif audit == "jsonl":
        auditor = JsonlAuditor(audit_path or Path.home() / ".tenet" / "audit.jsonl")
    elif audit == "null":
        auditor = NullAuditor()
    elif audit == "auto":
        auditor = SqliteAuditor(audit_path)
    else:
        raise ValueError(f"未知审计方式: {audit}")

    return {"authenticator": authenticator, "authorizer": authorizer, "auditor": auditor}
