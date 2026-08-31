"""签发脚本 roundtrip 测试 —— issue_persona_tokens 签发的 JWT 能被 ethos 验签。

防回归：签发格式与 ethos HS256 验签必须始终兼容（Step1 每人一把 token 的钥匙）。

注意：CLI 终端不再打印完整 JWT（防录屏泄漏，见实施单 §6），token 只进 --out 文件，
因此本测试从 --out JSON 解析 token 做 roundtrip 验签。
"""

import json
import subprocess
import sys
from pathlib import Path

from ethos.security import init_security

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "issue_persona_tokens.py"
SECRET = "test-secret-for-roundtrip"


def _run_out(tmp_path: Path, *args: str) -> list:
    out = tmp_path / "tokens.json"
    subprocess.run(
        [sys.executable, str(SCRIPTS), *args, "--secret", SECRET, "--out", str(out)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.read_text())["tokens"]


def test_issue_roundtrip_verifies(tmp_path):
    items = _run_out(tmp_path, "--subs", "tester-a")
    assert items[0]["sub"] == "tester-a"
    ctx = init_security(secret=SECRET).verify(items[0]["token"])
    assert ctx.verified
    assert ctx.principal.sub == "tester-a"


def test_issue_two_subs_distinct(tmp_path):
    items = _run_out(tmp_path, "--subs", "alice", "bob")
    subs = {t["sub"] for t in items}
    tokens = {t["token"] for t in items}
    assert subs == {"alice", "bob"}
    assert len(tokens) == 2  # 每人一把独立 token


def test_issue_duplicate_subs_rejected():
    r = subprocess.run(
        [sys.executable, str(SCRIPTS), "--subs", "x", "x", "--secret", SECRET],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "重复" in r.stderr


# ---------------------------------------------------------------------- #
# W2（Bolent 入驻预埋）：--emails 从邮箱出号（生态号 sha256 hex）
# ---------------------------------------------------------------------- #

ALICE_HASH = "ff8d9819fc0e12bf0d24892e45987e249a28dce836a85cad60e28eaaa8c6d976"


def test_issue_emails_sub_is_ecosystem_hash(tmp_path):
    """--emails 每人 sub = 64 位 hex（§3 alice 标准向量）；--out 禁止出现 email 键。"""
    out = tmp_path / "tokens.json"
    subprocess.run(
        [sys.executable, str(SCRIPTS), "--emails", "alice@example.com",
         "--secret", SECRET, "--out", str(out)],
        capture_output=True, text=True, check=True,
    )
    raw = out.read_text()
    items = json.loads(raw)["tokens"]
    assert items[0]["sub"] == ALICE_HASH
    assert "email" not in raw.lower()  # 明文邮箱不进 --out JSON
    ctx = init_security(secret=SECRET).verify(items[0]["token"])
    assert ctx.verified
    assert ctx.principal.sub == ALICE_HASH


def test_issue_emails_case_folding(tmp_path):
    """大小写折叠：Alice@Example.COM 与 alice@example.com 同号。"""
    out = tmp_path / "tokens.json"
    subprocess.run(
        [sys.executable, str(SCRIPTS), "--emails", "Alice@Example.COM",
         "--secret", SECRET, "--out", str(out)],
        capture_output=True, text=True, check=True,
    )
    items = json.loads(out.read_text())["tokens"]
    assert items[0]["sub"] == ALICE_HASH


def test_issue_emails_two_distinct(tmp_path):
    """两个邮箱 → 两个不同 hex sub，每人一把独立 token。"""
    items = _run_out(tmp_path, "--emails", "alice@example.com", "bob@example.com")
    subs = {t["sub"] for t in items}
    assert len(subs) == 2
    assert len({t["token"] for t in items}) == 2


def test_issue_subs_and_emails_mutually_exclusive():
    """--subs 与 --emails 互斥，同时给出必须拒绝。"""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS), "--subs", "x", "--emails", "a@x",
         "--secret", SECRET],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "互斥" in r.stderr
