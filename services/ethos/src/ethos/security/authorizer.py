"""鉴权器：对已认证的 Principal 做权限判定（ethos 不管签发，只管"放不放行"）。

两种模型：
- TierAuthorizer：按档位（free/basic/pro/admin）判定，适合"按套餐开放能力"。
- PermissionAuthorizer：按权限标识（permission 列表）判定，适合细粒度 RBAC。

通用约定：
- 未认证（principal=None）一律拒绝（deny by default）。
- 返回 ``Decision``（allow / deny + 原因），中间件据此决定 401/403。
"""

from __future__ import annotations

from typing import Optional

from ..models import AuthContext, Principal, Tier


class Decision:
    __slots__ = ("allow", "reason")

    def __init__(self, allow: bool, reason: str = "") -> None:
        self.allow = allow
        self.reason = reason

    @classmethod
    def allow_reason(cls, reason: str = "") -> "Decision":
        return cls(True, reason)

    @classmethod
    def deny(cls, reason: str = "") -> "Decision":
        return cls(False, reason)

    def __bool__(self) -> bool:
        return self.allow

    def __repr__(self) -> str:  # pragma: no cover
        return f"Decision(allow={self.allow}, reason={self.reason!r})"


class BaseAuthorizer:
    def authorize(self, ctx: AuthContext, scope: str) -> Decision:
        raise NotImplementedError


class TierAuthorizer(BaseAuthorizer):
    """档位鉴权：scope → 最低档位。如 {"rag.query": Tier.PRO}。

    特殊键 ``"*"`` 可作为兜底（默认拒绝：未列出即 deny）。
    """

    def __init__(self, policy: Optional[dict[str, Tier]] = None) -> None:
        self._policy = dict(policy or {})
        self._fallback = self._policy.get("*", None)  # None 表示未配置则拒绝

    def authorize(self, ctx: AuthContext, scope: str) -> Decision:
        p = ctx.principal
        if p is None:
            return Decision.deny("unauthenticated")
        required = self._policy.get(scope, self._fallback)
        if required is None:
            return Decision.deny(f"scope '{scope}' 未在策略中，默认拒绝")
        if p.tier == Tier.ADMIN:
            return Decision.allow_reason("admin bypass")
        if _tier_rank(p.tier) >= _tier_rank(required):
            return Decision.allow_reason(f"{p.tier.value} >= {required.value}")
        return Decision.deny(f"need tier {required.value}, got {p.tier.value}")


class PermissionAuthorizer(BaseAuthorizer):
    """权限标识鉴权：scope → 所需 permission。如 {"ai:chat": "ai:chat"}。

    支持通配权限：principal 拥有 ``"*"`` 时全部放行。
    """

    def __init__(self, required: Optional[dict[str, str]] = None) -> None:
        self._required = dict(required or {})

    def authorize(self, ctx: AuthContext, scope: str) -> Decision:
        p = ctx.principal
        if p is None:
            return Decision.deny("unauthenticated")
        if p.tier == Tier.ADMIN or "*" in p.permissions:
            return Decision.allow_reason("admin/wildcard bypass")
        need = self._required.get(scope)
        if need is None:
            return Decision.deny(f"scope '{scope}' 未定义所需权限")
        if p.has_permission(need):
            return Decision.allow_reason(f"has permission '{need}'")
        return Decision.deny(f"missing permission '{need}'")


def _tier_rank(tier: Tier) -> int:
    return {Tier.FREE: 0, Tier.BASIC: 1, Tier.PRO: 2, Tier.ADMIN: 3}[tier]
