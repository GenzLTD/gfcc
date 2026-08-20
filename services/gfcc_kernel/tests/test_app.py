"""API 集成测试 —— POST /v1/ask 单入口 + GET /health。

使用 FastAPI TestClient 同步写法（绕开 pytest-asyncio 配置）。
CI 环境：无 ETHOS_AUTH_SECRET → ethos stub 验证模式（本地联调放行语义）。
"""

from fastapi.testclient import TestClient

from gfcc_kernel.app import app

client = TestClient(app)


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
