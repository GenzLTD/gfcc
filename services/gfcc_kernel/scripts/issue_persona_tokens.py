"""签发 Step1「每人一个 sub」测试 JWT（HS256，对齐 ethos 验签）+ 可选邀请码落盘。

用法：
    .venv/bin/python scripts/issue_persona_tokens.py                    # 占位 4 人，输出到终端
    .venv/bin/python scripts/issue_persona_tokens.py --subs alice bob   # 自定义 sub
    .venv/bin/python scripts/issue_persona_tokens.py --out /tmp/persona_tokens.json
    .venv/bin/python scripts/issue_persona_tokens.py --subs alice \
        --invite-base http://14.29.216.219/circle/ --invite-days 7     # 顺带发邀请码

- 密钥：优先 --secret；否则读 services/gfcc_kernel/.env 的 ETHOS_AUTH_SECRET
  （与内核同一把；≠ SIGNAL_INGEST_SECRET，勿混用）。
- 签发的 JWT 与 redeem 端点同实现（gfcc_kernel.tokens），payload 结构一致。
- --invite-base 给出会场根 URL 时，邀请码落盘 data/circle_invites.db
  （CIRCLE_INVITES_DB 可覆盖），并在 --out JSON / 终端输出 invite_url
  （只带 16 位码，不含 JWT）。
- 终端每行只打 sub \\t invite_url \\t code，不打印完整 JWT；完整 JWT 只进 --out 文件。
- --out 永远不写 secret（chmod 600）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

_KERNEL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KERNEL_ROOT / "src"))

from gfcc_kernel.invites import InviteStore, generate_code  # noqa: E402
from gfcc_kernel.tokens import issue_token, load_secret  # noqa: E402


def _invite_url(base: str, code: str) -> str:
    sep = "" if base.endswith("/") or base.endswith("?") else "/"
    return base + sep + "?i=" + urllib.parse.quote(code, safe="")


def main() -> None:
    parser = argparse.ArgumentParser(description="签发 Step1 每人一张 ethos JWT（可选带邀请码）")
    parser.add_argument("--subs", nargs="+", default=None,
                        help="sub 列表（默认占位 4 人，按报名表替换）")
    parser.add_argument("--secret", default=None, help="HS256 密钥（默认读 .env 的 ETHOS_AUTH_SECRET）")
    parser.add_argument("--out", default=None, help="输出 JSON 文件（默认只打印；永不写 secret）")
    parser.add_argument("--days", type=int, default=30, help="token 有效期（天）")
    parser.add_argument("--invite-base", default=None,
                        help="邀请链接前缀（形如 http://<host>/circle/）；给出才落邀请码")
    parser.add_argument("--invite-days", type=int, default=None,
                        help="邀请码有效期（天）；默认与 --days 一致")
    args = parser.parse_args()

    secret = load_secret(args.secret)
    if not secret:
        sys.exit("ETHOS_AUTH_SECRET 未配置：请先配 services/gfcc_kernel/.env（与签发脚本同一把，≠ SIGNAL_INGEST_SECRET）")
    subs: List[str] = args.subs or ["tester-a", "tester-b", "tester-c", "tester-d"]
    if len(subs) != len(set(subs)):
        sys.exit("subs 有重复，每人一把独立 token，禁止共用")

    invite_days = args.invite_days if args.invite_days is not None else args.days
    store = InviteStore() if args.invite_base else None

    issued: List[Dict[str, Any]] = []
    for sub in subs:
        token = issue_token(sub, secret, days=args.days)
        item: Dict[str, Any] = {"sub": sub, "token": token}
        url: Optional[str] = None
        if store is not None:
            code = generate_code()
            exp = int(time.time()) + invite_days * 86400
            store.issue(sub, code, exp)
            url = _invite_url(args.invite_base, code)
            item["invite_code"] = code
            item["invite_url"] = url
            item["exp"] = exp
        issued.append(item)
        print(f"{sub}\t{url or '(no invite-base)'}\t{item.get('invite_code', '')}")

    if args.out:
        out = Path(args.out)
        out.write_text(json.dumps({"tokens": issued}, ensure_ascii=False, indent=2))
        os.chmod(out, 0o600)
        print(f"\n写入 {out}（chmod 600，不含 secret）")


if __name__ == "__main__":
    main()
