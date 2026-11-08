"""流向门与 lab-genz-brain-m2 固化的 64 组合矩阵对拍。"""

from __future__ import annotations

import json
from pathlib import Path

from ethos.flow import evaluate
from ethos.models import Tier

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rust_cartesian_matrix.json"


def test_matrix_matches_lab_fixture():
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(rows) == 64
    for row in rows:
        got = evaluate(row["tier"], row["source"], row["dest"])
        assert got == row["verdict"], row


def test_unlisted_combination_denies_plaintext():
    assert evaluate("L0_PII", "CN", "EU", rules=()) == "deny_plaintext"
    assert evaluate("not-a-tier", "CN", "EU") == "deny_plaintext"
    assert evaluate("L1", "Atlantis", "CN") == "deny_plaintext"


def test_privacy_tier_is_not_the_quota_tier():
    assert {item.value for item in Tier} == {"free", "basic", "pro", "admin"}
    assert evaluate("public", "CN", "SG") == "allow"
