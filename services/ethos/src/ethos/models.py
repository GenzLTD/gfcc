"""共享数据模型（dataclass，零依赖，跨模块通用）。

与 tenet 的差异：这是"纯验证者"模型——只承载"验证后"的语义，
不包含任何签发逻辑。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# 身份模型
# --------------------------------------------------------------------------- #

class Tier(str, Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    """验证通过后解析出的主体身份。

    字段尽量宽容（兼容 Go/Rust 两套 Claims 命名），
    通过 ``.tier`` / ``.permissions`` 提供统一视图。
    """

    sub: str                       # 唯一用户标识（Claims.sub，兼容 user_id）
    tier: Tier = Tier.FREE         # 统一档位视图
    roles: List[str] = field(default_factory=list)      # 全部角色（兼容单值 role）
    permissions: List[str] = field(default_factory=list)  # 全部权限标识
    scopes: List[str] = field(default_factory=list)      # OAuth 风格 scopes（可选）
    username: Optional[str] = None
    tenant_type: Optional[str] = None
    claims: Dict[str, Any] = field(default_factory=dict)  # 原始 Claims 全文（保留）
    exp: Optional[int] = None      # 过期时间（unix 秒）
    iat: Optional[int] = None      # 签发时间

    # -- 兼容视图 ---------------------------------------------------------- #

    @property
    def user_id(self) -> str:
        """跨端统一 uid：优先 sub，退化到 user_id/uid 字段。"""
        if self.sub:
            return self.sub
        return str(self.claims.get("user_id") or self.claims.get("uid") or "")

    @property
    def role(self) -> str:
        """单角色兼容：roles 非空取第一个，否则取原始 role 字段。"""
        if self.roles:
            return self.roles[0]
        return str(self.claims.get("role") or "")

    def has_permission(self, permission: str) -> bool:
        if self.tier == Tier.ADMIN:
            return True
        return permission in self.permissions or permission in self.scopes

    @property
    def is_expired(self, now: Optional[int] = None) -> bool:
        if self.exp is None:
            return False
        return (now or int(time.time())) > self.exp


@dataclass
class AuthContext:
    """一次请求的完整认证上下文（中间件产物）。"""

    token: Optional[str] = None
    principal: Optional[Principal] = None
    error: Optional[str] = None          # 认证失败原因
    verified: bool = False
    verifier: str = ""                   # 使用的验证器名
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verified and self.principal is not None


# --------------------------------------------------------------------------- #
# 配额模型
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class QuotaLimit:
    """某个资源类型的配额上限定义。"""

    resource: str
    daily: int = 0                 # 每日上限；0 表示不限制
    amount_per_call: int = 1       # 单次消耗量
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuotaState:
    """配额查询/检查结果。"""

    resource: str
    remaining: int
    limit: int
    ok: bool = True                # 是否仍可消耗
    message: str = ""

    @property
    def used(self) -> int:
        return max(self.limit - self.remaining, 0)


# --------------------------------------------------------------------------- #
# 审计模型
# --------------------------------------------------------------------------- #

class AuditEvent:
    """审计事件载体（dataclass 但容忍任意字段，便于上报序列化）。"""

    __slots__ = ("action", "principal", "resource", "meta", "ts")

    def __init__(
        self,
        action: str,
        principal: Optional[Principal] = None,
        resource: str = "",
        meta: Optional[Dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> None:
        self.action = action
        self.principal = principal
        self.resource = resource
        self.meta = dict(meta or {})
        self.ts = ts if ts is not None else time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "action": self.action,
            "resource": self.resource,
            "user_id": self.principal.user_id if self.principal else "",
            "tier": self.principal.tier.value if self.principal else "",
            **self.meta,
        }
