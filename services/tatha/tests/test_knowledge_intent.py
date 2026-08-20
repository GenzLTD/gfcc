"""Tatha 中央大脑 knowledge 意图（调度 DemoPeter 知识库 RAG）测试。"""
from __future__ import annotations

from tatha.api.central_brain import _call_knowledge_service, _parse_intent_rules, dispatch
from tatha.api.schemas import AskRequest


def test_rule_keyword_knowledge():
    assert _parse_intent_rules("帮我查一下最近的资料") == "knowledge"
    assert _parse_intent_rules("搜索一下相关知识") == "knowledge"


def test_dispatch_knowledge_ok(monkeypatch):
    import tatha.api.central_brain as cb

    def fake(text, top_k=5, threshold=0.5):
        return {
            "query": text,
            "answer": "知识库答案",
            "sources": [{"title": "s1"}],
            "retrieval_mode": "hybrid",
            "chunk_count": 3,
            "response_time_ms": 42,
        }

    monkeypatch.setattr(cb, "_call_knowledge_service", fake)
    result = dispatch("knowledge", AskRequest(message="帮我查一下 x"))
    assert result["status"] == "ok"
    assert result["answer"] == "知识库答案"
    assert result["sources"] == [{"title": "s1"}]
    assert result["chunk_count"] == 3


def test_dispatch_knowledge_empty():
    result = dispatch("knowledge", AskRequest(message=""))
    assert result["status"] == "pending"


def test_dispatch_knowledge_downstream_failure(monkeypatch):
    import tatha.api.central_brain as cb

    def fake(text, top_k=5, threshold=0.5):
        raise RuntimeError("downstream down")

    monkeypatch.setattr(cb, "_call_knowledge_service", fake)
    result = dispatch("knowledge", AskRequest(message="帮我查一下 x"))
    assert result["status"] == "error"
    assert "downstream down" in result["error"]


def test_call_knowledge_service_stub_mode_no_token(monkeypatch):
    """stub 模式（未配置 ETHOS_AUTH_SECRET）不携带 Authorization 头。"""
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"answer": "x"}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json, headers):
            captured["url"] = url
            captured["payload"] = json
            captured["headers"] = headers
            return FakeResp()

    monkeypatch.setattr("httpx.Client", FakeClient)
    out = _call_knowledge_service("hello")
    assert out["answer"] == "x"
    assert captured["url"] == "http://127.0.0.1:5220/api/rag/query"
    assert captured["payload"] == {"query": "hello", "top_k": 5, "threshold": 0.5}
    assert "Authorization" not in captured["headers"]
