"""auth.verify_token 的 fail-closed 回归测试（非 HMAC 模式下的量子认证链）。

背景（安全项，与 GenzLTD/Tatha PR#5 同一处缺陷）：

旧实现（本仓 services/tatha/src/tatha/api/auth.py）：

    ctx = _verify_token_remote(token)
    if ctx is not None:
        return ctx
    return _verify_token_stub(token)      # ← 远程失败也回落 stub

即 fail-open：只要量子认证服务抖动（非 200 / 超时 / 缺 user_id / 异常），
任意伪造 token 都能通过鉴权并拿到 `stub-xxx` 身份 + free 档。

风险窗口：本仓认证链为「ETHOS_AUTH_SECRET(HMAC 严格) → QUANTUM_AUTH_URL(远程) → stub」。
docker-compose 里 `ETHOS_AUTH_SECRET: ${ETHOS_AUTH_SECRET:-}` 默认为空，
一旦某套环境漏配 ETHOS_AUTH_SECRET 却配了 QUANTUM_AUTH_URL，即落入 fail-open。

修复后：一旦配置了 QUANTUM_AUTH_URL，远程校验失败一律返回 None（→ 401），
只有「未配置 QUANTUM_AUTH_URL」才走开发 stub。

本文件锁定这两条边界，防止改回 fail-open。
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

# 测试隔离：本文件只针对「非 HMAC 模式」的量子认证链，确保 ETHOS_AUTH_SECRET 为空
os.environ.pop("ETHOS_AUTH_SECRET", None)

from tatha.api import security as security_mod  # noqa: E402
from tatha.api.auth import verify_token  # noqa: E402
from tatha.api.security import SecurityService  # noqa: E402


class _QuantumStubHandler(BaseHTTPRequestHandler):
    """本地量子认证桩：状态码与响应体由测试改写。"""

    status = 200
    payload = {"user_id": "u-remote", "tier": "pro"}

    def do_GET(self):  # noqa: N802 - http.server 约定
        self._reply()

    def _reply(self):
        body = json.dumps(type(self).payload).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静音，避免污染测试输出
        pass


@pytest.fixture
def no_ethos(monkeypatch):
    """确保处于非 HMAC 模式（未配置 ETHOS_AUTH_SECRET）。"""
    monkeypatch.delenv("ETHOS_AUTH_SECRET", raising=False)
    yield


@pytest.fixture
def quantum(monkeypatch, no_ethos):
    """起一个本地量子认证桩，并把 QUANTUM_AUTH_URL 指向它。"""
    server = HTTPServer(("127.0.0.1", 0), _QuantumStubHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("QUANTUM_AUTH_URL", f"http://127.0.0.1:{port}/verify")
    monkeypatch.setattr(_QuantumStubHandler, "status", 200)
    monkeypatch.setattr(_QuantumStubHandler, "payload", {"user_id": "u-remote", "tier": "pro"})
    yield server
    server.shutdown()
    server.server_close()


def test_unconfigured_uses_dev_stub(monkeypatch, no_ethos):
    """未配置 QUANTUM_AUTH_URL → 走开发 stub（保留本地/联调便利）。"""
    monkeypatch.delenv("QUANTUM_AUTH_URL", raising=False)
    ctx = verify_token("demo-token-123")
    assert ctx is not None
    assert ctx.user_id.startswith("stub-")
    assert ctx.tier == "free"


def test_configured_remote_ok_returns_real_identity(quantum):
    """已配置且认证服务 200 → 返回真身份，不经过 stub。"""
    ctx = verify_token("a-real-token")
    assert ctx is not None
    assert ctx.user_id == "u-remote"
    assert ctx.tier == "pro"


def test_configured_remote_unreachable_is_fail_closed(monkeypatch, no_ethos):
    """已配置但认证服务不可达 → None（401），绝不回落 stub。"""
    monkeypatch.setenv("QUANTUM_AUTH_URL", "http://127.0.0.1:1/verify")  # 必然拒绝连接
    assert verify_token("forged-token") is None


def test_configured_non_200_is_fail_closed(quantum, monkeypatch):
    """已配置但认证服务非 200 → None，绝不回落 stub。"""
    monkeypatch.setattr(_QuantumStubHandler, "status", 401)
    assert verify_token("forged-token") is None


def test_configured_missing_user_id_is_fail_closed(quantum, monkeypatch):
    """已配置但响应缺 user_id → None，绝不回落 stub。"""
    monkeypatch.setattr(_QuantumStubHandler, "payload", {"tier": "pro"})
    assert verify_token("forged-token") is None


def test_configured_timeout_is_fail_closed(monkeypatch, no_ethos):
    """已配置但认证服务超时 → None，绝不回落 stub。"""
    server = HTTPServer(("127.0.0.1", 0), _QuantumStubHandler)
    port = server.server_address[1]
    blocker = threading.Event()

    class _SlowHandler(_QuantumStubHandler):
        def _reply(self):
            blocker.wait(10)  # 不返回，制造超时

    server.RequestHandlerClass = _SlowHandler
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("QUANTUM_AUTH_URL", f"http://127.0.0.1:{port}/verify")
    try:
        assert verify_token("forged-token") is None
    finally:
        blocker.set()
        server.shutdown()
        server.server_close()


def test_hmac_strict_mode_never_falls_back_to_stub(monkeypatch):
    """HMAC 严格模式（配置 ETHOS_AUTH_SECRET）：验签失败不回落 stub/远程。

    这条是既有正确行为，加锁防止后续被改坏。
    """
    monkeypatch.setenv("ETHOS_AUTH_SECRET", "integration-test-secret")
    monkeypatch.setenv("QUANTUM_AUTH_URL", "http://127.0.0.1:1/verify")
    # singleton 在 import 时创建（那时 ETHOS_AUTH_SECRET 为空 → StubVerifier），
    # 需换成带 HMAC verifier 的实例（auth 内部是 `from .security import security`）
    monkeypatch.setattr(security_mod, "security", SecurityService())
    assert verify_token("forged-token") is None
