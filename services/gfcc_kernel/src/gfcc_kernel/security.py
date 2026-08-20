"""内核安全接入 —— 复用 ethos 纯验证者。

对齐 contracts/ask.envelope.v1.json 的 auth 语义：
- verifier: ethos；uid_claim: sub；deny_by_default: true；401/403/429。
- 同一把 ethos 密钥：ETHOS_AUTH_SECRET 留空 → StubVerifier（本地联调放行，
  与现有 5210 基线一致）；配置后 → HS256 严格校验（系统令牌跨服务互通）。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from ethos.models import Tier
from ethos.security import SecurityProvider, init_security

logger = logging.getLogger("gfcc_kernel.security")

# 端口 → 最小 scope（对齐 roles.v1.json 八级阶梯 + 各端口契约 operations）
PORT_SCOPES = {
    "circle": {
        "create": "circle.create",
        "join": "circle.join",
        "leave": "circle.leave",
        "pause": "circle.pause",
        "dissolve": "circle.dissolve",
        "read": "circle.read",
    },
    "identity": {
        "read": "identity.read",
        "write": "identity.write",
    },
    "memory": {
        "read": "memory.read",
        "write": "memory.write",
        "observe": "memory.observe",
    },
    "consensus": {
        "read": "consensus.read",
        "propose": "consensus.propose",
        "score": "consensus.score",
        "ack": "consensus.ack",
    },
    "contribution": {
        "attest": "contribution.attest",
        "fulfill": "contribution.fulfill",
        "appeal": "contribution.appeal",
        "resolve": "contribution.appeal.resolve",
    },
}


def build_security() -> SecurityProvider:
    """装配 ethos 安全门面。密钥语义与 5210 一致。"""
    secret = os.getenv("ETHOS_AUTH_SECRET") or ""
    sec = init_security(
        secret=secret or None,
        # 默认：无策略 → TierAuthorizer({"*": FREE})，认证即可用（stub 联调）
        audit_db=os.getenv("ETHOS_AUDIT_DB") or None,
        audit_jsonl=os.getenv("ETHOS_AUDIT_JSONL") or None,
    )
    if secret:
        logger.info("ethos: HS256 strict mode enabled")
    else:
        logger.warning("ethos: stub verify mode (no ETHOS_AUTH_SECRET) — local integration only")
    return sec


class KernelPolicy:
    """内核 policy 槽：把 ethos 门面包成 dispatcher 可用的轻量门面。"""

    def __init__(self, sec: SecurityProvider) -> None:
        self.sec = sec
        self.sub: Optional[str] = None
        self.ctx: Any = None

    def bind(self, ctx: Any) -> None:
        """绑定当前请求的 AuthContext。"""
        self.ctx = ctx
        self.sub = ctx.principal.user_id if ctx and ctx.principal else None

    def require_scope(self, scope: str) -> bool:
        """stub 语义：未绑定主体或 stub 验证器 → 放行（本地联调）；严格模式走 ethos。"""
        if self.ctx is None:
            return True
        try:
            self.sec.require(self.ctx, scope)
            return True
        except PermissionError:
            return False

    def authorize(self, scope: str) -> bool:
        decision = self.sec.authorize(self.ctx, scope) if self.ctx else None
        return bool(decision) if decision is not None else True

    def audit(self, action: str, resource: str = "", meta: Optional[Dict[str, Any]] = None) -> None:
        self.sec.audit(action, self.ctx, resource=resource, meta=meta)
