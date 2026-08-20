"""鉴权：Principal + action → AuthDecision。基于 tier 的策略引擎。

策略：每个 action 映射一个"所需最低 tier"，主体验权时按 tier 等级比较。
默认策略与对外供给层对齐：
    ask / search           → free（基础能力）
    rag.query / memory.*   → pro （知识库 / 记忆体）
    admin                  → admin
"""

from __future__ import annotations

from typing import Mapping, Optional, Protocol

from .models import AuthDecision, Principal


class Authorizer(Protocol):
    def authorize(self, principal: Principal, action: str, resource: str = "") -> AuthDecision:
        ...


DEFAULT_POLICY: dict[str, str] = {
    "ask": "free",
    "search": "free",
    "rag.query": "pro",
    "memory.read": "pro",
    "memory.write": "pro",
    "admin": "admin",
}

TIER_RANK: dict[str, int] = {"free": 0, "pro": 1, "admin": 2}


class TierAuthorizer:
    """按 tier 等级鉴权。policy 可整体替换或局部覆盖。"""

    def __init__(self, policy: Optional[Mapping[str, str]] = None) -> None:
        merged = dict(DEFAULT_POLICY)
        if policy:
            merged.update(policy)
        self._policy = merged

    def authorize(self, principal: Principal, action: str, resource: str = "") -> AuthDecision:
        if principal.expired:
            return AuthDecision.deny("身份已过期")
        required = self._policy.get(action)
        if required is None:
            return AuthDecision.deny(f"未知操作: {action}")
        if TIER_RANK.get(principal.tier, -1) < TIER_RANK.get(required, 99):
            return AuthDecision.deny(
                f"tier={principal.tier} 无权执行 {action}（需要 {required}）"
            )
        return AuthDecision.allow()
