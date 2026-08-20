"""Tenet security 模块测试（pytest）。"""

import sqlite3

from tenet.security import (
    HmacAuthenticator,
    SqliteAuditor,
    StubAuthenticator,
    TierAuthorizer,
    init_security,
)
from tenet.security.models import AuditEvent, Principal


def test_hmac_issue_and_verify():
    auth = HmacAuthenticator("test-secret")
    token = auth.issue("alice", tier="pro", scopes=["rag.query"])
    p = auth.authenticate(token)
    assert p is not None
    assert p.user_id == "alice"
    assert p.tier == "pro"
    assert "rag.query" in p.scopes


def test_hmac_rejects_tampered():
    auth = HmacAuthenticator("test-secret")
    token = auth.issue("alice")
    bad = token[:-4] + ("abcd" if token[-4:] != "abcd" else "wxyz")
    assert auth.authenticate(bad) is None


def test_hmac_rejects_expired():
    auth = HmacAuthenticator("test-secret")
    token = auth.issue("alice", ttl_seconds=0)
    assert auth.authenticate(token) is None


def test_hmac_requires_secret():
    import os

    old = os.environ.pop("TENET_AUTH_SECRET", None)
    try:
        try:
            HmacAuthenticator()
            assert False, "应抛出缺少密钥异常"
        except ValueError:
            pass
    finally:
        if old is not None:
            os.environ["TENET_AUTH_SECRET"] = old


def test_stub_authenticator():
    auth = StubAuthenticator()
    assert auth.authenticate("anything").user_id == "local-dev"


def test_tier_authorizer():
    authz = TierAuthorizer()
    free = Principal("u1", tier="free")
    pro = Principal("u2", tier="pro")
    assert authz.authorize(free, "ask").allowed
    assert not authz.authorize(free, "rag.query").allowed
    assert authz.authorize(pro, "rag.query").allowed
    assert not authz.authorize(pro, "admin").allowed
    assert not authz.authorize(pro, "unknown").allowed


def test_sqlite_auditor_roundtrip(tmp_path):
    db = tmp_path / "audit.db"
    auditor = SqliteAuditor(db)
    auditor.record(
        AuditEvent(action="rag.query", user_id="alice", tier="pro", intent="search", status="ok")
    )
    auditor.close()
    conn = sqlite3.connect(str(db))
    n = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    row = conn.execute("SELECT user_id, tier, action FROM audit_log").fetchone()
    assert n == 1
    assert row == ("alice", "pro", "rag.query")


def test_init_security_stub_and_null():
    ctx = init_security(auth="stub", audit="null")
    p = ctx["authenticator"].authenticate("x")
    assert p is not None and p.user_id == "local-dev"
    ctx["auditor"].record(AuditEvent(action="ask", user_id="local-dev"))
