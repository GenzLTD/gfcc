#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W4 信号发送器（mock，入库可复跑）—— GFCC 全量 E2E 的"发送"一截。

用法（示例）:
  python scripts/mock_signal_sender.py --base http://127.0.0.1:5211
  python scripts/mock_signal_sender.py --case valid-beacon
  python scripts/mock_signal_sender.py --case restart-persist-seed
  python scripts/mock_signal_sender.py --case restart-persist-verify

密钥: 只读环境变量 SIGNAL_INGEST_SECRET，不写进脚本、不传参。
      （未设置且未显式 --dev-no-auth 时直接退出，避免误判契约语义）

用例矩阵（对齐 Phase2_Step3 §3.3 契约语义 / signal.envelope.v1）:
  valid-beacon           合法 personality_beacon     → 200 stored, port=identity
  valid-match            合法 consensus_match        → 200 stored, port=consensus
  duplicate              同 nonce 再发               → 200 duplicate, signal_id 相同
  bad-signature          错误 X-Signature            → 401 invalid_signature
  missing-field          缺字段                      → 422 invalid_envelope
  extra-field            多余字段                    → 422 invalid_envelope
  unknown-type           未知 signal_type            → 422 unsupported_signal
  restart-persist-seed   发两条真信号落库（记录 signal_id）
  restart-persist-verify 杀进程重启后查库：旧记录仍在

退出码: 全部 PASS → 0；任一 FAIL → 1（可挂 CI / 交件留痕）。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # services/gfcc_kernel/
SEED_FILE = BASE_DIR / "data" / ".w4_restart_seed.json"

HEADERS_JSON = {"Content-Type": "application/json"}

# 合法样例（对齐 signal.py validate_payload / contracts/signals/*.v1.json）
SAMPLE = {
    "personality_beacon": {
        "signal_type": "personality_beacon",
        "user_id_hash": "b" * 64,
        "nonce": "",
        "payload": {
            "personality_type": "INTJ",
            "traits": [{"name": "T", "score": 0.72}, {"name": "N", "score": 0.55}],
            "assessment_score": 0.61,
            "source": "planetx",
        },
    },
    "consensus_match": {
        "signal_type": "consensus_match",
        "user_id_hash": "c" * 64,
        "nonce": "",
        "payload": {
            "match_score": 0.91,
            "shared_tags": ["gfcc", "consensus"],
            "peer_id_hash": "d" * 64,
            "source": "demoppi",
        },
    },
}

PASSED, FAILED = [], []


def log_result(name: str, ok: bool, detail: str) -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<28} {detail}")


def sign(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def post(base: str, body: dict, secret: str | None, tamper_sig: str | None = None,
         headers_extra: dict | None = None) -> tuple[int, dict]:
    """POST /v1/signal-ingest。返回 (status_code, json)。"""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = dict(HEADERS_JSON)
    if headers_extra:
        headers.update(headers_extra)
    if tamper_sig is not None:
        headers["X-Signature"] = tamper_sig
    elif secret is not None:
        headers["X-Signature"] = sign(secret, raw)
    req = urllib.request.Request(base.rstrip("/") + "/v1/signal-ingest",
                                 data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return exc.code, {"code": "unparseable", "detail": str(exc)}


def fresh_nonce() -> str:
    import uuid
    return uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# 单用例
# --------------------------------------------------------------------------- #

def case_valid(base: str, secret: str | None, kind: str) -> None:
    env = dict(SAMPLE[kind])
    env["nonce"] = fresh_nonce()
    code, body = post(base, env, secret)
    expected_port = "identity" if kind == "personality_beacon" else "consensus"
    ok = code == 200 and body.get("status") == "stored" and body.get("port") == expected_port
    log_result(f"valid-{kind}", ok,
               f"200 stored port={expected_port} -> {code} {body.get('status')}/{body.get('port')}")


def case_duplicate(base: str, secret: str | None) -> None:
    env = dict(SAMPLE["personality_beacon"])
    env["nonce"] = fresh_nonce()
    raw = json.dumps(env, ensure_ascii=False).encode("utf-8")
    headers = dict(HEADERS_JSON)
    if secret is not None:
        headers["X-Signature"] = sign(secret, raw)
    req = urllib.request.Request(base.rstrip("/") + "/v1/signal-ingest",
                                 data=raw, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        first = resp.status, json.loads(resp.read().decode("utf-8"))
    code2, body2 = post(base, env, secret)
    same_id = code2 == 200 and body2.get("signal_id") == first[1].get("signal_id")
    ok = first[0] == 200 and code2 == 200 and body2.get("status") == "duplicate" and same_id
    log_result("duplicate", ok,
               f"2nd -> {code2} duplicate signal_id相同={same_id}")


def case_bad_signature(base: str, secret: str) -> None:
    env = dict(SAMPLE["consensus_match"])
    env["nonce"] = fresh_nonce()
    code, body = post(base, env, secret, tamper_sig="0" * 64)
    ok = code == 401 and body.get("code") == "invalid_signature"
    log_result("bad-signature", ok, f"401 invalid_signature -> {code} {body.get('code')}")


def case_missing_field(base: str, secret: str | None) -> None:
    env = dict(SAMPLE["consensus_match"])
    env["nonce"] = fresh_nonce()
    del env["payload"]  # 缺 payload（必填）
    code, body = post(base, env, secret)
    ok = code == 422 and body.get("code") == "invalid_envelope"
    log_result("missing-field", ok, f"422 invalid_envelope -> {code} {body.get('code')}")


def case_extra_field(base: str, secret: str | None) -> None:
    env = dict(SAMPLE["personality_beacon"])
    env["nonce"] = fresh_nonce()
    env["hacked_extra"] = "surprise"  # 信封多余字段（additionalProperties=false）
    code, body = post(base, env, secret)
    ok = code == 422 and body.get("code") == "invalid_envelope"
    log_result("extra-field", ok, f"422 invalid_envelope -> {code} {body.get('code')}")


def case_unknown_type(base: str, secret: str | None) -> None:
    env = dict(SAMPLE["personality_beacon"])
    env["nonce"] = fresh_nonce()
    env["signal_type"] = "hacked_signal"
    code, body = post(base, env, secret)
    ok = code == 422 and body.get("code") == "unsupported_signal"
    log_result("unknown-type", ok, f"422 unsupported_signal -> {code} {body.get('code')}")


# --------------------------------------------------------------------------- #
# 杀进程再启动：持久化验证（两阶段，可复跑）
# --------------------------------------------------------------------------- #

def db_path_from_env() -> str:
    p = os.getenv("SIGNAL_LOG_DB") or os.getenv("STORE_DB_PATH") or ""
    if p and os.path.isabs(p):
        return p
    if p:
        return str(BASE_DIR / p)
    return str(BASE_DIR / "data" / "memory.db")


def _default_db() -> str:
    return db_path_from_env()


def case_restart_seed(base: str, secret: str | None, db: str) -> None:
    records = []
    for kind in ("personality_beacon", "consensus_match"):
        env = dict(SAMPLE[kind])
        env["nonce"] = fresh_nonce()
        code, body = post(base, env, secret)
        if code != 200 or body.get("status") != "stored":
            log_result(f"restart-seed:{kind}", False, f"seed 失败 {code} {body}")
            return
        records.append({"signal_id": body["signal_id"], "signal_type": kind})
    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    # seed 文件自带库路径：verify 阶段自包含读取，不依赖 shell 环境变量
    payload = {"db": db, "records": records}
    SEED_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log_result("restart-persist-seed", True,
               f"2 条已落库 -> {db}，signal_id 已记录（现在可杀 5211 再启动）")


def case_restart_verify(db: str | None = None) -> None:
    if not SEED_FILE.exists():
        log_result("restart-persist-verify", False,
                   "缺少 seed 文件，请先跑 --case restart-persist-seed")
        return
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    records = seed["records"]
    # seed 文件里的 db 是权威（写入时的真实库路径）；--db 仅作显式覆盖
    db = seed.get("db") or db or _default_db()
    conn = sqlite3.connect(db)
    ok_all = True
    for rec in records:
        cur = conn.execute(
            "SELECT signal_id, signal_type, created_at FROM signal_log WHERE signal_id=?",
            (rec["signal_id"],),
        )
        row = cur.fetchone()
        found = row is not None and row[1] == rec["signal_type"]
        ok_all &= found
        print(f"    [{row[1] if row else 'MISSING':<20}] {rec['signal_id']} "
              f"{'仍在' if found else '丢失!'}")
    conn.close()
    log_result("restart-persist-verify", ok_all, f"旧记录在 signal_log 中：{ok_all}")


# --------------------------------------------------------------------------- #

CASES = {
    "valid-beacon": lambda a: case_valid(a.base, a.secret, "personality_beacon"),
    "valid-match": lambda a: case_valid(a.base, a.secret, "consensus_match"),
    "duplicate": lambda a: case_duplicate(a.base, a.secret),
    "bad-signature": lambda a: case_bad_signature(a.base, a.secret),
    "missing-field": lambda a: case_missing_field(a.base, a.secret),
    "extra-field": lambda a: case_extra_field(a.base, a.secret),
    "unknown-type": lambda a: case_unknown_type(a.base, a.secret),
    "restart-persist-seed": lambda a: case_restart_seed(a.base, a.secret, a.db),
    "restart-persist-verify": lambda a: case_restart_verify(a.db),
}
ALL = ["valid-beacon", "valid-match", "duplicate", "bad-signature",
       "missing-field", "extra-field", "unknown-type"]


def main() -> int:
    p = argparse.ArgumentParser(description="W4 信号发送器（mock，可复跑）")
    p.add_argument("--base", default="http://127.0.0.1:5211",
                   help="gfcc_kernel 基址（默认 http://127.0.0.1:5211，勿写死局域网 IP）")
    p.add_argument("--case", choices=sorted(CASES) + ["all"], default="all",
                   help="单用例或 all（all 不含 restart-persist，需两阶段手动重启）")
    p.add_argument("--db", help="signal_log 库路径（restart-persist-verify 用）")
    p.add_argument("--dev-no-auth", action="store_true",
                   help="SIGNAL_INGEST_SECRET 未设时也跑（本机调试用，默认拒绝）")
    args = p.parse_args()

    args.secret = os.environ.get("SIGNAL_INGEST_SECRET")
    # restart-persist-verify 只查库（不 HTTP），不需要密钥
    if args.case != "restart-persist-verify" and not args.secret and not args.dev_no_auth:
        print("[error] SIGNAL_INGEST_SECRET 未设置（密钥只读环境变量，不写进脚本）")
        print("        本机调试可加 --dev-no-auth，但契约用例 bad-signature 将无意义。")
        return 2
    args.db = args.db or db_path_from_env()

    cases = ALL if args.case == "all" else [args.case]
    print(f"== W4 mock_signal_sender  base={args.base}  cases={len(cases)}")
    for c in cases:
        try:
            CASES[c](args)
        except Exception as exc:  # noqa: BLE001
            log_result(c, False, f"异常: {type(exc).__name__}: {exc}")

    print(f"== 结果  PASS={len(PASSED)} FAIL={len(FAILED)}")
    if FAILED:
        print(f"   失败: {FAILED}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
