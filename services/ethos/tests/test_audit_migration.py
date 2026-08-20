"""SqliteAuditor 旧版审计表（tenet 结构）自动迁移测试。

覆盖：
1. 空库 → 直接建 ethos 新表结构；
2. tenet 旧表（含 request_id、ts TEXT）→ 迁移为 ethos 结构，历史保留 audit_log_legacy；
3. ts 文本转 unix 秒（REAL），request_id/intent/status/latency_ms/quota_after/detail 并入 meta；
4. 迁移幂等（新结构不再触发）；迁移后新事件正常落库。
"""

from __future__ import annotations

import json
import sqlite3

from ethos.security.auditor import SqliteAuditor

_LEGACY_SCHEMA = """
CREATE TABLE audit_log (
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
"""

_LEGACY_ROW = (
    "2026-08-19 10:30:00",  # ts（文本）
    "req-1",                # request_id
    "user-1",               # user_id
    "pro",                  # tier
    "ask",                  # action
    "ai:ask",               # resource
    "match_jobs",           # intent
    "ok",                   # status
    123,                    # latency_ms
    4,                      # quota_after
    "hello",                # detail
)


def _make_legacy(db_path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO audit_log (ts, request_id, user_id, tier, action, resource, intent, status, latency_ms, quota_after, detail) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        _LEGACY_ROW,
    )
    conn.commit()
    conn.close()


def _ethos_columns(db_path) -> set[str]:
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)")}
    conn.close()
    return cols


def test_fresh_db_creates_ethos_schema(tmp_path) -> None:
    db = tmp_path / "audit.db"
    SqliteAuditor(str(db))
    cols = _ethos_columns(db)
    assert {"ts", "action", "user_id", "tier", "resource", "meta"} <= cols
    assert "request_id" not in cols


def test_legacy_table_migrated_to_ethos_schema(tmp_path) -> None:
    db = tmp_path / "audit.db"
    _make_legacy(db)
    SqliteAuditor(str(db))

    # 新表为 ethos 结构
    assert "request_id" not in _ethos_columns(db)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ts, action, user_id, tier, resource, meta FROM audit_log LIMIT 1"
    ).fetchone()
    legacy_count = conn.execute("SELECT COUNT(*) FROM audit_log_legacy").fetchone()[0]
    conn.close()

    # ts 已转 unix 秒（REAL）
    assert isinstance(row[0], float)
    assert row[0] > 1_700_000_000
    assert row[1] == "ask"
    assert row[2] == "user-1"
    assert row[3] == "pro"
    assert row[4] == "ai:ask"

    # 旧字段并入 meta
    meta = json.loads(row[5])
    assert meta["request_id"] == "req-1"
    assert meta["intent"] == "match_jobs"
    assert meta["status"] == "ok"
    assert meta["latency_ms"] == 123
    assert meta["quota_after"] == 4
    assert meta["detail"] == "hello"

    # 历史保留可溯源
    assert legacy_count == 1


def test_migration_idempotent_and_records_keep_working(tmp_path) -> None:
    db = tmp_path / "audit.db"
    _make_legacy(db)

    # 第一次打开：迁移
    SqliteAuditor(str(db))
    # 第二次打开：新结构，不迁移（legacy 仍是迁移时的 1 行）
    auditor = SqliteAuditor(str(db))

    # 迁移后新事件正常落库
    from ethos.models import AuditEvent, Principal, Tier

    auditor.record(
        AuditEvent(
            ts=1_750_000_000.0,
            action="ask",
            principal=Principal(sub="u-new", tier=Tier.PRO),
            resource="ai:ask",
            meta={"took_ms": 5},
        )
    )

    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    legacy_count = conn.execute("SELECT COUNT(*) FROM audit_log_legacy").fetchone()[0]
    conn.close()
    assert count == 2          # 1 迁移行 + 1 新行
    assert legacy_count == 1   # 未重复迁移
