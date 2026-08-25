#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dialogue_library · query.py —— 对话库（情景记忆子集）检索端
位置: E:\\CorpusPipeline\\dialogue_library

用法:
  python query.py recall 验收 --limit 5          # 全文检索对话片段（中文可用）
  python query.py transcript demo-001            # 回看某会话完整流水
  python query.py list-sessions                  # 会话清单
  python query.py stats                          # 数据统计
  python query.py recall 验收 --session demo-001 --json
"""
import argparse
import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "data", "dialogue.db")


def _conn(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_recall(args) -> None:
    conn = _conn(args.db)
    where, params = [], []
    if args.session:
        where.append("t.session_id=?")
        params.append(args.session)
    if args.role:
        where.append("t.role=?")
        params.append(args.role)
    if args.mode:
        where.append("t.mode=?")
        params.append(args.mode)
    cond = (" AND " + " AND ".join(where)) if where else ""
    base = (
        "SELECT t.session_id, t.seq, t.role, t.mode, t.signal_ref, t.channel, t.ts, t.content,"
        "       s.title AS session_title,"
    )
    q = args.query.strip()
    if len(q) >= 3:
        # 全文检索（trigram，≥3 字符）
        sql = (
            base + " bm25(turns_fts) AS bm25"
            "  FROM turns_fts"
            "  JOIN turns t ON t.id = turns_fts.rowid"
            "  LEFT JOIN sessions s ON s.session_id = t.session_id"
            f" WHERE turns_fts MATCH ?{cond}"
            "  ORDER BY bm25(turns_fts) LIMIT ?"
        )
        params = ["\"" + q.replace("\"", "\"\"") + "\""] + params + [args.limit]
    else:
        # 短查询（<3 字符）回退 LIKE 模糊匹配
        sql = (
            base + " 0.0 AS bm25"
            "  FROM turns t"
            "  LEFT JOIN sessions s ON s.session_id = t.session_id"
            f" WHERE t.content LIKE ?{cond}"
            "  ORDER BY t.ts DESC LIMIT ?"
        )
        params = [f"%{q}%"] + params + [args.limit]
    rows = conn.execute(sql, params).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return
    if not rows:
        print(f"[recall] 无命中: {args.query!r}")
        return
    print(f"[recall] {args.query!r} -> {len(rows)} 条命中")
    for r in rows:
        head = (r["content"] if len(r["content"]) <= 60
                else r["content"][:60] + "…")
        print(f"  [{r['session_id']}#{r['seq']}] ({r['role']}/{r['mode']}) {r['ts']}")
        print(f"      {head}")


def cmd_transcript(args) -> None:
    conn = _conn(args.db)
    sess = conn.execute(
        "SELECT * FROM sessions WHERE session_id=?", (args.session,)
    ).fetchone()
    if not sess:
        print(f"[transcript] 会话不存在: {args.session}")
        return
    print(f"== 会话 {sess['session_id']} | {sess['title']} | kind={sess['kind']} "
          f"| participants={sess['participants']} | created={sess['created_at']}")
    rows = conn.execute(
        "SELECT * FROM turns WHERE session_id=? ORDER BY seq", (args.session,)
    ).fetchall()
    for r in rows:
        tag = r["signal_ref"] or ""
        print(f"  #{r['seq']:>3} [{r['role']:<9}] {r['ts']} {tag}")
        print(f"       {r['content']}")


def cmd_list(args) -> None:
    conn = _conn(args.db)
    rows = conn.execute(
        "SELECT s.session_id, s.kind, s.title, COUNT(t.id) AS turns, s.updated_at"
        "  FROM sessions s LEFT JOIN turns t ON t.session_id = s.session_id"
        " GROUP BY s.session_id ORDER BY s.created_at DESC"
    ).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return
    for r in rows:
        print(f"  {r['session_id']:<24} kind={r['kind']:<6} turns={r['turns']:<4} {r['title']}")


def cmd_stats(args) -> None:
    conn = _conn(args.db)
    n_sess = conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
    n_turn = conn.execute("SELECT COUNT(*) c FROM turns").fetchone()["c"]
    n_fts = conn.execute("SELECT COUNT(*) c FROM turns_fts").fetchone()["c"]
    by_role = conn.execute(
        "SELECT role, COUNT(*) c FROM turns GROUP BY role ORDER BY c DESC"
    ).fetchall()
    print(f"== dialogue_library 统计 ==")
    print(f"  会话数: {n_sess} | 轮次数: {n_turn} | FTS 同步: {n_fts}")
    for r in by_role:
        print(f"  {r['role']:<10} {r['c']}")


def main() -> None:
    p = argparse.ArgumentParser(description="dialogue_library 检索端")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite 路径（默认 data/dialogue.db）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("recall", help="全文检索对话片段")
    sp.add_argument("query")
    sp.add_argument("--session")
    sp.add_argument("--role")
    sp.add_argument("--mode")
    sp.add_argument("--limit", type=int, default=5)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_recall)

    sp = sub.add_parser("transcript", help="回看会话流水")
    sp.add_argument("session")
    sp.set_defaults(fn=cmd_transcript)

    sp = sub.add_parser("list-sessions", help="会话清单")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("stats", help="数据统计")
    sp.set_defaults(fn=cmd_stats)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
