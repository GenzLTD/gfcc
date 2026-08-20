"""Tatha 运行时系统签发（SystemMinter）+ 超管 mint 端点验证。

覆盖：
1. 系统自动签发：bootstrap 签出标准 JWT，ethos 能验通（tier=admin → Tatha pro）；
   有效期内幂等复用；过期自动续签（全程无人干预）。
2. 超管 mint：mint_for 签任意主体令牌可验通；is_super_admin 判定。
3. bootstrap 审计 system.token.issued 落库（可溯源）。
4. /v1/admin/tokens 端点：无 token 401、stub 模式 403、非超管 403、超管 200 并落审计 admin.mint。
5. stub 模式（未配置 ETHOS_AUTH_SECRET）：minter 不可用，不签发任何令牌。
"""

from __future__ import annotations

import os
import sqlite3
import time

import pytest
from fastapi import HTTPException

from tatha.api.app import AdminMintRequest, admin_mint_token
from tatha.api.security import SecurityService, SystemMinter, is_super_admin

_SECRET = "integration-test-secret"


def _reset_env(secret: str | None, audit_db: str | None) -> None:
    if secret is None:
        os.environ.pop("ETHOS_AUTH_SECRET", None)
    else:
        os.environ["ETHOS_AUTH_SECRET"] = secret
    if audit_db is None:
        os.environ.pop("ETHOS_AUDIT_DB", None)
    else:
        os.environ["ETHOS_AUDIT_DB"] = audit_db


@pytest.fixture()
def hmac_env(tmp_path):
    """设置 HMAC 严格模式 + 隔离审计库，并重建 app 模块级 security 单例。"""
    _reset_env(_SECRET, str(tmp_path / "audit.db"))
    from tatha.api import app as _app_mod

    _app_mod.security = SecurityService()
    yield _app_mod
    _reset_env(None, None)
    _app_mod.security = SecurityService()


class TestSystemMinter:
    def test_bootstrap_token_verifiable_by_ethos(self, hmac_env) -> None:
        svc = SecurityService()
        token = svc.minter.bootstrap()
        assert token.count(".") == 2
        auth = svc.authenticate(token)
        assert auth is not None
        assert auth.user_id == "svc:tatha"
        assert auth.tier == "pro"  # admin 档在 Tatha 按 pro 处理

    def test_bootstrap_idempotent_within_ttl(self, hmac_env) -> None:
        svc = SecurityService()
        assert svc.minter.bootstrap() == svc.minter.bootstrap()

    def test_bootstrap_renews_after_expiry(self, hmac_env) -> None:
        svc = SecurityService()
        m = svc.minter
        m.bootstrap()
        old_exp = m._current_exp
        m._current_exp = time.time() - 1  # 模拟过期
        t2 = m.bootstrap()
        # 续签发生：过期时间延长（JWT 秒级 iat，同秒重签内容可相同，不断言 token 字符串差异）
        assert m._current_exp > old_exp
        auth = svc.authenticate(t2)
        assert auth is not None and auth.user_id == "svc:tatha"

    def test_get_system_token_auto_renews(self, hmac_env) -> None:
        svc = SecurityService()
        t1 = svc.get_system_token()
        assert t1 is not None
        assert svc.get_system_token() == t1  # 有效期内复用

    def test_mint_token_verifiable(self, hmac_env) -> None:
        svc = SecurityService()
        token = svc.mint_for("u-77", "pro", ["user"])
        auth = svc.authenticate(token)
        assert auth.user_id == "u-77"
        assert auth.tier == "pro"

    def test_mint_admin_principal(self, hmac_env) -> None:
        svc = SecurityService()
        token = svc.mint_for("root-1", "admin", ["admin"])
        principal = svc.verify_principal(token)
        assert principal is not None
        assert principal.tier.value == "admin"
        assert is_super_admin(principal)


class TestStubMode:
    def test_minter_disabled_without_secret(self) -> None:
        _reset_env(None, None)
        svc = SecurityService()
        assert not svc.minter.enabled
        assert svc.get_system_token() is None
        with pytest.raises(RuntimeError):
            svc.minter.bootstrap()
        with pytest.raises(RuntimeError):
            svc.mint_for("u-1", "free")
        assert svc.bootstrap() is None  # 门面返回 None，不抛


class TestSuperAdmin:
    def test_is_super_admin(self) -> None:
        from ethos.models import Principal, Tier

        assert is_super_admin(Principal(sub="a", tier=Tier.ADMIN))
        assert is_super_admin(Principal(sub="a", tier=Tier.FREE, roles=["super_admin"]))
        assert is_super_admin(Principal(sub="a", tier=Tier.FREE, roles=["system"]))
        assert is_super_admin(Principal(sub="a", tier=Tier.FREE, roles=["root"]))
        assert not is_super_admin(Principal(sub="a", tier=Tier.FREE, roles=["user"]))
        assert not is_super_admin(Principal(sub="a", tier=Tier.FREE, roles=[]))


class TestBootstrapAudit:
    def test_bootstrap_audits_token_issued(self, hmac_env, tmp_path) -> None:
        svc = SecurityService()
        svc.bootstrap()
        conn = sqlite3.connect(tmp_path / "audit.db")
        action, user_id, meta = conn.execute(
            "SELECT action, user_id, meta FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert action == "system.token.issued"
        assert user_id == "svc:tatha"
        assert "auto-issued" in meta


class TestAdminMintEndpoint:
    def test_missing_token_401(self, hmac_env) -> None:
        with pytest.raises(HTTPException) as ei:
            admin_mint_token(AdminMintRequest(sub="x"), None)
        assert ei.value.status_code == 401

    def test_stub_mode_403(self, tmp_path) -> None:
        _reset_env(None, str(tmp_path / "audit.db"))
        from tatha.api import app as _app_mod

        _app_mod.security = SecurityService()
        try:
            with pytest.raises(HTTPException) as ei:
                admin_mint_token(AdminMintRequest(sub="x"), "Bearer demo-token")
            assert ei.value.status_code == 403
        finally:
            _reset_env(None, None)
            _app_mod.security = SecurityService()

    def test_non_superadmin_403(self, hmac_env) -> None:
        svc = hmac_env.security
        user_token = svc.mint_for("u-1", "free", ["user"])
        with pytest.raises(HTTPException) as ei:
            admin_mint_token(AdminMintRequest(sub="x"), f"Bearer {user_token}")
        assert ei.value.status_code == 403

    def test_superadmin_mints_and_audits(self, hmac_env, tmp_path) -> None:
        svc = hmac_env.security
        admin_token = svc.minter.bootstrap()  # 系统令牌即超管（roles=[system]）
        resp = admin_mint_token(
            AdminMintRequest(sub="svc:new", tier="pro", roles=["user"]),
            f"Bearer {admin_token}",
        )
        assert resp["ok"] is True
        auth = svc.authenticate(resp["token"])
        assert auth.user_id == "svc:new"
        assert auth.tier == "pro"

        conn = sqlite3.connect(tmp_path / "audit.db")
        action, detail = conn.execute(
            "SELECT action, meta FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert action == "admin.mint"
        assert "svc:new" in detail

    def test_invalid_tier_422(self, hmac_env) -> None:
        svc = hmac_env.security
        admin_token = svc.minter.bootstrap()
        with pytest.raises(HTTPException) as ei:
            admin_mint_token(AdminMintRequest(sub="x", tier="vip"), f"Bearer {admin_token}")
        assert ei.value.status_code == 422

    def test_empty_sub_422(self, hmac_env) -> None:
        svc = hmac_env.security
        admin_token = svc.minter.bootstrap()
        with pytest.raises(HTTPException) as ei:
            admin_mint_token(AdminMintRequest(sub="   "), f"Bearer {admin_token}")
        assert ei.value.status_code == 422
