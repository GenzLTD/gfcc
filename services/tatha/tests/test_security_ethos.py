"""Tatha × ethos 接入验证（ethos 纯验证者语义）。

覆盖：
1. Stub 联调模式（无 ETHOS_AUTH_SECRET）：authenticate 不接管认证链，
   verify_token 回落 stub free —— 行为与 tenet 版等价。
2. HMAC 严格模式（配置 ETHOS_AUTH_SECRET）：
   - 标准 JWT（Rust 风格 sub+role / Go 风格 user_id+roles[]）验签通过，uid/tier 映射正确；
   - tenet 旧格式 token（hex 签名）验签失败（不兼容，已知缺口）；
   - 过期 / 坏签名 token 失败；
   - issue_token 恒 None（纯验证者，不签发）。
3. 鉴权：free→ask 放行、free→rag.query 拒绝、pro→rag.query 放行、admin 越权放行。
4. 审计：audit 落 SQLite（ethos audit_log 表结构）。

运行：uv run pytest tests/test_security_ethos.py -v（在 Tatha 目录下）
"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time

import pytest

# 测试隔离：确保 stub 模式与远程链干净（须在 import tatha 之前）
os.environ.pop("ETHOS_AUTH_SECRET", None)
os.environ.pop("QUANTUM_AUTH_URL", None)

from tatha.api.auth import verify_token  # noqa: E402
from tatha.api.security import SecurityService  # noqa: E402

# --------------------------------------------------------------------------- #
# 测试用签发工具（ethos 是纯验证者，这里模拟"外部签发方"）
# --------------------------------------------------------------------------- #


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _issue_hs256(secret: str, claims: dict) -> str:
    """标准 JWT（HS256，base64url 签名）—— ethos 能验签的格式。"""
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def _issue_tenet_style(secret: str, claims: dict) -> str:
    """tenet 旧格式：签名是 hex 而非 base64url —— ethos 验签失败的样本。"""
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).hexdigest()
    return f"{h}.{p}.{sig}"


_SECRET = "integration-test-secret"

# --------------------------------------------------------------------------- #
# 1. Stub 联调模式（行为等价验证）
# --------------------------------------------------------------------------- #


class TestStubMode:
    def test_hmac_not_enabled_by_default(self):
        os.environ.pop("ETHOS_AUTH_SECRET", None)
        svc = SecurityService()
        assert svc.hmac_enabled is False

    def test_authenticate_does_not_own_chain_in_stub_mode(self):
        os.environ.pop("ETHOS_AUTH_SECRET", None)
        svc = SecurityService()
        assert svc.authenticate("anything") is None  # 不接管，交由上层 stub/远程

    def test_verify_token_falls_back_to_stub_free(self):
        # 无 ETHOS_AUTH_SECRET、无 QUANTUM_AUTH_URL → stub free（与 tenet 版等价）
        os.environ.pop("ETHOS_AUTH_SECRET", None)
        os.environ.pop("QUANTUM_AUTH_URL", None)
        ctx = verify_token("demo-token-x")
        assert ctx.user_id.startswith("stub-")
        assert ctx.tier == "free"

    def test_issue_token_returns_none(self):
        svc = SecurityService()
        assert svc.issue_token("user-1", "free") is None


# --------------------------------------------------------------------------- #
# 2. HMAC 严格模式（ethos 验签）
# --------------------------------------------------------------------------- #


class TestHmacMode:
    def setup_method(self):
        os.environ["ETHOS_AUTH_SECRET"] = _SECRET
        self.svc = SecurityService()

    def teardown_method(self):
        os.environ.pop("ETHOS_AUTH_SECRET", None)

    def test_rust_style_sub_role_token(self):
        token = _issue_hs256(_SECRET, {"sub": "user-123", "role": "user", "exp": int(time.time()) + 3600})
        auth = self.svc.authenticate(token)
        assert auth is not None
        assert auth.user_id == "user-123"
        assert auth.tier == "free"  # 无 tier 键 → fallback roles[0]="user" → free

    def test_go_style_user_id_roles_token(self):
        token = _issue_hs256(
            _SECRET,
            {"user_id": "u-88", "username": "alice", "roles": ["user"], "exp": int(time.time()) + 3600},
        )
        auth = self.svc.authenticate(token)
        assert auth is not None
        assert auth.user_id == "u-88"

    def test_tier_pro_token(self):
        token = _issue_hs256(
            _SECRET, {"sub": "user-1", "tier": "pro", "role": "user", "exp": int(time.time()) + 3600}
        )
        auth = self.svc.authenticate(token)
        assert auth is not None
        assert auth.user_id == "user-1"
        assert auth.tier == "pro"

    def test_tenet_style_token_rejected(self):
        # tenet 签名是 hex → ethos 验签失败（已知缺口：格式不兼容）
        token = _issue_tenet_style(_SECRET, {"sub": "user-1", "tier": "free"})
        assert self.svc.authenticate(token) is None

    def test_expired_token_rejected(self):
        token = _issue_hs256(_SECRET, {"sub": "user-1", "tier": "free", "exp": int(time.time()) - 10})
        assert self.svc.authenticate(token) is None

    def test_wrong_signature_rejected(self):
        token = _issue_hs256("other-secret", {"sub": "user-1", "tier": "free"})
        assert self.svc.authenticate(token) is None

    def test_no_sub_rejected(self):
        token = _issue_hs256(_SECRET, {"tier": "free", "exp": int(time.time()) + 3600})
        assert self.svc.authenticate(token) is None


# --------------------------------------------------------------------------- #
# 3. 鉴权（档位策略）
# --------------------------------------------------------------------------- #


class TestAuthorize:
    def setup_method(self):
        os.environ["ETHOS_AUTH_SECRET"] = _SECRET
        self.svc = SecurityService()

    def teardown_method(self):
        os.environ.pop("ETHOS_AUTH_SECRET", None)

    def _free(self):
        from tatha.api.auth import AuthContext

        return AuthContext(user_id="u-free", tier="free")

    def _pro(self):
        from tatha.api.auth import AuthContext

        return AuthContext(user_id="u-pro", tier="pro")

    def test_free_can_ask(self):
        decision = self.svc.authorize(self._free(), "ask")
        assert decision.allow is True

    def test_free_cannot_rag_query(self):
        decision = self.svc.authorize(self._free(), "rag.query")
        assert decision.allow is False
        assert decision.reason

    def test_pro_can_rag_query(self):
        decision = self.svc.authorize(self._pro(), "rag.query")
        assert decision.allow is True

    def test_admin_bypass(self):
        from tatha.api.auth import AuthContext

        admin = AuthContext(user_id="u-admin", tier="pro")
        # ethos admin 档由外部 JWT 的 tier=admin 进入；这里直接构造 ethos Principal 验证越权
        from ethos.models import AuthContext as EthosAuthContext
        from ethos.models import Principal
        from ethos.models import Tier as EthosTier

        principal = Principal(sub="u-admin", tier=EthosTier.ADMIN)
        ectx = EthosAuthContext(token="", verified=True, principal=principal)
        decision = self.svc._sec.authorize(ectx, "rag.query")
        assert decision.allow is True


# --------------------------------------------------------------------------- #
# 4. 审计（ethos audit_log 落库）
# --------------------------------------------------------------------------- #


class TestAudit:
    def test_audit_writes_sqlite(self, tmp_path):
        os.environ["ETHOS_AUDIT_DB"] = str(tmp_path / "audit.db")
        os.environ["ETHOS_AUTH_SECRET"] = _SECRET
        try:
            svc = SecurityService()
            from tatha.api.auth import AuthContext

            auth = AuthContext(user_id="user-1", tier="pro")
            svc.audit(
                auth=auth,
                action="ask",
                intent="match_jobs",
                status="ok",
                latency_ms=823,
                quota_after=4,
                request_id="req-1",
            )
            conn = sqlite3.connect(tmp_path / "audit.db")
            row = conn.execute(
                "SELECT action, user_id, tier, meta FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            assert row is not None
            assert row[0] == "ask"
            assert row[1] == "user-1"
            assert row[2] == "pro"
            assert '"intent": "match_jobs"' in row[3]
            assert '"latency_ms": 823' in row[3]
        finally:
            os.environ.pop("ETHOS_AUDIT_DB", None)
            os.environ.pop("ETHOS_AUTH_SECRET", None)
