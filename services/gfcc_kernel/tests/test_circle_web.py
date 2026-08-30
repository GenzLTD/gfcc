"""围坐会场 web 面测试（/circle/ + /circle/api/*）。

stub 模式（conftest 强制）下：Bearer 任意 token 按 payload.sub 解析身份，
不验签——测试里直接构造不同 sub 的假 JWT 区分 A/B/C。
HS256 严格分支由 monkeypatch 单独覆盖（401）。
"""

from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from gfcc_kernel.app import app as kernel_app


def _b64(o: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(o).encode("utf-8")).rstrip(b"=").decode("ascii")


def _jwt(sub: str) -> str:
    """假 JWT：stub 模式只解析 payload.sub，不验签。"""
    header = _b64({"alg": "HS256", "typ": "JWT"})
    payload = _b64({"sub": sub, "tier": "pro", "iat": 0, "exp": 4102444800})
    return f"{header}.{payload}.ZmFrZXNpZw"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


TOKEN_A = _jwt("tester-a")
TOKEN_B = _jwt("tester-b")
TOKEN_C = _jwt("tester-c")


def test_page_served() -> None:
    with TestClient(kernel_app) as client:
        r = client.get("/circle/")
        assert r.status_code == 200
        assert "围坐会场" in r.text
        assert "/circle/api/me" in r.text


def test_me_returns_sub() -> None:
    with TestClient(kernel_app) as client:
        r = client.get("/circle/api/me", headers=_auth(TOKEN_A))
        assert r.status_code == 200
        assert r.json()["sub"] == "tester-a"


def test_unauthorized_strict_mode(monkeypatch) -> None:
    """HS256 严格模式：无效 token → 401（复用 _verify_request 语义）。"""

    class _BadCtx:
        error = "invalid signature"
        principal = None

    monkeypatch.setattr("gfcc_kernel.app._security.verify", lambda token: _BadCtx())
    with TestClient(kernel_app) as client:
        r = client.get("/circle/api/me", headers=_auth("bad.token.here"))
        assert r.status_code == 401
        assert "unauthorized" in r.json()["detail"]


def _create_circle(client: TestClient, name: str = "围坐") -> str:
    r = client.post("/circle/api/create", json={"name": name}, headers=_auth(TOKEN_A))
    assert r.status_code == 200, r.text
    return r.json()["circle_id"]


def test_full_flow_consensus_verified() -> None:
    """A 建圈 → B 入座 → A 写拍板句 → A/B 各自确认 → consensus_verified。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)

        # B 入座
        r = client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        assert r.status_code == 200
        assert len(r.json()["members"]) == 2

        # A 写拍板句（propose+score 一步到位 → awaiting_ack）
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "本周完成内存隔离验收", "basis": "Step1 已本地验证"},
            headers=_auth(TOKEN_A),
        )
        assert r.status_code == 200, r.text
        pid = r.json()["proposal_id"]
        assert r.json()["proposal"]["status"] == "awaiting_ack"
        assert set(r.json()["proposal"]["parties"]) == {"tester-a", "tester-b"}

        # A 本人点确认
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_A))
        assert r.status_code == 200
        assert r.json()["can_complete"] is False

        # B 本人点确认 → 全票 → verified
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_B))
        assert r.status_code == 200
        assert r.json()["can_complete"] is True
        assert r.json()["proposal"]["status"] == "consensus_verified"

        # 状态可见
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_A))
        assert r.status_code == 200
        body = r.json()
        assert body["circle"]["status"] == "active"
        assert len(body["proposals"]) == 1
        assert body["proposals"][0]["status"] == "consensus_verified"


def test_join_unknown_circle_rejected() -> None:
    with TestClient(kernel_app) as client:
        r = client.post(
            "/circle/api/join",
            json={"circle_id": "no-such-circle"},
            headers=_auth(TOKEN_B),
        )
        assert r.status_code == 400
        assert "not found" in r.json()["detail"]


def test_duplicate_join_is_idempotent() -> None:
    """重复入座幂等：已入座再 join 返回 200，成员不重复（配合 leave 后重进）。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        r1 = client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        assert r1.status_code == 200
        assert len(r1.json()["members"]) == 2
        r2 = client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        assert r2.status_code == 200
        assert len(r2.json()["members"]) == 2


def test_propose_needs_two_seated() -> None:
    """只有 A 一人时不能写拍板句（parties ≥ 2）。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "只有我一个人"},
            headers=_auth(TOKEN_A),
        )
        assert r.status_code == 400
        assert "at least 2" in r.json()["detail"]


def test_propose_requires_member() -> None:
    """未入座的 C 不能写拍板句。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "C 乱写"},
            headers=_auth(TOKEN_C),
        )
        assert r.status_code == 403
        assert "only seated members may propose" in r.json()["detail"]


def test_not_your_floor() -> None:
    """地板在 A 手上时，B 已入座也不能写拍板句（403 not your floor）。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "B 抢着写"},
            headers=_auth(TOKEN_B),
        )
        assert r.status_code == 403
        assert "not your floor" in r.json()["detail"]


def test_can_continue_propose_after_organizer_leave() -> None:
    """回归：轮询制下组织者离场后，圈内仍能继续拍板，不必重建圈。

    原真实场景：A（organizer）拍板一条后 leave，圈里只剩 B/C，修复前 403。
    轮询制：A 第一条达成后地板已交给 B，A 离场不影响 B 继续下一条分工。
    """
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))

        # A 拍板第一条并双方确认（开发调试由 Jason 承担）→ 地板交给 B
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "开发调试由 Jason 承担"},
            headers=_auth(TOKEN_A),
        )
        pid = r.json()["proposal_id"]
        client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_A))
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_B))
        assert r.json()["proposal"]["status"] == "consensus_verified"
        assert r.json()["floor_sub"] == "tester-b"

        # C 入座，A（organizer）离场 → 圈里只剩 B/C；地板已不在 A 手上
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        r = client.post("/circle/api/leave", json={"circle_id": cid}, headers=_auth(TOKEN_A))
        assert r.status_code == 200
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_B))
        assert r.json()["floor_sub"] == "tester-b"

        # B（当前地板）继续提交下一条分工
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "业务运维由 B 承担"},
            headers=_auth(TOKEN_B),
        )
        assert r.status_code == 200, r.text
        pid2 = r.json()["proposal_id"]
        assert set(r.json()["proposal"]["parties"]) == {"tester-b", "tester-c"}

        # 两人各自确认 → 第二条也达成 → 地板交给 C
        client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid2}, headers=_auth(TOKEN_B))
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid2}, headers=_auth(TOKEN_C))
        assert r.json()["proposal"]["status"] == "consensus_verified"
        assert r.json()["floor_sub"] == "tester-c"

        # 同圈内两条共识都落账，无需新建圈
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_B))
        body = r.json()
        assert len(body["proposals"]) == 2
        assert all(p["status"] == "consensus_verified" for p in body["proposals"])


def test_ack_not_party_rejected() -> None:
    """旁观者 C 在 propose 后才入座 → 不在 parties，确认被拒（先只看）。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "AB 拍板"},
            headers=_auth(TOKEN_A),
        )
        pid = r.json()["proposal_id"]

        # C 旁观：能看状态，但不能 ack
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_C))
        assert r.status_code == 200
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_C))
        assert r.status_code == 400
        assert "not a party" in r.json()["detail"]


def test_proposal_must_belong_to_circle() -> None:
    """ack 时 proposal 必须属于该圈。"""
    with TestClient(kernel_app) as client:
        cid_a = _create_circle(client, "圈A")
        cid_b = _create_circle(client, "圈B")
        client.post("/circle/api/join", json={"circle_id": cid_a}, headers=_auth(TOKEN_B))
        client.post("/circle/api/join", json={"circle_id": cid_b}, headers=_auth(TOKEN_B))
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid_a, "subject": "圈A的拍板句"},
            headers=_auth(TOKEN_A),
        )
        pid = r.json()["proposal_id"]
        r = client.post("/circle/api/ack", json={"circle_id": cid_b, "proposal_id": pid}, headers=_auth(TOKEN_A))
        assert r.status_code == 400
        assert "not in this circle" in r.json()["detail"]


def test_status_unknown_circle_404() -> None:
    with TestClient(kernel_app) as client:
        r = client.get("/circle/api/status?circle_id=nope", headers=_auth(TOKEN_A))
        assert r.status_code == 404


# ---------- 发言权轮询（施工单 §8） ----------


def test_floor_initially_organizer() -> None:
    """§8 #1 建圈者先持地板；单人圈下一位预览仍是自己。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_A))
        body = r.json()
        assert body["floor_sub"] == "tester-a"
        assert body["floor_next_sub"] == "tester-a"


def test_floor_advances_to_b_after_verified() -> None:
    """§8 #3 两人圈 A 达成一条后，地板交给 B。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "A 拍第一条"},
            headers=_auth(TOKEN_A),
        )
        pid = r.json()["proposal_id"]
        client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_A))
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_B))
        assert r.json()["proposal"]["status"] == "consensus_verified"
        assert r.json()["floor_sub"] == "tester-b"
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_B))
        body = r.json()
        assert body["floor_sub"] == "tester-b"
        assert body["floor_next_sub"] == "tester-a"


def test_floor_cycles_two_person() -> None:
    """§8 #4 两人圈 A→B→A：B 达成后地板回到 A。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        # A 第一条 → 地板给 B
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "第一条"},
            headers=_auth(TOKEN_A),
        )
        pid = r.json()["proposal_id"]
        client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_A))
        client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_B))
        # B 第二条 → 地板回 A
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "第二条"},
            headers=_auth(TOKEN_B),
        )
        assert r.status_code == 200, r.text
        pid = r.json()["proposal_id"]
        client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_B))
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_A))
        assert r.json()["proposal"]["status"] == "consensus_verified"
        assert r.json()["floor_sub"] == "tester-a"


def test_floor_cycles_three_person() -> None:
    """§8 #5 三人圈 A→B→C→A 闭环。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        seq = [("tester-a", TOKEN_A), ("tester-b", TOKEN_B), ("tester-c", TOKEN_C)]
        for sub, token in seq:
            r = client.post(
                "/circle/api/propose",
                json={"circle_id": cid, "subject": f"{sub} 轮到的议题"},
                headers=_auth(token),
            )
            assert r.status_code == 200, f"{sub} propose -> {r.status_code} {r.text}"
            pid = r.json()["proposal_id"]
            for _, t2 in [("tester-a", TOKEN_A), ("tester-b", TOKEN_B), ("tester-c", TOKEN_C)]:
                client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(t2))
            r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_A))
            assert r.json()["proposals"][-1]["status"] == "consensus_verified"
        # 三轮后地板回到 A（三人轮询闭环 A→B→C→A）
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_A))
        assert r.json()["floor_sub"] == "tester-a"


def test_pending_blocks_floor_holder() -> None:
    """§8 #6 一次一条：pending 时地板持有者再提也被拒（后端闸，不只藏按钮）。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "第一条"},
            headers=_auth(TOKEN_A),
        )
        assert r.status_code == 200
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "第二条"},
            headers=_auth(TOKEN_A),
        )
        assert r.status_code == 400
        assert "pending proposal exists" in r.json()["detail"]


def test_leave_transfers_floor() -> None:
    """§8 #7 地板持有者离场（无 pending）→ 地板交给剩余下一位。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        # A 是地板，直接离场 → 地板交给 B（剩余成员第一位）
        r = client.post("/circle/api/leave", json={"circle_id": cid}, headers=_auth(TOKEN_A))
        assert r.status_code == 200
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_B))
        body = r.json()
        assert len(body["circle"]["members"]) == 2
        assert body["floor_sub"] == "tester-b"
        # B 持地板可正常拍板
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "B 续拍"},
            headers=_auth(TOKEN_B),
        )
        assert r.status_code == 200, r.text


def test_proposer_leave_no_double_advance() -> None:
    """§8 #8 提议人中途 leave：地板已在 leave 时交接，达成后不再多跳一格。

    三人圈：A 提议并自己确认后离场 → 地板交 B；B/C 补 ack 达成。
    若达成时误把地板从 B 再进一位到 C（double advance），测试拦下。
    """
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        # A（地板）提议并自己先确认
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "A 的议题"},
            headers=_auth(TOKEN_A),
        )
        pid = r.json()["proposal_id"]
        client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_A))
        # A 中途离场 → 地板交给 B
        r = client.post("/circle/api/leave", json={"circle_id": cid}, headers=_auth(TOKEN_A))
        assert r.status_code == 200
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_B))
        assert r.json()["floor_sub"] == "tester-b"
        # 其余 party 补 ack → 达成；达成时不做 advance（地板已在 leave 时交给 B），
        # 地板保持 B 不跳 C——ack 响应 floor_sub 为 None，用 status 断言
        client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_B))
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_C))
        assert r.json()["proposal"]["status"] == "consensus_verified"
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_B))
        assert r.json()["floor_sub"] == "tester-b"


# ---------- 旁观在场可见（施工单「旁观在场可见实施」§0–§9） ----------


def test_observe_registers_and_visible_to_all() -> None:
    """决策⑩：C observe 后，A 与 B 的 status 都含 C；C 不进 members/parties。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))

        r = client.post("/circle/api/observe", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        assert r.status_code == 200, r.text
        assert [w["sub"] for w in r.json()["watchers"]] == ["tester-c"]

        # A 与 B 看到同一份旁观名单（验收硬点：不能只验 jason）
        for tok in (TOKEN_A, TOKEN_B):
            r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(tok))
            assert r.status_code == 200
            body = r.json()
            assert [w["sub"] for w in body["watchers"]] == ["tester-c"]
            assert all(m["sub"] != "tester-c" for m in body["circle"]["members"])


def test_observe_repeat_idempotent() -> None:
    """决策⑧：重复 observe 幂等 200，名单不重复。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        r1 = client.post("/circle/api/observe", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        r2 = client.post("/circle/api/observe", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        assert r1.status_code == 200
        assert r2.status_code == 200
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_A))
        assert [w["sub"] for w in r.json()["watchers"]] == ["tester-c"]


def test_observe_seated_member_rejected() -> None:
    """决策④：已入座再旁观 → 400（避免一人同时在两套名单）。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        r = client.post("/circle/api/observe", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        assert r.status_code == 400
        assert "already seated" in r.json()["detail"]


def test_observe_unknown_circle_rejected() -> None:
    """未知圈 observe → 400（对齐 join）。"""
    with TestClient(kernel_app) as client:
        r = client.post("/circle/api/observe", json={"circle_id": "no-such-circle"}, headers=_auth(TOKEN_C))
        assert r.status_code == 400
        assert "not found" in r.json()["detail"]


def test_observer_cannot_ack_or_propose() -> None:
    """§0 一句话：旁观可看 status，但不能 ack（not a party）、不能 propose（403）。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        client.post("/circle/api/observe", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "C 乱写"},
            headers=_auth(TOKEN_C),
        )
        assert r.status_code == 403
        assert "seated members" in r.json()["detail"]
        # 拍板句 parties 仍是入座成员，C 不在其中
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "AB 拍板"},
            headers=_auth(TOKEN_A),
        )
        pid = r.json()["proposal_id"]
        assert set(r.json()["proposal"]["parties"]) == {"tester-a", "tester-b"}
        r = client.post("/circle/api/ack", json={"circle_id": cid, "proposal_id": pid}, headers=_auth(TOKEN_C))
        assert r.status_code == 400
        assert "not a party" in r.json()["detail"]


def test_join_drops_watcher() -> None:
    """决策⑤：旁观后再入座 → watchers 消失、进入 members。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/observe", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_A))
        assert [w["sub"] for w in r.json()["watchers"]] == ["tester-c"]

        r = client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        assert r.status_code == 200
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_A))
        body = r.json()
        assert body["watchers"] == []
        assert [m["sub"] for m in body["circle"]["members"]] == ["tester-a", "tester-c"]


def test_unobserve_removes_from_all() -> None:
    """决策⑥：unobserve 后 A/B 的 status 都看不到 C。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/observe", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        r = client.post("/circle/api/unobserve", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        assert r.status_code == 200
        assert r.json()["watchers"] == []
        for tok in (TOKEN_A, TOKEN_B):
            r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(tok))
            assert r.json()["watchers"] == []


def test_unobserve_not_observer_rejected() -> None:
    """未旁观就 unobserve → 400。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        r = client.post("/circle/api/unobserve", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        assert r.status_code == 400
        assert "not an observer" in r.json()["detail"]


def test_leave_does_not_clear_others_watcher() -> None:
    """决策⑫：A leave 只摘自己的席位，不清 C 的旁观。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        client.post("/circle/api/observe", json={"circle_id": cid}, headers=_auth(TOKEN_C))
        r = client.post("/circle/api/leave", json={"circle_id": cid}, headers=_auth(TOKEN_A))
        assert r.status_code == 200
        r = client.get(f"/circle/api/status?circle_id={cid}", headers=_auth(TOKEN_B))
        body = r.json()
        assert [m["sub"] for m in body["circle"]["members"]] == ["tester-b"]
        assert [w["sub"] for w in body["watchers"]] == ["tester-c"]


def test_page_contains_observe_copy() -> None:
    """页面静态文案：有旁观语义、无含混的「全员」确认句。"""
    with TestClient(kernel_app) as client:
        r = client.get("/circle/")
        assert r.status_code == 200
        assert "旁观" in r.text
        assert "/circle/api/observe" in r.text
        assert "入座成员" in r.text
        assert "全员" not in r.text


def test_redeem_invite_flow(tmp_path, monkeypatch) -> None:
    """§8 回归：邀请深链兑换 → 入场（邀请链/本人 ack 不改）。"""
    import time

    from gfcc_kernel import invites as _invites_mod

    store = _invites_mod.InviteStore(tmp_path / "invites.db")
    monkeypatch.setattr(_invites_mod, "_store", store)
    code = _invites_mod.generate_code()
    store.issue("tester-c", code, int(time.time()) + 3600)
    with TestClient(kernel_app) as client:
        r = client.post("/circle/api/redeem", json={"code": code})
        assert r.status_code == 200, r.text
        token = r.json()["token"]
        r = client.get("/circle/api/me", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["sub"] == "tester-c"
        # 同码二兑 → 410 已兑换
        r = client.post("/circle/api/redeem", json={"code": code})
        assert r.status_code == 410


# ---------- G6 兑现与升级（CoCo 循环 + 八角梯） ----------


def _profile(sub: str) -> dict:
    """直接读 identity 端口画像（app 模块级 registry 单例，测试共享）。"""
    from gfcc_kernel import app as app_mod

    return app_mod._registry.get("identity").get_profile(sub).data["profile"]


def test_attest_and_fulfill_mints_evidence_trace() -> None:
    """G6 兑现入口：A 认定 B 的贡献 → A（steward+）兑现 → B 画像出现 contribution evidence 轨迹。

    兑现轨迹由 contribution 端口写入（source_port=contribution, weight=evidence），
    印证「兑现入口打通」而非仅返回 may_mint_trace=True。
    """
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))

        # A 认定 B 的贡献（participant+ 可 attest）
        r = client.post(
            "/circle/api/attest",
            json={"circle_id": cid, "subject_sub": "tester-b", "claim": "B 完成内存隔离验收"},
            headers=_auth(TOKEN_A),
        )
        assert r.status_code == 200, r.text
        rid = r.json()["record_id"]
        assert r.json()["record"]["status"] == "attested"

        # B（participant）不能兑现 → 403（roles.v1：fulfill 属 steward+）
        r = client.post("/circle/api/fulfill", json={"circle_id": cid, "record_id": rid}, headers=_auth(TOKEN_B))
        assert r.status_code == 403

        # A（organizer，包含 steward）兑现 → minted_trace_id 是真实 trace id（非 sub）
        r = client.post("/circle/api/fulfill", json={"circle_id": cid, "record_id": rid}, headers=_auth(TOKEN_A))
        assert r.status_code == 200, r.text
        assert r.json()["record"]["status"] == "fulfilled"
        minted = r.json()["minted_trace_id"]
        # 之前回归：append_trace 返回 id=sub 导致 minted_trace_id 变成 "tester-b"；必须指向 trace 条目
        assert minted is not None and minted != "tester-b"
        assert len(minted) == 36  # uuid4 格式

        # B 画像出现 contribution evidence 轨迹（兑现入口真 mint，非仅标记）
        profile = _profile("tester-b")
        trace = [t for t in profile["capability_trace"] if t["source_port"] == "contribution"]
        assert len(trace) >= 1
        assert trace[-1]["weight"] == "evidence"
        assert trace[-1]["label"].startswith("contribution:")
        assert trace[-1].get("id") == minted  # minted_trace_id 与轨迹条目 id 对应


def test_attest_self_rejected() -> None:
    """不能只为自己 attest 作为唯一证据。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        r = client.post(
            "/circle/api/attest",
            json={"circle_id": cid, "subject_sub": "tester-a", "claim": "我很努力"},
            headers=_auth(TOKEN_A),
        )
        assert r.status_code == 400
        assert "oneself" in r.json()["detail"]


def test_attest_requires_member() -> None:
    """未入座的 C 不能认定贡献。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        r = client.post(
            "/circle/api/attest",
            json={"circle_id": cid, "subject_sub": "tester-b", "claim": "C 乱认定"},
            headers=_auth(TOKEN_C),
        )
        assert r.status_code == 403
        assert "seated members" in r.json()["detail"]


def test_promote_c_requires_evidence() -> None:
    """G6 升级：无证据 → 400（禁止只拨 admin）；带证据 → 升级成功并记录证据引用。

    C 旁观不入座，升级的是 identity 画像 role（observer → participant），
    role_evidence_ids 记录兑现记录 id，role_changed_by 记录执行人。
    """
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))

        # 先造一条真实证据：A 认定 B 并兑现 → evidence_id（fulfilled record）
        r = client.post(
            "/circle/api/attest",
            json={"circle_id": cid, "subject_sub": "tester-b", "claim": "B 完成业务运维"},
            headers=_auth(TOKEN_A),
        )
        rid = r.json()["record_id"]
        r = client.post("/circle/api/fulfill", json={"circle_id": cid, "record_id": rid}, headers=_auth(TOKEN_A))
        assert r.json()["minted_trace_id"] is not None

        # 无证据 → 400（admin toggle 被拒）
        r = client.post(
            "/circle/api/promote",
            json={"circle_id": cid, "sub": "tester-c", "new_role": "participant", "evidence_ids": []},
            headers=_auth(TOKEN_A),
        )
        assert r.status_code == 400
        assert "evidence" in r.json()["detail"]

        # 带证据 → 200：role 升 participant + 记录证据 id
        r = client.post(
            "/circle/api/promote",
            json={"circle_id": cid, "sub": "tester-c", "new_role": "participant", "evidence_ids": [rid]},
            headers=_auth(TOKEN_A),
        )
        assert r.status_code == 200, r.text
        profile = _profile("tester-c")
        assert profile["role"] == "participant"
        assert rid in profile["role_evidence_ids"]
        assert profile["role_changed_by"] == "tester-a"


def test_promote_requires_organizer() -> None:
    """非 organizer（B participant）不能发起升级。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        r = client.post(
            "/circle/api/promote",
            json={"circle_id": cid, "sub": "tester-c", "new_role": "participant", "evidence_ids": ["x"]},
            headers=_auth(TOKEN_B),
        )
        assert r.status_code == 403
        assert "organizer" in r.json()["detail"]
