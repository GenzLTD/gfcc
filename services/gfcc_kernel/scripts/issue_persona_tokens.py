"""签发 Step1「每人一个 sub」测试 JWT（HS256，对齐 ethos 验签）。

用法：
    .venv/bin/python scripts/issue_persona_tokens.py                    # 占位 4 人，输出到终端
    .venv/bin/python scripts/issue_persona_tokens.py --subs alice bob   # 自定义 sub
    .venv/bin/python scripts/issue_persona_tokens.py --out /tmp/persona_tokens.json

- 密钥：优先 --secret；否则读 services/gfcc_kernel/.env 的 ETHOS_AUTH_SECRET
  （与内核同一把；≠ SIGNAL_INGEST_SECRET，勿混用）。
- 输出的 token 与 sub 一一对应，sub 即内核 policy.sub（actor 身份）。
- 过期默认 30 天（--days 调整）。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

_KERNEL_ROOT = Path(__file__).resolve().parents[1]


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_hs256(secret: str, signing_input: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()


def issue_token(sub: str, secret: str, days: int = 30, tier: str = "pro") -> str:
    """HS256 JWT：{alg:HS256, typ:JWT} + {sub, tier, iat, exp}，与 ethos._jwt 兼容。"""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload: Dict[str, Any] = {
        "sub": sub,
        "tier": tier,
        "iat": now,
        "exp": now + days * 86400,
    }
    h = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = sign_hs256(secret, f"{h}.{p}")
    return f"{h}.{p}.{b64url(sig)}"


def load_secret(secret_arg: Optional[str]) -> str:
    if secret_arg:
        return secret_arg
    env_file = _KERNEL_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("ETHOS_AUTH_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    env_val = os.getenv("ETHOS_AUTH_SECRET", "").strip()
    if env_val:
        return env_val
    sys.exit("ETHOS_AUTH_SECRET 未配置：请先配 services/gfcc_kernel/.env（与签发脚本同一把，≠ SIGNAL_INGEST_SECRET）")


def main() -> None:
    parser = argparse.ArgumentParser(description="签发 Step1 每人一张 ethos JWT")
    parser.add_argument("--subs", nargs="+", default=None,
                        help="sub 列表（默认占位 4 人，按报名表替换）")
    parser.add_argument("--secret", default=None, help="HS256 密钥（默认读 .env 的 ETHOS_AUTH_SECRET）")
    parser.add_argument("--out", default=None, help="输出 JSON 文件（默认只打印）")
    parser.add_argument("--days", type=int, default=30, help="token 有效期（天）")
    args = parser.parse_args()

    secret = load_secret(args.secret)
    subs: List[str] = args.subs or ["tester-a", "tester-b", "tester-c", "tester-d"]
    if len(subs) != len(set(subs)):
        sys.exit("subs 有重复，每人一把独立 token，禁止共用")

    issued: List[Dict[str, str]] = []
    for sub in subs:
        token = issue_token(sub, secret, days=args.days)
        issued.append({"sub": sub, "token": token})
        print(f"{sub}\t{token}")

    if args.out:
        out = Path(args.out)
        out.write_text(json.dumps({"secret": secret, "tokens": issued}, ensure_ascii=False, indent=2))
        os.chmod(out, 0o600)
        print(f"\n写入 {out}（chmod 600）")


if __name__ == "__main__":
    main()
