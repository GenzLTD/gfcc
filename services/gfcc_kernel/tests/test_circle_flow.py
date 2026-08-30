"""G6 圈/共识/地板落库测试。

独立临时库（CIRCLE_FLOW_DB → tmp_path，CIRCLE_FLOW_PROVIDER=sqlite），
不触碰开发者 data/circle_flow.db。验证施工单 §8：
- 重启恢复：新 adapter 同库 hydrate（圈/成员/地板/提案/acks）
- ack 达成 + 地板轮转同事务（决策②：库中不得出现 verified 而地板未动）
- dissolve 不删行；leave 删成员 + 地板交接同事务
- get 返回形状与今天一致（proposal 不暴露 verified_at 键）
"""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gfcc_kernel import circle_flow as cf
from gfcc_kernel.app import app as kernel_app
from gfcc_kernel.ports.circle import CircleAdapter
from gfcc_kernel.ports.consensus import ConsensusAdapter


def _b64(o: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(o).encode("utf-8")).rstrip(b"=").decode("ascii")


def _jwt(sub: str) -> str:
    header = _b64({"alg": "HS256", "typ": "JWT"})
    payload = _b64({"sub": sub, "tier": "pro", "iat": 0, "exp": 4102444800})
    return f"{header}.{payload}.sig"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


TOKEN_A = _jwt("tester-a")
TOKEN_B = _jwt("tester-b")


def _rows(db: Path, sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


@pytest.fixture()
def flow_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CIRCLE_FLOW_PROVIDER", "sqlite")
    monkeypatch.setenv("CIRCLE_FLOW_DB", str(tmp_path / "circle_flow.db"))
    monkeypatch.setattr(cf, "_store", None)
    yield cf
    monkeypatch.setattr(cf, "_store", None)


@pytest.fixture()
def store(flow_env):
    return flow_env.get_store()


@pytest.fixture()
def client(store, monkeypatch: pytest.MonkeyPatch):
    from gfcc_kernel.app import _registry

    # registry.get() 走 _ports[port]，属性与 _ports 都要替换，否则 HTTP 请求
    # 仍打到无 flow 的旧 adapter（不落库）
    circle_adapter = CircleAdapter(flow=store)
    consensus_adapter = ConsensusAdapter(threshold=85, flow=store)
    monkeypatch.setattr(_registry, "_circle", circle_adapter)
    monkeypatch.setattr(_registry, "_consensus", consensus_adapter)
    monkeypatch.setattr(
        _registry,
        "_ports",
        {**_registry._ports, "circle": circle_adapter, "consensus": consensus_adapter},
    )
    # raise_server_exceptions=False：同事务故障注入用例要拿到 500 响应而非抛异常
    with TestClient(kernel_app, raise_server_exceptions=False) as c:
        yield c


def _create_circle(client: TestClient, name: str = "围坐") -> str:
    r = client.post("/circle/api/create", json={"name": name}, headers=_auth(TOKEN_A))
    assert r.status_code == 200, r.text
    return r.json()["circle_id"]


# ---------------------------------------------------------------------- #
# 重启恢复（adapter 级：新实例同库 hydrate）
# ---------------------------------------------------------------------- #

def test_restart_recovers_circle(store) -> None:
    c1 = CircleAdapter(flow=store)
    r = c1.create("tester-a", "围坐")
    cid = r.data["circle_id"]
    c1.join(cid, "tester-b")

    c2 = CircleAdapter(flow=store)  # 模拟 restart
    g = c2.get(cid)
    assert g.ok
    assert [m["sub"] for m in g.data["circle"]["members"]] == ["tester-a", "tester-b"]
    assert g.data["circle"]["floor_sub"] == "tester-a"


def test_restart_recovers_proposal_and_acks(store) -> None:
    c1 = CircleAdapter(flow=store)
    cid = c1.create("tester-a", "围坐").data["circle_id"]
    c1.join(cid, "tester-b")
    k1 = ConsensusAdapter(threshold=85, flow=store)
    pid = k1.propose(cid, "验收内存隔离", ["tester-a", "tester-b"], "tester-a").data["proposal_id"]
    k1.score(pid, 90, [{"by_sub": "tester-a", "basis": "已本地验证", "at": "2026-08-28T00:00:00"}])
    k1.acknowledge(pid, "tester-a")  # 非 verified → append_ack 落库

    k2 = ConsensusAdapter(threshold=85, flow=store)  # 模拟 restart
    s = k2.get_status(pid)
    assert s.ok
    assert s.data["proposal"]["status"] == "awaiting_ack"
    assert [a["sub"] for a in s.data["proposal"]["acks"]] == ["tester-a"]
    assert "verified_at" not in s.data["proposal"]  # 形状与今天一致


# ---------------------------------------------------------------------- #
# HTTP 全链路：verified + 地板轮转落库 / 同事务 / 恢复
# ---------------------------------------------------------------------- #

def test_http_verified_persists_and_floor_advances(client, store, flow_env) -> None:
    cid = _create_circle(client)
    client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))

    r = client.post(
        "/circle/api/propose",
        json={"circle_id": cid, "subject": "开发调试由 Jason 承担", "basis": "团队内唯一开发"},
        headers=_auth(TOKEN_A),
    )
    pid = r.json()["proposal_id"]
    client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_A))
    r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_B))
    assert r.json()["proposal"]["status"] == "consensus_verified"
    assert r.json()["floor_sub"] == "tester-b"

    db = flow_env._db_path()
    props = _rows(db, "SELECT * FROM proposals")
    assert len(props) == 1
    assert props[0]["status"] == "consensus_verified"
    assert props[0]["verified_at"]
    assert _rows(db, "SELECT sub FROM proposal_acks ORDER BY rowid") == [
        {"sub": "tester-a"},
        {"sub": "tester-b"},
    ]
    circles = _rows(db, "SELECT floor_sub FROM circles WHERE id = ?", (cid,))
    assert circles[0]["floor_sub"] == "tester-b"

    # 重启恢复：同一库新 adapter
    c2 = CircleAdapter(flow=store)
    k2 = ConsensusAdapter(threshold=85, flow=store)
    assert c2.get(cid).data["circle"]["floor_sub"] == "tester-b"
    s = k2.get_status(pid)
    assert s.data["proposal"]["status"] == "consensus_verified"
    assert len(s.data["proposal"]["acks"]) == 2
    assert "verified_at" not in s.data["proposal"]


def test_verified_and_floor_same_transaction(client, store, flow_env, monkeypatch) -> None:
    """决策②：verify_and_advance_floor 失败 → 库中不得出现 verified 而地板未动。"""
    cid = _create_circle(client)
    client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
    r = client.post(
        "/circle/api/propose",
        json={"circle_id": cid, "subject": "同事务验证", "basis": "故障注入"},
        headers=_auth(TOKEN_A),
    )
    pid = r.json()["proposal_id"]
    client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_A))

    def _boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(store, "verify_and_advance_floor", _boom)
    r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_B))
    assert r.status_code == 500

    db = flow_env._db_path()
    assert _rows(db, "SELECT status FROM proposals WHERE id = ?", (pid,))[0]["status"] == "awaiting_ack"
    assert _rows(db, "SELECT floor_sub FROM circles WHERE id = ?", (cid,))[0]["floor_sub"] == "tester-a"
    assert _rows(db, "SELECT sub FROM proposal_acks ORDER BY rowid") == [{"sub": "tester-a"}]


# ---------------------------------------------------------------------- #
# dissolve / leave 语义
# ---------------------------------------------------------------------- #

def test_dissolve_keeps_row(store, flow_env) -> None:
    c1 = CircleAdapter(flow=store)
    cid = c1.create("tester-a", "围坐").data["circle_id"]
    assert c1.dissolve(cid, "tester-a").ok

    db = flow_env._db_path()
    row = _rows(db, "SELECT status, dissolved_at FROM circles WHERE id = ?", (cid,))
    assert row[0]["status"] == "dissolved"
    assert row[0]["dissolved_at"]

    c2 = CircleAdapter(flow=store)  # 模拟 restart：历史不丢
    g = c2.get(cid)
    assert g.ok and g.data["circle"]["status"] == "dissolved"


def test_leave_removes_member_and_floor_tx(client, store, flow_env) -> None:
    cid = _create_circle(client)
    client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
    r = client.post("/circle/api/leave", json={"circle_id": cid}, headers=_auth(TOKEN_A))
    assert r.status_code == 200

    db = flow_env._db_path()
    members = _rows(db, "SELECT sub FROM circle_members WHERE circle_id = ?", (cid,))
    assert [m["sub"] for m in members] == ["tester-b"]
    assert _rows(db, "SELECT floor_sub FROM circles WHERE id = ?", (cid,))[0]["floor_sub"] == "tester-b"


def test_reject_persists(client, store, flow_env) -> None:
    cid = _create_circle(client)
    client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
    r = client.post(
        "/circle/api/propose",
        json={"circle_id": cid, "subject": "可落库异议", "basis": "x"},
        headers=_auth(TOKEN_A),
    )
    pid = r.json()["proposal_id"]
    r = client.post(
        "/circle/api/reject",
        json={"circle_id": cid, "proposal_id": pid, "reason": "库里要留下理由"},
        headers=_auth(TOKEN_B),
    )
    assert r.status_code == 200, r.text
    db = flow_env._db_path()
    row = _rows(
        db,
        "SELECT status, rejected_by, reject_reason, rejected_at FROM proposals WHERE id = ?",
        (pid,),
    )[0]
    assert row["status"] == "rejected"
    assert row["rejected_by"] == "tester-b"
    assert row["reject_reason"] == "库里要留下理由"
    assert row["rejected_at"]

    k2 = ConsensusAdapter(threshold=85, flow=store)
    st = k2.get_status(pid)
    assert st.ok
    assert st.data["proposal"]["status"] == "rejected"
    assert st.data["proposal"]["reject_reason"] == "库里要留下理由"


def test_withdraw_persists(client, store, flow_env) -> None:
    cid = _create_circle(client)
    client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
    r = client.post(
        "/circle/api/propose",
        json={"circle_id": cid, "subject": "可落库撤回", "basis": "x"},
        headers=_auth(TOKEN_A),
    )
    pid = r.json()["proposal_id"]
    r = client.post(
        "/circle/api/withdraw",
        json={"circle_id": cid, "proposal_id": pid},
        headers=_auth(TOKEN_A),
    )
    assert r.status_code == 200, r.text
    db = flow_env._db_path()
    row = _rows(
        db,
        "SELECT status, withdrawn_by, withdrawn_at FROM proposals WHERE id = ?",
        (pid,),
    )[0]
    assert row["status"] == "withdrawn"
    assert row["withdrawn_by"] == "tester-a"
    assert row["withdrawn_at"]

    k2 = ConsensusAdapter(threshold=85, flow=store)
    st = k2.get_status(pid)
    assert st.ok and st.data["proposal"]["status"] == "withdrawn"


def test_stale_expiry_on_propose_path(client, store, flow_env) -> None:
    """不先开 status，直接 propose 也要先清僵尸 awaiting_ack。"""
    from gfcc_kernel.app import _registry

    cid = _create_circle(client)
    client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
    r = client.post(
        "/circle/api/propose",
        json={"circle_id": cid, "subject": "隔夜僵尸", "basis": "x"},
        headers=_auth(TOKEN_A),
    )
    assert r.status_code == 200, r.text
    pid = r.json()["proposal_id"]
    _registry.get("consensus")._proposals[pid]["created_at"] = "2000-01-01T00:00:00"
    store.update_proposal(pid, created_at="2000-01-01T00:00:00")
    r2 = client.post(
        "/circle/api/propose",
        json={"circle_id": cid, "subject": "清完再提", "basis": "y"},
        headers=_auth(TOKEN_A),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["proposal"]["status"] == "awaiting_ack"
    db = flow_env._db_path()
    assert _rows(db, "SELECT status FROM proposals WHERE id = ?", (pid,))[0]["status"] == "expired"


def test_stale_expiry_on_status_path(client, store) -> None:
    from gfcc_kernel.app import _registry

    cid = _create_circle(client)
    client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
    r = client.post(
        "/circle/api/propose",
        json={"circle_id": cid, "subject": "status 路径作废", "basis": "x"},
        headers=_auth(TOKEN_A),
    )
    pid = r.json()["proposal_id"]
    _registry.get("consensus")._proposals[pid]["created_at"] = "2000-01-01T00:00:00"
    store.update_proposal(pid, created_at="2000-01-01T00:00:00")
    r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_A))
    assert r.status_code == 200, r.text
    found = [p for p in r.json()["proposals"] if p["id"] == pid]
    assert found and found[0]["status"] == "expired"


def test_dissolve_persists(client, store, flow_env) -> None:
    cid = _create_circle(client)
    r = client.post("/circle/api/dissolve", json={"circle_id": cid}, headers=_auth(TOKEN_A))
    assert r.status_code == 200, r.text
    db = flow_env._db_path()
    row = _rows(db, "SELECT status, dissolved_at FROM circles WHERE id = ?", (cid,))[0]
    assert row["status"] == "dissolved"
    assert row["dissolved_at"]
    c2 = CircleAdapter(flow=store)
    g = c2.get(cid)
    assert g.ok and g.data["circle"]["status"] == "dissolved"
