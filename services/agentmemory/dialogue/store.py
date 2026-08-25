#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dialogue_library · store.py —— 对话库（情景记忆子集）写入端
位置: E:\\CorpusPipeline\\dialogue_library

用法:
  python store.py init                                  # 建库（幂等）
  python store.py session --id demo-001 --kind collab \
      --title "G3 验收对话" --participants "windows,mac,ai"
  python store.py append --session demo-001 --role user \
      --content "G3 真信号落库了吗？" --mode 协作 --signal THOMAS:5211:v1.0.0
  python store.py append --session demo-001 --role ai \
      --content "已落库，4 处契约校验通过。" --channel gfcc
  python store.py import-jsonl --file export.jsonl     # 批量导入
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")
DEFAULT_DB = os.path.join(BASE_DIR, "data", "dialogue.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_init(args) -> None:
    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()
    conn = _conn(args.db)
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print(f"[init] dialogue.db ready at {args.db}")


def cmd_session(args) -> None:
    conn = _conn(args.db)
    now = _now()
    conn.execute(
        "INSERT OR REPLACE INTO sessions(session_id, kind, title, participants, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?)",
        (args.id, args.kind, args.title, args.participants, now, now),
    )
    conn.commit()
    conn.close()
    print(f"[session] {args.id} kind={args.kind} title={args.title!r}")


def cmd_append(args) -> None:
    conn = _conn(args.db)
    row = conn.execute(
        "SELECT MAX(seq) AS m FROM turns WHERE session_id=?", (args.session,)
    ).fetchone()
    seq = (row["m"] or 0) + 1
    ts = args.ts or _now()
    conn.execute(
        "INSERT INTO turns(session_id, seq, role, content, mode, signal_ref, channel, ts)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (args.session, seq, args.role, args.content, args.mode, args.signal,
         args.channel, ts),
    )
    conn.execute(
        "UPDATE sessions SET updated_at=? WHERE session_id=?", (ts, args.session)
    )
    conn.commit()
    conn.close()
    print(f"[append] {args.session} seq={seq} role={args.role} ts={ts}")


def cmd_import_jsonl(args) -> None:
    """jsonl 每行:
       {"kind":"session","session_id":"s1","kind":"collab","title":"...","participants":"..."}
       {"kind":"turn","session_id":"s1","role":"user","content":"...","mode":"协作",
        "signal":"...","channel":"gfcc","ts":"2026-08-25T00:00:00+00:00"}
    """
    conn = _conn(args.db)
    now = _now()
    imported = 0
    with open(args.file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("kind") == "session":
                conn.execute(
                    "INSERT OR REPLACE INTO sessions(session_id,kind,title,participants,created_at,updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (rec["session_id"], rec.get("session_kind", "collab"), rec.get("title"),
                     rec.get("participants"), rec.get("ts", now), now),
                )
            elif rec.get("kind") == "turn":
                sid = rec["session_id"]
                row = conn.execute(
                    "SELECT MAX(seq) AS m FROM turns WHERE session_id=?", (sid,)
                ).fetchone()
                seq = (row["m"] or 0) + 1
                ts = rec.get("ts", now)
                conn.execute(
                    "INSERT INTO turns(session_id,seq,role,content,mode,signal_ref,channel,ts)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (sid, seq, rec.get("role", "user"), rec["content"],
                     rec.get("mode"), rec.get("signal"), rec.get("channel", "manual"), ts),
                )
                conn.execute(
                    "UPDATE sessions SET updated_at=? WHERE session_id=?", (ts, sid)
                )
            else:
                continue
            imported += 1
    conn.commit()
    conn.close()
    print(f"[import] {imported} records from {args.file}")


def main() -> None:
    p = argparse.ArgumentParser(description="dialogue_library 写入端")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite 路径（默认 data/dialogue.db）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="建库（幂等）")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("session", help="新建/更新会话")
    sp.add_argument("--id", required=True)
    sp.add_argument("--kind", default="collab", choices=["collab", "coach"])
    sp.add_argument("--title")
    sp.add_argument("--participants")
    sp.set_defaults(fn=cmd_session)

    sp = sub.add_parser("append", help="追加一条对话轮次")
    sp.add_argument("--session", required=True)
    sp.add_argument("--role", default="user", choices=["user", "assistant", "ai", "system"])
    sp.add_argument("--content", required=True)
    sp.add_argument("--mode", help="协作 / 教练")
    sp.add_argument("--signal", help="GFCC 契约信号，如 THOMAS:5211:v1.0.0")
    sp.add_argument("--channel", default="manual", help="gfcc / demopeter / agentmemory / manual")
    sp.add_argument("--ts", help="ISO8601，缺省为当前 UTC")
    sp.set_defaults(fn=cmd_append)

    sp = sub.add_parser("import-jsonl", help="批量导入 jsonl")
    sp.add_argument("--file", required=True)
    sp.set_defaults(fn=cmd_import_jsonl)

    args = p.parse_args()
    try:
        args.fn(args)
    except sqlite3.Error as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
