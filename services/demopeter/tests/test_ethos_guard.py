"""DemoPeter × ethos 接入测试：双模（Stub 放行 / HMAC 严格）+ 豁免 + 映射。

跑法（用 Tatha venv，ethos 为 editable 安装）：
    & D:\\surface-zervi\\GitHub\\szjason72\\Tatha\\.venv\\Scripts\\python.exe -m pytest tests/test_ethos_guard.py -v
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from flask import Flask, jsonify

from config.settings import config
from src.ethos_bootstrap import _action_for, get_security, init_ethos_guard

SECRET = "test-secret-ethos"


def _jwt(secret: str, claims: dict, ttl: int = 3600) -> str:
    """按网关协议签标准 HS256 JWT（与 ethos 验签端一致）。"""

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**claims, "iat": now, "exp": now + ttl}
    h = b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), f"{h}.{p}".encode("ascii"), hashlib.sha256).digest()
    return f"{h}.{p}.{b64(sig)}"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    # 审计库落到临时目录，避免污染 db/
    monkeypatch.setattr(config, "DB_DIR", tmp_path)
    app = Flask(__name__)
    init_ethos_guard(app)

    @app.route("/api/rag/query", methods=["POST"])
    def _query():
        return jsonify({"answer": "mock-answer"})

    @app.route("/api/health/config")
    def _health():
        return jsonify({"ok": True})

    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def _set_stub(monkeypatch):
    monkeypatch.delenv("ETHOS_AUTH_SECRET", raising=False)
    get_security.cache_clear()


def _set_hmac(monkeypatch):
    monkeypatch.setenv("ETHOS_AUTH_SECRET", SECRET)
    get_security.cache_clear()


# ---- 双模 ---------------------------------------------------------------- #

def test_stub_mode_allows_no_token(client, monkeypatch):
    _set_stub(monkeypatch)
    resp = client.post("/api/rag/query", json={"query": "hello"})
    assert resp.status_code == 200
    assert resp.get_json()["answer"] == "mock-answer"


def test_hmac_requires_token(client, monkeypatch):
    _set_hmac(monkeypatch)
    resp = client.post("/api/rag/query", json={"query": "hello"})
    assert resp.status_code == 401


def test_hmac_free_denied_rag_query(client, monkeypatch):
    _set_hmac(monkeypatch)
    tok = _jwt(SECRET, {"sub": "u1", "tier": "free"})
    resp = client.post(
        "/api/rag/query", json={"query": "hello"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 403


def test_hmac_pro_allowed_rag_query(client, monkeypatch):
    _set_hmac(monkeypatch)
    tok = _jwt(SECRET, {"sub": "u2", "tier": "pro"})
    resp = client.post(
        "/api/rag/query", json={"query": "hello"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200


def test_hmac_admin_allowed(client, monkeypatch):
    """Tatha 系统令牌（svc:tatha, tier=admin）应可直接调度。"""
    _set_hmac(monkeypatch)
    tok = _jwt(SECRET, {"sub": "svc:tatha", "tier": "admin", "roles": ["system"]})
    resp = client.post(
        "/api/rag/query", json={"query": "hello"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200


def test_hmac_admin_allowed_d_index_clear(client, monkeypatch):
    _set_hmac(monkeypatch)
    tok = _jwt(SECRET, {"sub": "svc:tatha", "tier": "admin", "roles": ["system"]})
    resp = client.post(
        "/api/d-index/clear",
        headers={"Authorization": f"Bearer {tok}"},
    )
    # 路由未定义会 404，但 guard 已放行（不再 401/403）即证明 admin 通过
    assert resp.status_code == 404


def test_hmac_free_denied_d_index_clear(client, monkeypatch):
    _set_hmac(monkeypatch)
    tok = _jwt(SECRET, {"sub": "u1", "tier": "free"})
    resp = client.post("/api/d-index/clear", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 403


# ---- 豁免 ---------------------------------------------------------------- #

def test_health_exempt_without_token(client, monkeypatch):
    _set_hmac(monkeypatch)
    resp = client.get("/api/health/config")
    assert resp.status_code == 200


def test_non_api_path_exempt(client, monkeypatch):
    _set_hmac(monkeypatch)
    resp = client.get("/")
    # 页面路由不在 /api/* 前缀，guard 直通 → 404（模板不存在）而非 401
    assert resp.status_code == 404


# ---- 映射 ---------------------------------------------------------------- #

def test_action_mapping():
    assert _action_for("/api/rag/query") == "rag.query"
    assert _action_for("/api/rag/stream") == "rag.query"
    assert _action_for("/api/reports/generate") == "rag.query"
    assert _action_for("/api/documents/upload") == "memory.write"
    assert _action_for("/api/documents/import") == "memory.write"
    assert _action_for("/api/d-index/clear") == "admin"
    assert _action_for("/api/d-index/checkpoint/reset") == "admin"
    assert _action_for("/api/stats") == "search"
    assert _action_for("/api/documents") == "search"
    assert _action_for("/api/d-index/search") == "search"
    assert _action_for("/api/whatever/else") == "search"
