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
