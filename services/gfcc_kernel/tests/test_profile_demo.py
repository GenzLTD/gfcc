"""L3 profile.demo 注册落地测试：厂商适配器 + 装配 + app 集成。

真源：modes/profile.demo.yaml + contracts/registry.v1.json。
默认模式（gfcc.default）下厂商适配器一律禁用（FORBIDDEN_IN_DEFAULT_TOOLS），
本文件单测层不依赖远端服务（monkeypatch _post / is_available）。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from gfcc_kernel import app as app_module
from gfcc_kernel.adapters import bind_profile_demo
from gfcc_kernel.adapters.agentmemory_store import AgentMemoryIIIStore
from gfcc_kernel.adapters.demopeter_knowledge import DemoPeterKnowledge
from gfcc_kernel.registry import PortRegistry

_DEFAULT_CLIENT = TestClient(app_module.app)


def _make_record(library="goals", actor_sub="sub-a", body="坚持围坐", circle_id=None):
    return {
        "id": uuid.uuid4().hex,
        "library": library,
        "actor_sub": actor_sub,
        "body": body,
        "observed_at": "2026-08-31T12:00:00",
        "record_type": "goal",
        "circle_id": circle_id,
    }


# --------------------------------------------------------------------------- #
# AgentMemoryIIIStore（store 槽适配器）
# --------------------------------------------------------------------------- #

def test_store_put_remembers_remote(monkeypatch):
    store = AgentMemoryIIIStore(gateway_url="http://mem.test:3210")
    calls = []
    monkeypatch.setattr(store, "is_available", lambda: True)
    monkeypatch.setattr(store, "_post",
                        lambda path, payload: (calls.append((path, payload)) or {"ok": True}))
    rec = store.put(_make_record())
    assert store.count() == 1
    assert calls and calls[0][0] == "/agentmemory/remember"
    assert calls[0][1]["text"] == "坚持围坐"
    assert calls[0][1]["user"] == "sub-a"
    assert calls[0][1]["tags"] == ["goals"]


def test_store_gateway_down_degrades_to_stub(monkeypatch):
    """网关不可达 → 降级纯 stub：不抛、不调远程、本地影子可读（契约允许空数据合法）。"""
    store = AgentMemoryIIIStore(gateway_url="http://mem.test:3210")
    monkeypatch.setattr(store, "is_available", lambda: False)

    def boom(path, payload):
        raise AssertionError("remote must not be called when gateway down")

    monkeypatch.setattr(store, "_post", boom)
    rec = store.put(_make_record())
    assert store.count() == 1
    assert store.get(rec["id"], actor_sub="sub-a") is not None


def test_store_visibility_contract_kept(monkeypatch):
    """可见性强制不变：无 actor_sub/circle_id 拒绝；跨人读返回 None。"""
    store = AgentMemoryIIIStore(gateway_url="http://mem.test:3210")
    monkeypatch.setattr(store, "is_available", lambda: False)
    rec = store.put(_make_record(actor_sub="sub-a"))
    with pytest.raises(ValueError):
        store.get(rec["id"])
    assert store.get(rec["id"], actor_sub="sub-b") is None
    assert store.get(rec["id"], actor_sub="sub-a") is not None


def test_store_supersede_ai_forbidden(monkeypatch):
    """契约红线：observed_by=ai 不得静默改写（继承自 StubStore）。"""
    store = AgentMemoryIIIStore(gateway_url="http://mem.test:3210")
    monkeypatch.setattr(store, "is_available", lambda: False)
    rec = store.put(_make_record())
    with pytest.raises(ValueError):
        store.supersede(rec["id"], {"body": "x"}, "sub-a", observed_by="ai")


# --------------------------------------------------------------------------- #
# DemoPeterKnowledge（knowledge.demopeter 工具适配器）
# --------------------------------------------------------------------------- #

def test_knowledge_query_ok(monkeypatch):
    k = DemoPeterKnowledge(base_url="http://demo.test:5220")
    monkeypatch.setattr(k, "_post", lambda path, payload: {
        "query": payload["query"],
        "answer": "RAG 答案",
        "sources": [{"doc": "a"}],
        "response_time_ms": 12,
        "chunk_count": 1,
        "retrieval_mode": "semantic",
    })
    r = k.query("如何围坐")
    assert r.ok
    assert r.data["answer"] == "RAG 答案"
    assert r.data["sources"][0]["doc"] == "a"
    assert r.data["retrieval_mode"] == "semantic"


def test_knowledge_query_remote_error(monkeypatch):
    k = DemoPeterKnowledge(base_url="http://demo.test:5220")

    def boom(path, payload):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(k, "_post", boom)
    r = k.query("如何围坐")
    assert not r.ok
    assert "unreachable" in (r.error or "")


def test_knowledge_query_empty_question():
    k = DemoPeterKnowledge(base_url="http://demo.test:5220")
    r = k.query("   ")
    assert not r.ok
    assert "required" in (r.error or "")


# --------------------------------------------------------------------------- #
# bind_profile_demo 装配（dispatch 不 import 实现，只经 registry 绑定）
# --------------------------------------------------------------------------- #

def test_bind_profile_demo_assembles():
    reg = PortRegistry()
    am = bind_profile_demo(reg, gateway_url="http://mem.test:3210",
                           demopeter_url="http://demo.test:5220")
    assert isinstance(reg.get("memory")._store, AgentMemoryIIIStore)
    assert reg._store is am  # store 槽引用同步（signal-ingest 用同一 store）
    assert reg.list_tools() == ["knowledge.demopeter"]
    assert isinstance(reg.get_tool("knowledge.demopeter"), DemoPeterKnowledge)
    # 一等端口仍为五端口，tools_extra 不增长 intent 表
    assert reg.list_ports() == ["circle", "identity", "memory", "consensus", "contribution"]


def test_default_registry_has_no_tools():
    reg = PortRegistry()
    assert reg.list_tools() == []
    assert reg.get_tool("knowledge.demopeter") is None
    assert not isinstance(reg.get("memory")._store, AgentMemoryIIIStore)


# --------------------------------------------------------------------------- #
# app 集成（/health + /v1/knowledge/query）
# --------------------------------------------------------------------------- #

def test_health_default_mode():
    data = _DEFAULT_CLIENT.get("/health").json()
    assert data["mode"] == "gfcc.default"
    assert data["tools_extra"] == []


def test_knowledge_query_404_when_not_registered():
    r = _DEFAULT_CLIENT.post("/v1/knowledge/query", json={"question": "hi"})
    assert r.status_code == 404


def test_knowledge_query_and_health_in_profile_demo(monkeypatch):
    reg = PortRegistry()
    am = bind_profile_demo(reg, gateway_url="http://mem.test:3210",
                           demopeter_url="http://demo.test:5220")
    tool = reg.get_tool("knowledge.demopeter")
    monkeypatch.setattr(tool, "_post", lambda path, payload: {
        "query": payload["query"],
        "answer": "组合后的答案",
        "sources": [],
        "chunk_count": 0,
    })
    monkeypatch.setattr(app_module, "_registry", reg)
    monkeypatch.setattr(app_module, "_store", am)
    monkeypatch.setattr(app_module, "_store_provider", "agentmemory_iii")
    monkeypatch.setattr(app_module, "_mode", "profile.demo")

    client = TestClient(app_module.app)
    r = client.post("/v1/knowledge/query",
                    json={"question": "gfcc 与本地组件如何结合", "top_k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "组合后的答案"
    assert body["query"] == "gfcc 与本地组件如何结合"

    h = client.get("/health").json()
    assert h["mode"] == "profile.demo"
    assert h["store"] == "agentmemory_iii"
    assert h["tools_extra"] == ["knowledge.demopeter"]
