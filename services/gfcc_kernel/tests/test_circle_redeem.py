"""邀请深链 redeem 测试（stub 模式 + 临时 SQLite 邀请库）。

覆盖施工单 §8 清单：400 / 404 / 200→410 / 过期 404 / 作废旧码 / 限流 429 /
旧 JWT 粘贴入场回归 / 页面静态断言 / CLI 不泄 secret + 邀请链接格式 + 跨进程落盘。
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gfcc_kernel import invites
from gfcc_kernel.app import app as kernel_app
from gfcc_kernel.circle_web import _RATE_FAIL_LIMIT, _rate_fails
from gfcc_kernel.invites import InviteStore, generate_code

_KERNEL_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _KERNEL_ROOT / "scripts"

_CODE = "ABCDEFGHJKMNPQRT"  # 16 位合法格式（Crockford 字符集内）


def _b64(o: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(o).encode("utf-8")).rstrip(b"=").decode("ascii")


def _jwt(sub: str) -> str:
    header = _b64({"alg": "HS256", "typ": "JWT"})
    payload = _b64({"sub": sub, "tier": "pro", "iat": 0, "exp": 4102444800})
    return f"{header}.{payload}.ZmFrZXNpZw"


@pytest.fixture()
def client():
    with TestClient(kernel_app) as c:
        yield c


@pytest.fixture()
def store(tmp_path, monkeypatch):
    s = InviteStore(tmp_path / "circle_invites.db")
    monkeypatch.setattr(invites, "_store", s)
    yield s
    monkeypatch.setattr(invites, "_store", None)


@pytest.fixture(autouse=True)
def _clean_rate():
    _rate_fails.clear()
    yield
    _rate_fails.clear()


# --------------------------------------------------------------------------- #
# redeem 端点
# --------------------------------------------------------------------------- #


def test_redeem_missing_code_400(client) -> None:
    r = client.post("/circle/api/redeem", json={})
    assert r.status_code == 400


def test_redeem_bad_format_400(client) -> None:
    r = client.post("/circle/api/redeem", json={"code": "abc"})
    assert r.status_code == 400
    r2 = client.post("/circle/api/redeem", json={"code": "OOOOOOOOOOOOOOOO"})
    assert r2.status_code == 400  # 不在 Crockford 字符集


def test_redeem_unknown_404(client) -> None:
    r = client.post("/circle/api/redeem", json={"code": _CODE})
    assert r.status_code == 404


def test_redeem_ok_then_used_and_me(client, store) -> None:
    code = generate_code()
    store.issue("tester-inv", code, int(time.time()) + 3600)
    r = client.post("/circle/api/redeem", json={"code": code})
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "tester-inv"
    assert body["token"]
    # 兑换出的 token 能直接入场
    r2 = client.get("/circle/api/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert r2.status_code == 200
    assert r2.json()["sub"] == "tester-inv"
    # 二次兑换 → 410
    r3 = client.post("/circle/api/redeem", json={"code": code})
    assert r3.status_code == 410


def test_redeem_expired_404(client, store) -> None:
    code = generate_code()
    store.issue("tester-exp", code, int(time.time()) - 10)
    r = client.post("/circle/api/redeem", json={"code": code})
    assert r.status_code == 404


def test_reissue_revokes_old(client, store) -> None:
    old = generate_code()
    new = generate_code()
    store.issue("tester-re", old, int(time.time()) + 3600)
    store.issue("tester-re", new, int(time.time()) + 3600)
    assert client.post("/circle/api/redeem", json={"code": old}).status_code == 404
    assert client.post("/circle/api/redeem", json={"code": new}).status_code == 200


def test_rate_limit_429_then_recovers(client, store) -> None:
    code = generate_code()
    store.issue("tester-rate", code, int(time.time()) + 3600)
    _rate_fails["testclient"] = deque([time.time()] * _RATE_FAIL_LIMIT)
    r = client.post("/circle/api/redeem", json={"code": code})
    assert r.status_code == 429
    _rate_fails.pop("testclient", None)
    assert client.post("/circle/api/redeem", json={"code": code}).status_code == 200


def test_failed_redeem_counts_toward_limit(client) -> None:
    """失败计数：连续未知码失败累积，达到上限后合法码也被挡（防御）。"""
    for _ in range(_RATE_FAIL_LIMIT):
        client.post("/circle/api/redeem", json={"code": _CODE})
    r = client.post("/circle/api/redeem", json={"code": _CODE})
    assert r.status_code == 429


# --------------------------------------------------------------------------- #
# 回归与页面
# --------------------------------------------------------------------------- #


def test_old_jwt_entry_regression(client) -> None:
    """旧流程：主持人先发 JWT，tester 粘贴入场仍 200（§8.5 回归）。"""
    token = _jwt("tester-old")
    r = client.get("/circle/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["sub"] == "tester-old"


def test_page_static_asserts(client) -> None:
    r = client.get("/circle/")
    assert r.status_code == 200
    assert "没有注册" in r.text
    assert "/circle/api/redeem" in r.text
    assert "邀请链接" in r.text


# --------------------------------------------------------------------------- #
# CLI 签发
# --------------------------------------------------------------------------- #


def test_cli_no_secret_in_out_and_invite_url(tmp_path) -> None:
    out = tmp_path / "out.json"
    db = tmp_path / "cli.db"
    env = {**os.environ, "ETHOS_AUTH_SECRET": "t", "CIRCLE_INVITES_DB": str(db)}
    base = "http://127.0.0.1:5211/circle/"
    r = subprocess.run(
        [
            sys.executable, str(_SCRIPTS / "issue_persona_tokens.py"),
            "--subs", "cli-inv-a", "--secret", "t",
            "--out", str(out), "--invite-base", base, "--invite-days", "7",
        ],
        capture_output=True, text=True, env=env, cwd=_KERNEL_ROOT, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text())
    assert "secret" not in data
    item = data["tokens"][0]
    assert item["sub"] == "cli-inv-a"
    url = item["invite_url"]
    assert url.startswith(base)
    assert "?i=" in url
    assert "eyJ" not in url  # URL 只带 16 位码，不带 JWT
    assert "eyJ" not in r.stdout  # 终端不打印完整 JWT
    # 跨进程落盘：同一库文件，redeem 能兑
    status, sub, _exp = InviteStore(db).redeem(item["invite_code"])
    assert status == "ok"
    assert sub == "cli-inv-a"


def test_cli_without_invite_base_keeps_old_behavior(tmp_path) -> None:
    """不带 --invite-base：行为与旧版一致（不落邀请码，仍可 --out）。"""
    out = tmp_path / "old.json"
    r = subprocess.run(
        [
            sys.executable, str(_SCRIPTS / "issue_persona_tokens.py"),
            "--subs", "cli-bare", "--secret", "t", "--out", str(out),
        ],
        capture_output=True, text=True,
        env={**os.environ, "ETHOS_AUTH_SECRET": "t", "CIRCLE_INVITES_DB": str(tmp_path / "unused.db")},
        cwd=_KERNEL_ROOT, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text())
    assert data["tokens"][0]["sub"] == "cli-bare"
    assert "invite_url" not in data["tokens"][0]
