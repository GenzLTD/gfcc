"""W3 户口本 fixture 校验 —— bolent.membership.v0（Bolent 入驻预埋）。

只验 docs/experiments/bolent_membership.fixture.json 的 schema 样例，不 import
生产 DB（红线：户口本真源在 Bolent/genz 社区壳，本 fixture 只是可对账样例；
禁止明文邮箱 / token / ETHOS 密钥进文件）。

验收（docs/experiments/Bolent入驻预埋_Windows行动方案.md §W3）：
1. JSON 可解析；members[] 每项恰有 email_hash / bolent_site_id / status
2. email_hash 匹配 ^[a-f0-9]{64}$
3. status ∈ {applied, active, left}
4. alice 那行的 hash = §3 标准向量
5. 不 import 生产 DB
"""

import json
import re
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[3] / "docs" / "experiments" / "bolent_membership.fixture.json"

ALICE_HASH = "ff8d9819fc0e12bf0d24892e45987e249a28dce836a85cad60e28eaaa8c6d976"
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
STATUS_ENUM = {"applied", "active", "left"}


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_parses_and_schema():
    data = _load()
    assert data["schema"] == "bolent.membership.v0"
    assert isinstance(data["members"], list)
    assert data["members"], "fixture 至少一行样例"


def test_members_have_exact_fields():
    for member in _load()["members"]:
        assert set(member) == {"email_hash", "bolent_site_id", "status"}


def test_email_hash_shape():
    for member in _load()["members"]:
        assert HASH_RE.fullmatch(member["email_hash"])


def test_status_in_enum():
    for member in _load()["members"]:
        assert member["status"] in STATUS_ENUM


def test_alice_row_matches_standard_vector():
    data = _load()
    alice = next(m for m in data["members"] if m["bolent_site_id"] == "site_bolent_demo_1")
    assert alice["email_hash"] == ALICE_HASH


def test_no_plaintext_email_or_secret():
    """红线：fixture 不写明文邮箱 / token / 密钥。"""
    raw = FIXTURE.read_text(encoding="utf-8").lower()
    assert "@" not in raw  # 明文邮箱特征
    assert "token" not in raw
    assert "secret" not in raw
    assert "password" not in raw
