"""Tatha 中央大脑 memory 意图（调度 agentmemory 记忆网关）测试。

搜索走 POST /agentmemory/search（经网关 :3210 透传到桥 :3220 调 mem::search）；
写入走 POST /agentmemory/remember（mem::remember）。
"""
from __future__ import annotations

from tatha.api.central_brain import (
    _call_memory_service,
    _parse_intent_rules,
    _remember_memory_service,
    dispatch,
)
from tatha.api.schemas import AskRequest


def test_rule_keyword_memory():
    assert _parse_intent_rules("回忆一下上次的项目方案") == "memory"
    assert _parse_intent_rules("我之前说过什么关于 x 的") == "memory"
    assert _parse_intent_rules("帮我记住这个方案") == "memory"


def test_dispatch_memory_ok(monkeypatch):
    import tatha.api.central_brain as cb

    def fake(text, limit=10):
        return {
            "format": "full",
            "results": [
                {"observation": {"id": "m1", "content": "记忆内容"}, "score": 12.3},
            ],
        }

    monkeypatch.setattr(cb, "_call_memory_service", fake)
    result = dispatch("memory", AskRequest(message="回忆一下 xxx"))
    assert result["status"] == "ok"
    # mem::search 的 results 每条是 {observation, score}，应解包出 observation
    assert result["memories"] == [{"id": "m1", "content": "记忆内容"}]
    assert result["query"] == "回忆一下 xxx"


def test_dispatch_memory_remember(monkeypatch):
    import tatha.api.central_brain as cb

    def fake_remember(content, memory_type="fact", importance=5):
        assert memory_type == "fact"
        assert importance == 5
        return {
            "memory": {"id": "mem_x", "content": content},
            "success": True,
        }

    monkeypatch.setattr(cb, "_remember_memory_service", fake_remember)
    result = dispatch("memory", AskRequest(message="记住这个方案：用 Postgres 存记忆"))
    assert result["status"] == "ok"
    assert result["remembered"] is True
    assert result["memory"]["id"] == "mem_x"


def test_dispatch_memory_empty():
    result = dispatch("memory", AskRequest(message=""))
    assert result["status"] == "pending"


def test_dispatch_memory_downstream_failure(monkeypatch):
    import tatha.api.central_brain as cb

    def fake(text, limit=10):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(cb, "_call_memory_service", fake)
    result = dispatch("memory", AskRequest(message="回忆一下 xxx"))
    assert result["status"] == "error"
    assert "gateway down" in result["error"]


def test_dispatch_memory_remember_failure(monkeypatch):
    import tatha.api.central_brain as cb

    def fake_remember(content, memory_type="fact", importance=5):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(cb, "_remember_memory_service", fake_remember)
    result = dispatch("memory", AskRequest(message="记住 xxx"))
    assert result["status"] == "error"
    assert result["message"] == "记忆写入失败"


def test_call_memory_service_stub_mode_no_token(monkeypatch):
    """stub 模式（未配置 ETHOS_AUTH_SECRET）不携带 Authorization 头；POST /agentmemory/search。"""
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"format": "full", "results": []}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResp()

    monkeypatch.setattr("httpx.Client", FakeClient)
    out = _call_memory_service("hello")
    assert out == {"format": "full", "results": []}
    assert captured["url"] == "http://127.0.0.1:3210/agentmemory/search"
    assert captured["json"] == {"query": "hello", "limit": 10}
    assert "Authorization" not in captured["headers"]


def test_remember_memory_service_stub_mode_no_token(monkeypatch):
    """写入走 POST /agentmemory/remember，body {content, type, importance}。"""
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"memory": {"id": "mem_x"}, "success": True}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResp()

    monkeypatch.setattr("httpx.Client", FakeClient)
    out = _remember_memory_service("记住 hello", memory_type="decision", importance=7)
    assert out["success"] is True
    assert captured["url"] == "http://127.0.0.1:3210/agentmemory/remember"
    assert captured["json"] == {
        "content": "记住 hello",
        "type": "decision",
        "importance": 7,
    }
    assert "Authorization" not in captured["headers"]
