"""API 集成测试 —— POST /v1/ask 单入口 + GET /health。

使用 FastAPI TestClient 同步写法（绕开 pytest-asyncio 配置）。
CI 环境：无 ETHOS_AUTH_SECRET → ethos stub 验证模式（本地联调放行语义）。
stub 模式下 StubVerifier 会解析「恰好是 JWT」的 token 的 sub（不验签），
因此可签两个不同 sub 的假 token 做 Step1 按人隔离端到端验收。
"""

from fastapi.testclient import TestClient

from ethos.security._jwt import encode_token
from gfcc_kernel.app import app

client = TestClient(app)


def _jwt(sub: str) -> str:
    """stub 模式假 token：不验签，仅让 StubVerifier 解析出 sub。"""
    return encode_token({"alg": "HS256", "typ": "JWT"}, {"sub": sub}, b"x")


class TestHealth:
    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["service"] == "gfcc_kernel"
        assert data["version"] == "1.1.0"
        assert data["mode"] == "gfcc.default"
        assert set(data["ports"]) == {"circle", "identity", "memory", "consensus", "contribution"}


class TestV1Ask:
    def test_chitchat_unknown(self):
        r = client.post("/v1/ask", json={"message": "你好"})
        assert r.status_code == 200
        data = r.json()
        assert data["port"] == "unknown"
        assert data["status"] == "unknown"

    def test_memory_write(self):
        r = client.post("/v1/ask", json={
            "message": "记住明天社区例会",
            "context": {"port_hint": "memory", "session_id": "s-api"},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["port"] == "memory"
        assert data["status"] == "ok"
        assert data["result"]["receipts"][0]["id"]  # 写操作有 id

    def test_extra_field_422(self):
        r = client.post("/v1/ask", json={"message": "hi", "backend": "tatha"})
        assert r.status_code == 422  # additionalProperties=false

    def test_empty_message_422(self):
        r = client.post("/v1/ask", json={"message": ""})
        assert r.status_code == 422

    def test_dialog_mode_coach(self):
        r = client.post("/v1/ask", json={
            "message": "记住每天复盘",
            "context": {"port_hint": "memory", "dialog_mode": "coach"},
        })
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestStep1ActorIsolation:
    """Step1 验收核心：每人一个 sub，记忆体按人隔离（A 记住 → B 问不到）。"""

    _AUTH = {"Authorization": "Bearer "}

    def test_a_remembers_b_cannot_recall(self):
        # A 记住一条专属事项
        r = client.post("/v1/ask", json={
            "message": "记住下周去体检",
            "context": {"port_hint": "memory", "session_id": "iso-a"},
        }, headers={"Authorization": "Bearer " + _jwt("tester-a")})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["result"]["receipts"][0]["id"]

        # B 用同一句问 → 0 条（Step1 验收：B 问不到 A 的记忆）
        r = client.post("/v1/ask", json={
            "message": "回忆下周去体检",
            "context": {"port_hint": "memory", "session_id": "iso-b"},
        }, headers={"Authorization": "Bearer " + _jwt("tester-b")})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["result"]["receipts"][0]["id"] is None  # 无命中
        assert any("no records" in s for s in data["suggestions"])

        # A 自己能问到
        r = client.post("/v1/ask", json={
            "message": "回忆下周去体检",
            "context": {"port_hint": "memory", "session_id": "iso-a"},
        }, headers={"Authorization": "Bearer " + _jwt("tester-a")})
        data = r.json()
        assert data["status"] == "ok"
        assert any("record(s) found" in s for s in data["suggestions"])

    def test_no_token_still_ok_in_stub(self):
        # stub 模式（CI 无 secret）：无 token 放行（本地联调语义）
        r = client.post("/v1/ask", json={
            "message": "记住一条",
            "context": {"port_hint": "memory", "session_id": "iso-anon"},
        })
        assert r.status_code == 200
