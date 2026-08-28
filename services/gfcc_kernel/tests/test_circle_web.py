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


def test_propose_organizer_only() -> None:
    """B 已入座也不能写拍板句：只有建圈的 A（organizer）能写，避免互相覆盖。"""
    with TestClient(kernel_app) as client:
        cid = _create_circle(client)
        client.post("/circle/api/join", json={"circle_id": cid}, headers=_auth(TOKEN_B))
        r = client.post(
            "/circle/api/propose",
            json={"circle_id": cid, "subject": "B 也想写一句"},
            headers=_auth(TOKEN_B),
        )
        assert r.status_code == 403
        assert "organizer" in r.json()["detail"]


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
