"""审计器：本地落库 + 可选上报。

ethos 定位"本地审计（可选上报）"：
- Auditor 默认把事件写本地（SQLite 或 JSONL），零依赖。
- 可挂载 AuditReporter（上报协议），每次事件后在本地落库之外异步上报中心。
- NullAuditor 用于关闭审计（如纯联调）。

上报策略（reporter 与本地落库互不阻塞）：
- 本地落库是同步、强一致的（快速、可靠）。
- 上报是尽力而为（best-effort），失败不抛、不影响主流程。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

from ..models import AuditEvent


def _legacy_ts_to_float(value: Any) -> float:
    """tenet 旧版审计表 ts 是 'YYYY-MM-DD HH:MM:SS' 文本，转 ethos 的 unix 秒（REAL）。

    依次尝试常见格式；数字直通；解析失败回退当前时间（保证迁移不丢行）。
    """
    if value is None or value == "":
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(text)
    except ValueError:
        return time.time()


class AuditReporter(Protocol):
    """上报协议：把审计事件发给中心（HTTP/日志/消息队列）。"""

    def report(self, event: AuditEvent) -> None: ...


# --------------------------------------------------------------------------- #
# 本地后端
# --------------------------------------------------------------------------- #

class SqliteAuditor:
    """SQLite 本地审计：表 audit_log(id, ts, action, user_id, tier, resource, meta)。"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS audit_log (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        ts       REAL    NOT NULL,
        action   TEXT    NOT NULL,
        user_id  TEXT    DEFAULT '',
        tier     TEXT    DEFAULT '',
        resource TEXT    DEFAULT '',
        meta     TEXT    DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log (user_id, ts);
    CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log (action, ts);
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._local = threading.local()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=5.0)
            self._local.conn = conn
        return conn

    def _init(self) -> None:
        conn = self._conn()
        cols = self._table_columns(conn, "audit_log")
        if cols is None:
            conn.executescript(self.SCHEMA)
        elif "request_id" in cols:
            # tenet 旧版审计表（含 request_id 列）→ 迁移为 ethos 结构，历史保留 audit_log_legacy
            self._migrate_legacy_table(conn)
        conn.commit()

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> Optional[set[str]]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r[1] for r in rows} if rows else None

    def _migrate_legacy_table(self, conn: sqlite3.Connection) -> None:
        """把 tenet 旧版 audit_log 迁移为 ethos 结构，原始表改名 audit_log_legacy 保留。

        映射（ethos 表为唯一规范，多余字段并入 meta 防丢信息）：
        ts TEXT（'YYYY-MM-DD HH:MM:SS'）→ ts REAL（unix 秒）；
        request_id/intent/status/latency_ms/quota_after/detail → meta JSON。
        幂等：ethos 新表无 request_id 列，不会触发二次迁移。
        """
        cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
        pick = [
            c
            for c in (
                "ts", "request_id", "user_id", "tier", "action", "resource",
                "intent", "status", "latency_ms", "quota_after", "detail",
            )
            if c in cols
        ]
        rows = conn.execute(f"SELECT {', '.join(pick)} FROM audit_log").fetchall()
        conn.execute("ALTER TABLE audit_log RENAME TO audit_log_legacy")
        conn.executescript(self.SCHEMA)
        meta_fields = ("request_id", "intent", "status", "latency_ms", "quota_after", "detail")
        for row in rows:
            rec = dict(zip(pick, row))
            meta = {k: rec[k] for k in meta_fields if rec.get(k) not in (None, "")}
            conn.execute(
                "INSERT INTO audit_log (ts, action, user_id, tier, resource, meta) VALUES (?,?,?,?,?,?)",
                (
                    _legacy_ts_to_float(rec.get("ts")),
                    rec.get("action") or "",
                    rec.get("user_id") or "",
                    rec.get("tier") or "",
                    rec.get("resource") or "",
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
        conn.commit()

    def record(self, event: AuditEvent) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO audit_log (ts, action, user_id, tier, resource, meta) VALUES (?,?,?,?,?,?)",
            (
                event.ts,
                event.action,
                event.principal.user_id if event.principal else "",
                event.principal.tier.value if event.principal else "",
                event.resource,
                json.dumps(event.meta, ensure_ascii=False),
            ),
        )
        conn.commit()

    def recent(self, limit: int = 50, action: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT ts, action, user_id, tier, resource, meta FROM audit_log"
        params: list[Any] = []
        if action:
            sql += " WHERE action = ?"
            params.append(action)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn().execute(sql, params).fetchall()
        return [
            {
                "ts": r[0],
                "action": r[1],
                "user_id": r[2],
                "tier": r[3],
                "resource": r[4],
                "meta": json.loads(r[5]) if r[5] else {},
            }
            for r in rows
        ]


class JsonlAuditor:
    """JSONL 文件审计：每事件一行 JSON，适合运维 grep / 后续转储。"""

    def __init__(self, path: str) -> None:
        self._path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


class NullAuditor:
    """关闭审计。"""

    def record(self, event: AuditEvent) -> None:  # pragma: no cover
        pass


# --------------------------------------------------------------------------- #
# 门面：Auditor（本地 + 可选上报）
# --------------------------------------------------------------------------- #

class Auditor:
    """审计门面：本地落库（同步）+ 可选上报（尽力而为）。

    usage:
        audit = Auditor(SqliteAuditor("logs/audit.db"))
        audit.reporter = HttpReporter("http://audit-center")
        audit.record(action="rag.query", principal=p, resource="ask")
    """

    def __init__(self, backend: Optional[Any] = None, reporter: Optional[AuditReporter] = None) -> None:
        self._backend = backend or NullAuditor()
        self.reporter = reporter  # 可在运行时替换/关闭（置 None 即只本地）

    def record(
        self,
        action: str,
        principal: Any = None,
        resource: str = "",
        meta: Optional[Dict[str, Any]] = None,
        event: Optional[AuditEvent] = None,
    ) -> AuditEvent:
        ev = event or AuditEvent(action=action, principal=principal, resource=resource, meta=meta)
        try:
            self._backend.record(ev)  # 本地强一致
        except Exception:
            pass  # 本地失败不阻断业务（审计是旁路）
        if self.reporter is not None:
            try:
                self.reporter.report(ev)  # 上报尽力而为
            except Exception:
                pass
        return ev

    @property
    def backend(self) -> Any:
        return self._backend
