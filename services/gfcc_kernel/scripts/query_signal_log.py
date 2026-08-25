#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_log 官方查库方式（Windows/Mac 两侧同名查询，防表名/字段分叉）。

落库文件: services/gfcc_kernel/data/signal_log.db（Mac 侧约定；Windows 侧
          由 SIGNAL_LOG_DB 控制，未设则回退 STORE_DB_PATH / data/memory.db，
          表结构一致——signal_log 表永远是这个）。

固定 SQL（对齐两侧实现的唯一官方查询）:
  SELECT signal_id, signal_type, user_id_hash, nonce, created_at
    FROM signal_log
   ORDER BY created_at DESC
   LIMIT ?;

用法:
  python scripts/query_signal_log.py                    # 最近 20 条
  python scripts/query_signal_log.py --type consensus_match
  python scripts/query_signal_log.py --signal-id <id>
  python scripts/query_signal_log.py --limit 50 --json
  python scripts/query_signal_log.py --sql "SELECT COUNT(*) FROM signal_log"
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # services/gfcc_kernel/

FIXED_SQL = (
    "SELECT signal_id, signal_type, user_id_hash, nonce, created_at "
    "FROM signal_log ORDER BY created_at DESC LIMIT ?;"
)
COLUMNS = ["signal_id", "signal_type", "user_id_hash", "nonce", "created_at"]


def default_db() -> str:
    p = os.getenv("SIGNAL_LOG_DB") or os.getenv("STORE_DB_PATH") or ""
    if p and os.path.isabs(p):
        return p
    if p:
        return str(BASE_DIR / p)
    return str(BASE_DIR / "data" / "memory.db")


def main() -> int:
    p = argparse.ArgumentParser(description="signal_log 官方查询")
    p.add_argument("--db", help=f"库路径（默认 env SIGNAL_LOG_DB / STORE_DB_PATH / {default_db()}）")
    p.add_argument("--signal-id")
    p.add_argument("--type", dest="sig_type")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.add_argument("--sql", help="任意只读 SQL（覆盖固定 SQL）")
    args = p.parse_args()

    db = args.db or default_db()
    if not os.path.exists(db):
        print(f"[error] 库不存在: {db}（先启动 5211 并用 STORE_PROVIDER=sqlite 落过库）")
        return 1

    if args.sql:
        sql, params = args.sql, ()
    else:
        sql, params = FIXED_SQL, (args.limit,)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        print(f"[error] SQL 失败: {exc}")
        return 1
    finally:
        conn.close()

    if args.signal_id:
        rows = [r for r in rows if r["signal_id"] == args.signal_id]
    if args.sig_type:
        rows = [r for r in rows if r["signal_type"] == args.sig_type]

    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return 0

    print(f"== signal_log @ {db}  ({len(rows)} 行)")
    print(f"   {FIXED_SQL.split(';')[0]};")
    for r in rows:
        print(f"   [{r['signal_type']:<18}] {r['signal_id']}")
        print(f"       nonce={r['nonce']} created={r['created_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
