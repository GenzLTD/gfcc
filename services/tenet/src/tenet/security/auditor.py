"""审计：把 AuditEvent 落盘。SQLite（推荐）+ JSONL + Null 三种实现。

SQLite 默认路径 ~/.tenet/audit.db（双平台自动落用户目录），
可用 TENET_AUDIT_DB 环境变量覆盖。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional, Protocol

from .models import AuditEvent


class Auditor(Protocol):
    def record(self, event: AuditEvent) -> None:
        ...


class NullAuditor:
    """联调用：什么都不落盘。"""

    def record(self, event: AuditEvent) -> None:
        return None


class JsonlAuditor:
    """JSONL 追加写，适合轻量 / 管道消费。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        line = json.dumps(event.__dict__, ensure_ascii=False) + "\n"
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)


class SqliteAuditor:
    """审计日志落 SQLite，带 ts / user / action 索引，可查询可审计。"""

    _DDL = """
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      request_id TEXT,
      user_id TEXT,
      tier TEXT,
      action TEXT,
      resource TEXT,
      intent TEXT,
      status TEXT,
      latency_ms INTEGER,
      quota_after INTEGER,
      detail TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
    CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
    CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _default_audit_db()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(self._DDL)
        self._conn.commit()
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        row = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event.ts)),
            event.request_id,
            event.user_id,
            event.tier,
            event.action,
            event.resource,
            event.intent,
            event.status,
            event.latency_ms,
            event.quota_after,
            event.detail,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log "
                "(ts, request_id, user_id, tier, action, resource, intent, status,"
                " latency_ms, quota_after, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _default_audit_db() -> Path:
    override = _getenv("TENET_AUDIT_DB")
    return Path(override) if override else (Path.home() / ".tenet" / "audit.db")


def _getenv(name: str) -> str:
    import os

    return os.getenv(name) or ""
