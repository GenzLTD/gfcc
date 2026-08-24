"""mock_signal_sender —— Step3 W4：机机信号发送端模拟器（demoppi / planetx）。

按 signal.envelope.v1 契约构造信封并 HMAC 签名后投递到 gfcc_kernel
的 POST /v1/signal-ingest，用于本地 E2E（覆盖 stored / duplicate / 401 / 422）。

用法：
    python scripts/mock_signal_sender.py --type consensus_match
    python scripts/mock_signal_sender.py --type personality_beacon
    python scripts/mock_signal_sender.py --type consensus_match --secret <SECRET>
    python scripts/mock_signal_sender.py --repeat 2          # 同 nonce 重放 -> duplicate
    python scripts/mock_signal_sender.py --broken missing    # 缺字段 -> 422
    python scripts/mock_signal_sender.py --broken signature  # 错签名 -> 401

secret 优先级：--secret > 环境变量 SIGNAL_INGEST_SECRET > 空（dev 免签）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
import uuid

# 允许直接以脚本方式运行（无需 pip install -e）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "gfcc_kernel", "src"))

from gfcc_kernel.signal import build_hmac_signature  # noqa: E402

DEFAULT_URL = "http://localhost:5211/v1/signal-ingest"


def hash_email(email: str) -> str:
    return hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()


def build_envelope(signal_type: str) -> dict:
    if signal_type == "consensus_match":
        return {
            "signal_type": "consensus_match",
            "user_id_hash": hash_email("alice@example.com"),
            "nonce": uuid.uuid4().hex,
            "payload": {
                "match_score": 0.92,
                "shared_tags": ["python", "内核"],
                "peer_id_hash": hash_email("bob@example.com"),
                "source": "demoppi",
            },
        }
    if signal_type == "personality_beacon":
        return {
            "signal_type": "personality_beacon",
            "user_id_hash": hash_email("alice@example.com"),
            "nonce": uuid.uuid4().hex,
            "payload": {"personality_type": "INTJ", "source": "planetx"},
        }
    raise SystemExit(f"unknown signal_type: {signal_type}")


def post(url: str, body: dict, secret: str, broken: str | None) -> None:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if broken == "signature":
        headers = {"X-Signature": "0" * 64}
    elif broken == "missing":
        del body["nonce"]  # 缺字段 -> 信封不合法 -> 422
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"X-Signature": build_hmac_signature(secret, raw)} if secret else {}
    else:
        headers = {"X-Signature": build_hmac_signature(secret, raw)} if secret else {}

    req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"HTTP {resp.status}")
            print(json.dumps(json.loads(resp.read().decode("utf-8")), ensure_ascii=False, indent=2))
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}")
        print(exc.read().decode("utf-8", errors="replace"))


def main() -> None:
    parser = argparse.ArgumentParser(description="signal.envelope.v1 mock sender (W4)")
    parser.add_argument("--type", choices=["consensus_match", "personality_beacon"],
                        default="consensus_match")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--secret", default=os.getenv("SIGNAL_INGEST_SECRET", ""))
    parser.add_argument("--repeat", type=int, default=1,
                        help="同信封重复发送次数（>1 演示幂等 duplicate）")
    parser.add_argument("--broken", choices=["missing", "signature"], default=None,
                        help="演示 422（缺字段）/ 401（错签名）")
    args = parser.parse_args()

    envelope = build_envelope(args.type)
    if args.broken is None and args.repeat > 1:
        # 幂等演示：固定 nonce 重放同一信封
        envelope["nonce"] = uuid.uuid4().hex
        for i in range(args.repeat):
            print(f"--- send #{i + 1} (nonce={envelope['nonce'][:8]}…) ---")
            post(args.url, dict(envelope), args.secret, None)
        return

    print(f"--- send ({args.type}) ---")
    post(args.url, envelope, args.secret, args.broken)


if __name__ == "__main__":
    main()
