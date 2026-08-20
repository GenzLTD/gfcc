"""ethos 冒烟自测（无需 pytest，直接运行）：
    python tests/smoke_test.py

覆盖：验签 / Rust-Go 双 Claims 兼容 / 鉴权 / 配额 / 审计 / resolver。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 允许从源码直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ethos.security import (
    QuotaLimit,
    init_security,
    HmacJwtVerifier,
    StubVerifier,
    TierAuthorizer,
    PermissionAuthorizer,
)
from ethos.security._jwt import b64url_encode
from ethos.resolver import init_resolver


# --------------------------------------------------------------------------- #
# 模拟"签发方"（ethos 是纯验证者，这里只在测试中生成令牌）
# --------------------------------------------------------------------------- #

def issue_token(secret: str, claims: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    h = b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p = b64url_encode(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64url_encode(sig)}"


def main() -> None:
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {name}" + (f"  <- {detail}" if detail and not cond else ""))

    print("== 1. 验签：Rust 风格 Claims(sub+role) ==")
    secret = "test-secret"
    tok_rust = issue_token(secret, {"sub": "u-1001", "role": "pro", "exp": int(time.time()) + 3600})
    v = HmacJwtVerifier(secret)
    ctx = v.verify(tok_rust)
    check("Rust token 验签通过", ctx.ok, ctx.error or "")
    check("uid 取自 sub", ctx.principal.user_id == "u-1001", ctx.principal.user_id)
    check("档位识别 role->pro", ctx.principal.tier.value == "pro", ctx.principal.tier.value)

    print("== 2. 验签：Go 风格 Claims(user_id+roles[]) ==")
    tok_go = issue_token(secret, {"user_id": "u-2002", "roles": ["basic"], "permissions": ["ai:chat"]})
    ctx2 = v.verify(tok_go)
    check("Go token 验签通过", ctx2.ok, ctx2.error or "")
    check("uid 兼容 user_id", ctx2.principal.user_id == "u-2002", ctx2.principal.user_id)
    check("roles[] -> basic", ctx2.principal.tier.value == "basic", ctx2.principal.tier.value)
    check("permissions 解析", ctx2.principal.has_permission("ai:chat"))

    print("== 3. 防伪：错误 secret / 篡改 token ==")
    bad = v.verify(issue_token("wrong-secret", {"sub": "u-1"}))
    check("错误 secret 拒绝", not bad.ok, bad.error or "")
    tampered = tok_rust[:-4] + ("AAAA" if not tok_rust.endswith("AAAA") else "BBBB")
    tampered_ctx = v.verify(tampered)
    check("篡改签名拒绝", not tampered_ctx.ok, tampered_ctx.error or "")

    print("== 4. 过期校验 ==")
    expired = v.verify(issue_token(secret, {"sub": "u-3", "exp": int(time.time()) - 10}))
    check("过期 token 拒绝", not expired.ok, expired.error or "")

    print("== 5. Stub 模式（无密钥本地联调） ==")
    stub = StubVerifier()
    sctx = stub.verify("demo-token-anything")
    check("Stub 放行", sctx.ok)
    check("Stub 默认 admin", sctx.principal.tier.value == "admin", sctx.principal.tier.value)

    print("== 6. 鉴权：Tier / Permission ==")
    sec = init_security(
        secret=secret,
        tier_policy={"rag.query": "pro", "resume.parse": "basic"},
        permission_required=None,
    )
    d1 = sec.authorize(ctx, "rag.query")      # pro >= pro
    d2 = sec.authorize(ctx, "resume.parse")   # pro >= basic
    d3 = sec.authorize(ctx2, "rag.query")     # basic < pro → deny
    check("pro 访问 rag.query 放行", d1.allow, d1.reason)
    check("pro 访问 resume.parse 放行", d2.allow, d2.reason)
    check("basic 访问 rag.query 拒绝", not d3.allow, d3.reason)

    perm_sec = init_security(
        secret=secret,
        permission_required={"ai:chat": "ai:chat"},
    )
    pd = perm_sec.authorize(ctx2, "ai:chat")
    check("Permission 鉴权放行", pd.allow, pd.reason)

    print("== 7. 配额：库内默认（本地） ==")
    q = sec.quota
    q.set_limits({"rag.query": QuotaLimit("rag.query", daily=2)})
    s1 = sec.consume_quota(ctx, "rag.query")
    s2 = sec.consume_quota(ctx, "rag.query")
    s3 = sec.consume_quota(ctx, "rag.query")   # 第 3 次应超限
    check("第1次消耗 ok", s1.ok)
    check("第2次消耗 ok", s2.ok)
    check("第3次超限拒绝", not s3.ok, s3.message)
    check("剩余量=0", s3.remaining == 0, str(s3.remaining))

    print("== 8. 审计：SQLite 落库 ==")
    tmp = tempfile.mkdtemp()
    audit_sec = init_security(secret=secret, audit_db=os.path.join(tmp, "audit.db"))
    audit_sec.audit("rag.query", ctx, resource="ask", meta={"took_ms": 12})
    audit_sec.audit("job.match", ctx2, resource="match", meta={"top_n": 3})
    recent = audit_sec.auditor.backend.recent(limit=10)
    check("审计落库 2 条", len(recent) == 2, str(len(recent)))
    check("审计字段含 action", recent[0]["action"] == "rag.query" or recent[1]["action"] == "rag.query", str(recent))
    check("审计含 user_id", any(r["user_id"] == "u-1001" for r in recent))

    print("== 9. resolver：资源路径 + 服务定位 ==")
    cfg_path = os.path.join(tmp, "resources.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "poetry_corpus": "${POETRY_ROOT:-./corpus}/chinese-poetry",
                "chroma_index": "${WORKSPACE:-./data}/chroma",
                "services": {"auth": "http://127.0.0.1:8207"},
            },
            f,
        )
    rsl = init_resolver(cfg_path)
    p = rsl.path("poetry_corpus")
    check("路径已绝对化", os.path.isabs(p), p)
    check("路径统一 / 分隔符", "/" in p and "\\" not in p.replace("/", ""), p)
    s = rsl.service("auth")
    check("服务定位", s == "http://127.0.0.1:8207", str(s))

    print()
    print("RESULT:", "ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
