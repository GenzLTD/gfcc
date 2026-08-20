"""
Ethos security 三件套（认证 / 鉴权 / 审计）+ 运行时系统签发（SystemMinter）在 Tatha 的接入层。

设计（ethos 库保持"纯验证者"——验签/鉴权/审计，不签发；签发属应用层行为）：
- 认证：配置了 ETHOS_AUTH_SECRET → ethos HS256 严格校验（验签标准 JWT）；
  未配置 → 保持现状（远程量子 / stub 联调链），ethos 不接管认证。
- 鉴权：ethos TierAuthorizer，按 action 策略放行（ask=free 起，rag.query=pro 起）。
- 审计：每次请求落 SQLite（默认 <TATHA_ROOT>/logs/audit.db，ETHOS_AUDIT_DB 可覆盖）。
- 签发（SystemMinter，运行时自动 + 超管例外）：
  · 服务启动 bootstrap() 自动签系统令牌（svc:tatha，tier=admin，roles=[system]），过期惰性续签；
  · login/register 等业务接口不签发（不被人为左右）；
  · /v1/admin/tokens 仅超管/系统主体（tier=admin 或 roles 含 admin/system）可按需签发。

tier 映射：Tatha 三档 free/basic/pro ↔ ethos free/basic/pro（一一对应，不再折叠 basic）。

注意（ethos 纯验证者带来的行为差异）：
- 业务接口不再签发令牌：issue_token 恒返回 None，login/register 回落 demo-token；
  真实用户令牌由外部签发方（Go 8207 / Rust 网关 / 其他 HS256 签发方）签发后，Tatha 只验签。
- 不兼容 tenet 令牌格式：tenet 签名是 hex，ethos 只认标准 JWT（base64url 签名）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Optional

from ethos.models import AuthContext as EthosAuthContext
from ethos.models import Principal
from ethos.models import Tier as EthosTier
from ethos.security import Decision, init_security

from .auth import AuthContext, Tier

def _default_audit_path() -> str:
    """审计库默认位置：跟随 Tatha（logs/audit.db），ETHOS_AUDIT_DB 可覆盖。"""
    return os.getenv("ETHOS_AUDIT_DB") or str(
        Path(__file__).resolve().parent.parent.parent.parent / "logs" / "audit.db"
    )

# Tatha action → 最低档位（与 tenet 版策略对齐：ask=free 起，rag.query=pro 起；
# 未列出的 action 默认拒绝，deny by default）
_TIER_POLICY: dict[str, str] = {
    "ask": "free",
    "jobs.match": "free",
    "rag.query": "pro",
    "documents.convert": "free",
}

# Tatha tier → ethos tier（一一对应）
_TIER_TO_ETHOS: dict[Tier, str] = {"free": "free", "basic": "basic", "pro": "pro"}
# ethos tier → Tatha tier（未知档位回落 free；admin 在 Tatha 无对应，按 pro 处理）
TIER_TO_TATHA: dict[str, Tier] = {"free": "free", "basic": "basic", "pro": "pro", "admin": "pro"}


def _b64url(data: bytes) -> str:
    """标准 base64url（去填充），与 ethos 验签端一致。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_hs256(secret: str, claims: dict, ttl: int) -> str:
    """签发标准 JWT（HS256，base64url 签名）——与网关协议 §1、ethos 验签端一致。

    签出的令牌必须能被 ethos `HmacJwtVerifier` 验通：header {alg: HS256, typ: JWT}，
    payload 含 iat/exp 及网关协议约定的宽容 Claims 键。
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**claims, "iat": now, "exp": now + ttl}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), f"{h}.{p}".encode("ascii"), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


# 超管/系统主体判定：tier=admin 直接为真；否则看 roles 是否含系统/管理角色
_SUPER_ROLES = frozenset({"admin", "super_admin", "super-admin", "root", "system"})


def is_super_admin(principal: Principal) -> bool:
    """超管/系统主体判定（供 /v1/admin/tokens 端点使用）。"""
    if principal.tier == EthosTier.ADMIN:
        return True
    return bool(_SUPER_ROLES & {r.lower() for r in (principal.roles or [])})


class SystemMinter:
    """运行时系统签发器（仅 HMAC 严格模式可用，secret 非空）。

    原则（用户指定）：
    - 运行时系统自动签发：服务启动 bootstrap() 自动签系统令牌，过期惰性续签，全程无人干预；
    - 不被人为左右：login/register 等业务接口不签发，普通请求不可能触发签发；
    - 超级管理员例外：/v1/admin/tokens 持超管/系统令牌者可按需签发（mint）。
    """

    def __init__(self, secret: str, *, system_sub: str = "svc:tatha", ttl: int = 3600) -> None:
        self._secret = secret
        self._system_sub = system_sub
        self._ttl = ttl
        self._current: Optional[str] = None
        self._current_exp: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._secret)

    def bootstrap(self) -> str:
        """系统启动时自动签发系统令牌（tier=admin，roles=[system]）。

        幂等：有效期内复用现有令牌；过期才重新签发（惰性续签）。
        未配置 secret（联调 stub 模式）时拒绝签发。
        """
        if not self.enabled:
            raise RuntimeError("SystemMinter 未启用：需要配置 ETHOS_AUTH_SECRET")
        now = time.time()
        if self._current and self._current_exp > now:
            return self._current
        self._current = _sign_hs256(
            self._secret,
            {"sub": self._system_sub, "tier": "admin", "roles": ["system"]},
            self._ttl,
        )
        self._current_exp = now + self._ttl
        return self._current

    def get_token(self) -> Optional[str]:
        """取当前系统令牌；未就绪/过期则自动续签（系统自动，无需人工）。"""
        if not self.enabled:
            return None
        return self.bootstrap()

    def mint(
        self,
        sub: str,
        tier: str = "free",
        roles: Optional[list[str]] = None,
        ttl: int = 3600,
    ) -> str:
        """按需签发任意主体令牌（仅超管端点调用）；未配置 secret 时拒绝。"""
        if not self.enabled:
            raise RuntimeError("SystemMinter 未启用：需要配置 ETHOS_AUTH_SECRET")
        return _sign_hs256(self._secret, {"sub": sub, "tier": tier, "roles": roles or []}, ttl)


class SecurityService:
    """ethos security 三件套的 Tatha 门面。"""

    def __init__(self) -> None:
        # secret 留空 → ethos StubVerifier（仅联调放行，不接管认证链，与 tenet 版一致）
        self._sec = init_security(
            secret=os.getenv("ETHOS_AUTH_SECRET") or None,
            tier_policy=_TIER_POLICY,
            audit_db=_default_audit_path(),
        )
        # 运行时系统签发器（同一 secret；未配置时 disabled，不签发任何令牌）
        self._minter = SystemMinter(os.getenv("ETHOS_AUTH_SECRET") or "")

    @property
    def hmac_enabled(self) -> bool:
        """是否处于 HMAC 严格模式（配置了 ETHOS_AUTH_SECRET）。"""
        return bool(os.getenv("ETHOS_AUTH_SECRET"))

    @property
    def minter(self) -> SystemMinter:
        """运行时系统签发器（系统自动签发 + 超管 mint 的底层实现）。"""
        return self._minter

    # ---- 认证 ----

    def authenticate(self, token: str) -> Optional[AuthContext]:
        """
        ethos 认证入口：仅 HMAC 模式接管（严格验签标准 JWT，失败返回 None）。
        未配置 ETHOS_AUTH_SECRET 时返回 None，由上层回落现有 stub/远程链。
        """
        if not self.hmac_enabled:
            return None
        ctx = self._sec.verify(token)
        # deny by default：验签通过但 uid 为空（无 sub/user_id/uid）→ 视为匿名，拒绝。
        # ethos 验签对缺失 uid 宽容（Claims 键兼容），但 Tatha 业务必须持有真实身份。
        if not ctx.ok or ctx.principal is None or not ctx.principal.user_id:
            return None
        return AuthContext(
            user_id=ctx.principal.user_id,
            tier=TIER_TO_TATHA.get(ctx.principal.tier.value, "free"),
        )

    def issue_token(self, user_id: str, tier: Tier = "free") -> Optional[str]:
        """
        业务接口不签发令牌（不被人为左右），恒返回 None。
        login/register 由此回落 demo-token；真实令牌由外部签发方（Go 8207 / Rust 网关 /
        Supabase）签发后，Tatha 只负责验签（authenticate）。
        """
        return None

    # ---- 签发（运行时自动 + 超管例外，SystemMinter）----

    def bootstrap(self) -> Optional[str]:
        """服务启动时自动签发系统令牌并审计 system.token.issued（仅 HMAC 模式）。

        由 FastAPI startup 调用；过期后 get_system_token 惰性续签并再次审计。
        """
        if not self.hmac_enabled:
            return None
        token = self._minter.bootstrap()
        self.audit(
            auth=AuthContext(
                user_id=self._minter._system_sub,
                tier=TIER_TO_TATHA.get("admin", "pro"),
            ),
            action="system.token.issued",
            resource="system",
            status="ok",
            detail="runtime auto-issued system token",
        )
        return token

    def get_system_token(self) -> Optional[str]:
        """取当前系统令牌（内部服务调用用）；未就绪/过期自动续签，无需人工。"""
        return self._minter.get_token() if self.hmac_enabled else None

    def mint_for(
        self,
        sub: str,
        tier: str = "free",
        roles: Optional[list[str]] = None,
        ttl: int = 3600,
    ) -> str:
        """按需签发任意主体令牌（仅 /v1/admin/tokens 超管端点调用）。

        调用方必须已确认 HMAC 严格模式（hmac_enabled），否则拒绝。
        """
        if not self.hmac_enabled:
            raise RuntimeError("mint 需要配置 ETHOS_AUTH_SECRET（HMAC 严格模式）")
        return self._minter.mint(sub, tier, roles, ttl)

    def verify_principal(self, token: str) -> Optional[Principal]:
        """验签并返回 ethos Principal（含 tier/roles），供超管判定；失败返回 None。"""
        if not self.hmac_enabled:
            return None
        ctx = self._sec.verify(token)
        if not ctx.ok or ctx.principal is None:
            return None
        return ctx.principal

    # ---- 鉴权 ----

    def authorize(self, auth: AuthContext, action: str, resource: str = "") -> Decision:
        """按 ethos 档位策略鉴权（free/basic/pro/admin 有序比较，admin 直接放行）。"""
        principal = Principal(
            sub=auth.user_id,
            tier=EthosTier(_TIER_TO_ETHOS.get(auth.tier, "free")),
        )
        ectx = EthosAuthContext(token="", verified=True, principal=principal)
        return self._sec.authorize(ectx, action)

    # ---- 审计 ----

    def audit(
        self,
        *,
        auth: AuthContext,
        action: str,
        resource: str = "",
        intent: str = "",
        status: str = "ok",
        latency_ms: int = 0,
        quota_after: int = -1,
        request_id: str = "",
        detail: str = "",
    ) -> None:
        """记一条审计事件（同步落 SQLite，开销 ~1ms 级）。"""
        self._sec.audit(
            action=action,
            principal=Principal(
                sub=auth.user_id,
                tier=EthosTier(_TIER_TO_ETHOS.get(auth.tier, "free")),
            ),
            resource=resource,
            meta={
                "intent": intent,
                "status": status,
                "latency_ms": latency_ms,
                "quota_after": quota_after,
                "request_id": request_id,
                "detail": detail,
            },
        )

    def close(self) -> None:
        """ethos Auditor 无需显式关闭（连接按需复用）。保留方法以兼容调用方。"""
        pass


# 模块级单例：整个进程共享一套 security（审计线程安全，SQLite check_same_thread=False）
security = SecurityService()
