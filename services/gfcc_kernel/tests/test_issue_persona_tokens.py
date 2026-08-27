"""签发脚本 roundtrip 测试 —— issue_persona_tokens 签发的 JWT 能被 ethos 验签。

防回归：签发格式与 ethos HS256 验签必须始终兼容（Step1 每人一把 token 的钥匙）。
"""

import subprocess
import sys
from pathlib import Path

from ethos.security import init_security

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "issue_persona_tokens.py"
SECRET = "test-secret-for-roundtrip"


def _run(*args: str) -> str:
    return subprocess.run(
        [sys.executable, str(SCRIPTS), *args, "--secret", SECRET],
        capture_output=True, text=True, check=True,
    ).stdout


def test_issue_roundtrip_verifies():
    out = _run("--subs", "tester-a")
    sub, token = out.strip().split("\t")
    assert sub == "tester-a"
    ctx = init_security(secret=SECRET).verify(token)
    assert ctx.verified
    assert ctx.principal.sub == "tester-a"


def test_issue_two_subs_distinct():
    out = _run("--subs", "alice", "bob")
    lines = [ln.split("\t") for ln in out.strip().splitlines()]
    subs = {s for s, _ in lines}
    tokens = {t for _, t in lines}
    assert subs == {"alice", "bob"}
    assert len(tokens) == 2  # 每人一把独立 token


def test_issue_duplicate_subs_rejected():
    r = subprocess.run(
        [sys.executable, str(SCRIPTS), "--subs", "x", "x", "--secret", SECRET],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "重复" in r.stderr
