"""ethos.security：纯验证者认证 + 库内配额（可插拔远程）+ 本地审计（可选上报）。

装配入口：init_security(...)  → SecurityProvider（组合 verifier + authorizer + quota + auditor）。

用法（与 tenet.init_security 对齐，但 ethos 不签发令牌）:

    from ethos.security import init_security, SecurityProvider
    sec = init_security(
        secret="...",                # 留空 → StubVerifier（本地联调放行）
        tier_policy={"rag.query": "pro"},
        quota_limits={"rag.query": QuotaLimit("rag.query", daily=100)},
        audit_db="logs/audit.db",    # None → 关闭本地审计
    )
    ctx = sec.verify(token)
    sec.authorize(ctx, "rag.query")
    sec.consume_quota(ctx, "rag.query")
    sec.audit("rag.query", ctx.principal)
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .. import registry as _registry
from ..models import AuthContext, QuotaLimit, Tier
from .auditor import Auditor, JsonlAuditor, NullAuditor, SqliteAuditor
from .authorizer import (
    BaseAuthorizer,
    Decision,
    PermissionAuthorizer,
    TierAuthorizer,
)
from .quota import (
    LocalQuotaBackend,
    QuotaBackend,
    QuotaManager,
    RemoteQuotaBackend,
)
from .verifier import (
    HmacJwtVerifier,
    StubVerifier,
    TokenVerifier,
)

__all__ = [
    "init_security",
    "SecurityProvider",
    "TokenVerifier",
    "HmacJwtVerifier",
    "StubVerifier",
    "TierAuthorizer",
    "PermissionAuthorizer",
    "QuotaManager",
    "LocalQuotaBackend",
    "RemoteQuotaBackend",
    "Auditor",
    "SqliteAuditor",
    "JsonlAuditor",
    "NullAuditor",
]


class SecurityProvider:
    """认证/鉴权/配额/审计的组合门面（一次装配，四处调用）。"""

    def __init__(
        self,
        verifier: TokenVerifier,
        authorizer: BaseAuthorizer,
        quota: QuotaManager,
        auditor: Auditor,
    ) -> None:
        self.verifier = verifier
        self.authorizer = authorizer
        self.quota = quota
        self.auditor = auditor
        self._lock = False

    # -- 认证 ------------------------------------------------------------- #

    def verify(self, token: str) -> AuthContext:
        return self.verifier.verify(token)

    # -- 鉴权 ------------------------------------------------------------- #

    def authorize(self, ctx: AuthContext, scope: str) -> Decision:
        return self.authorizer.authorize(ctx, scope)

    def require(self, ctx: AuthContext, scope: str) -> AuthContext:
        """鉴权不过则抛 PermissionError（用于中间件快速失败）。"""
        decision = self.authorizer.authorize(ctx, scope)
        if not decision:
            raise PermissionError(f"{scope}: {decision.reason}")
        return ctx

    # -- 配额 ------------------------------------------------------------- #

    def check_quota(self, ctx: AuthContext, resource: str) -> Any:
        if ctx.principal is None:
            return False
        return self.quota.check(ctx.principal.user_id, resource)

    def consume_quota(self, ctx: AuthContext, resource: str, amount: int = 1) -> Any:
        if ctx.principal is None:
            return False
        return self.quota.consume(ctx.principal.user_id, resource, amount=amount)

    # -- 审计 ------------------------------------------------------------- #

    def audit(
        self,
        action: str,
        ctx: Optional[AuthContext] = None,
        principal: Any = None,
        resource: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        p = principal if principal is not None else (ctx.principal if ctx else None)
        self.auditor.record(action=action, principal=p, resource=resource, meta=meta)


def init_security(
    secret: Optional[str] = None,
    verifier: Optional[TokenVerifier] = None,
    authorizer: Optional[BaseAuthorizer] = None,
    tier_policy: Optional[Dict[str, str]] = None,
    permission_required: Optional[Dict[str, str]] = None,
    quota_limits: Optional[Dict[str, QuotaLimit]] = None,
    quota_backend: Optional[QuotaBackend] = None,
    remote_quota_url: Optional[str] = None,
    audit_db: Optional[str] = None,
    audit_jsonl: Optional[str] = None,
    audit_reporter: Optional[Any] = None,
    extra_secrets: Optional[list[str]] = None,
) -> SecurityProvider:
    """装配 ethos.security。

    参数：
    - secret: HS256 对称密钥。留空 → StubVerifier（本地联调放行 admin）。
      环境变量优先：ETHOS_AUTH_SECRET。
    - verifier: 自定义 TokenVerifier（覆盖默认选择）。
    - tier_policy: {"scope": "free|basic|pro|admin"} → TierAuthorizer。
    - permission_required: {"scope": "perm"} → PermissionAuthorizer。
      tier_policy 与 permission_required 至少提供一个，否则默认全放行。
    - quota_limits: {resource: QuotaLimit}；quota_backend 缺省为 LocalQuotaBackend。
    - remote_quota_url: 指定则用 RemoteQuotaBackend（需 httpx）。
    - audit_db: SQLite 审计路径（None → 尝试环境变量 ETHOS_AUDIT_DB）。
    - audit_jsonl: 若提供，用 JSONL 审计（优先级低于 audit_db）。
    - audit_reporter: 可选上报器（AuditReporter 协议）。

    返回：SecurityProvider。
    """
    # 1) 验证器
    effective_secret = secret or os.getenv("ETHOS_AUTH_SECRET") or ""
    if verifier is None:
        if effective_secret:
            verifier = HmacJwtVerifier(effective_secret, extra_secrets=extra_secrets)
        else:
            verifier = StubVerifier(default_tier=Tier.ADMIN)

    # 2) 鉴权器
    if authorizer is None:
        if tier_policy:
            _policy = {k: Tier(v) for k, v in tier_policy.items()}
            authorizer = TierAuthorizer(_policy)
        elif permission_required:
            authorizer = PermissionAuthorizer(permission_required)
        else:
            # 未配置策略 → 全放行（认证即可用）
            authorizer = TierAuthorizer({"*": Tier.FREE})

    # 3) 配额
    if quota_backend is None:
        if remote_quota_url or os.getenv("ETHOS_QUOTA_URL"):
            quota_backend = RemoteQuotaBackend(
                remote_quota_url or os.getenv("ETHOS_QUOTA_URL", "")
            )
        else:
            quota_backend = LocalQuotaBackend(
                persist_path=os.getenv("ETHOS_QUOTA_PERSIST")
            )
    quota_mgr = QuotaManager(limits=quota_limits, backend=quota_backend)

    # 4) 审计
    if audit_reporter is None and os.getenv("ETHOS_AUDIT_REPORTER_URL"):
        from .reporters import HttpReporter  # noqa: PLC0415

        audit_reporter = HttpReporter(os.getenv("ETHOS_AUDIT_REPORTER_URL"))

    db_path = audit_db or os.getenv("ETHOS_AUDIT_DB")
    if db_path:
        backend = SqliteAuditor(db_path)
    elif audit_jsonl:
        backend = JsonlAuditor(audit_jsonl)
    else:
        backend = NullAuditor()
    auditor = Auditor(backend=backend, reporter=audit_reporter)

    provider = SecurityProvider(verifier, authorizer, quota_mgr, auditor)

    # 注册到全局 registry（便于按名复用 / 换实现）
    _registry.get_registry("security").register("default", provider)

    return provider
