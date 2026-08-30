"""围坐会务态 SQLite 落盘层（G6：圈 / 共识 / 地板落库）。

施工单「docs/围坐会场_G6圈态落库实施.md」决策①：独立库 data/circle_flow.db
（CIRCLE_FLOW_DB 可覆盖），不进 Dual（memory.db）、不进入场票（circle_invites.db）。
圈表与提案表必须同文件——决策②「ack 达成 + 地板轮转同事务」只能在同库上做。

- 表：circles（含 floor_sub）+ circle_members + proposals + proposal_acks；
  evidence / parties / builder_tags 作 JSON 列；acks 拆表；verified_at 给下一刀 refs 用。
- 多语句写（create_circle / append_ack / verify_and_advance_floor）用
  `with self._connect()` 隐式事务（对标 invites.py 纪律）：事务内任何语句失败
  整个回滚，不会出现「库中已 verified 而地板未轮转」的半态。
- 模块单例 get_store()：CIRCLE_FLOW_PROVIDER（默认跟随 STORE_PROVIDER）为
  sqlite 时启用；stub → None（adapter 纯内存，单测隔离，不碰开发者库）。
  测试用 monkeypatch 置 CIRCLE_FLOW_DB 为临时路径 + _store=None。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "circle_flow.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS circles (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    parent_id    TEXT,
    status       TEXT NOT NULL,
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    dissolved_at TEXT,
    floor_sub    TEXT
);
CREATE TABLE IF NOT EXISTS circle_members (
    circle_id    TEXT NOT NULL,
    sub          TEXT NOT NULL,
    role         TEXT NOT NULL,
    builder_tags TEXT NOT NULL DEFAULT '[]',
    joined_at    TEXT NOT NULL,
    PRIMARY KEY (circle_id, sub)
);
CREATE INDEX IF NOT EXISTS idx_circle_members_circle ON circle_members (circle_id);
CREATE TABLE IF NOT EXISTS proposals (
    id             TEXT PRIMARY KEY,
    circle_id      TEXT NOT NULL,
    subject        TEXT NOT NULL,
    issue_id       TEXT,
    created_by     TEXT NOT NULL,
    status         TEXT NOT NULL,
    score          REAL,
    score_evidence TEXT NOT NULL DEFAULT '[]',
    parties        TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL,
    verified_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_proposals_circle ON proposals (circle_id);
CREATE TABLE IF NOT EXISTS proposal_acks (
    proposal_id TEXT NOT NULL,
    sub         TEXT NOT NULL,
    at          TEXT NOT NULL,
    PRIMARY KEY (proposal_id, sub)
);
CREATE INDEX IF NOT EXISTS idx_proposal_acks_proposal ON proposal_acks (proposal_id);
CREATE TABLE IF NOT EXISTS circle_watchers (
    circle_id   TEXT NOT NULL,
    sub         TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    left_at     TEXT,
    PRIMARY KEY (circle_id, sub)
);
CREATE INDEX IF NOT EXISTS idx_circle_watchers_circle ON circle_watchers (circle_id);
"""

# update_proposal 的 JSON 列（读取时 _jloads 对称还原）
_JSON_COLUMNS = {"parties", "score_evidence"}


def _db_path() -> Path:
    return Path(os.getenv("CIRCLE_FLOW_DB", "").strip() or _DEFAULT_DB)


def _jloads(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


class CircleFlowStore:
    """会务态 store：adapter 只调它，不直接 sqlite3.connect。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db = Path(db_path) if db_path is not None else _db_path()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------ #
    # 写：单语句直写；多语句用 `with self._connect()` 隐式事务
    # ------------------------------------------------------------------ #

    def create_circle(self, circle: Dict[str, Any], organizer: Dict[str, Any]) -> None:
        """建圈 + 首成员（organizer）一个事务。"""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO circles (id, name, parent_id, status, created_by, created_at, "
                "dissolved_at, floor_sub) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    circle["id"],
                    circle["name"],
                    circle.get("parent_id"),
                    circle["status"],
                    circle["created_by"],
                    circle["created_at"],
                    circle.get("dissolved_at"),
                    circle.get("floor_sub"),
                ),
            )
            conn.execute(
                "INSERT INTO circle_members (circle_id, sub, role, builder_tags, joined_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    circle["id"],
                    organizer["sub"],
                    organizer["role"],
                    json.dumps(organizer.get("builder_tags") or []),
                    organizer["joined_at"],
                ),
            )

    def upsert_member(self, circle_id: str, member: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO circle_members (circle_id, sub, role, builder_tags, joined_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    circle_id,
                    member["sub"],
                    member["role"],
                    json.dumps(member.get("builder_tags") or []),
                    member["joined_at"],
                ),
            )

    def remove_member_and_floor(self, circle_id: str, sub: str, floor_sub: Optional[str]) -> None:
        """leave：删成员；若交出地板则同事务更新 floor_sub（§4.2 交接）。"""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM circle_members WHERE circle_id = ? AND sub = ?",
                (circle_id, sub),
            )
            if floor_sub is not None:
                conn.execute(
                    "UPDATE circles SET floor_sub = ? WHERE id = ?",
                    (floor_sub, circle_id),
                )

    def set_floor(self, circle_id: str, floor_sub: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE circles SET floor_sub = ? WHERE id = ?", (floor_sub, circle_id))

    def update_circle_status(self, circle_id: str, status: str, dissolved_at: Optional[str] = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE circles SET status = ?, dissolved_at = ? WHERE id = ?",
                (status, dissolved_at, circle_id),
            )

    def insert_proposal(self, proposal: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO proposals (id, circle_id, subject, issue_id, created_by, status, "
                "score, score_evidence, parties, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal["id"],
                    proposal["circle_id"],
                    proposal["subject"],
                    proposal.get("issue_id"),
                    proposal["created_by"],
                    proposal["status"],
                    proposal.get("score"),
                    json.dumps(proposal.get("score_evidence") or []),
                    json.dumps(proposal.get("parties") or []),
                    proposal["created_at"],
                ),
            )

    def update_proposal(self, proposal_id: str, **fields: Any) -> None:
        """通用字段更新（status / score / score_evidence / issue_id）。JSON 列自动序列化。"""
        if not fields:
            return
        params: Dict[str, Any] = dict(fields)
        for key in _JSON_COLUMNS & params.keys():
            params[key] = json.dumps(params[key] or [])
        cols = ", ".join(f"{k} = ?" for k in params)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE proposals SET {cols} WHERE id = ?",
                (*params.values(), proposal_id),
            )

    def append_ack(self, proposal_id: str, sub: str, at: str, status: str) -> None:
        """非 verified 的 ack：追加一行 + 状态同事务（verified 走 verify_and_advance_floor）。"""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO proposal_acks (proposal_id, sub, at) VALUES (?, ?, ?)",
                (proposal_id, sub, at),
            )
            conn.execute("UPDATE proposals SET status = ? WHERE id = ?", (status, proposal_id))

    def verify_and_advance_floor(
        self,
        proposal_id: str,
        circle_id: str,
        *,
        status: str,
        verified_at: str,
        acks: List[Dict[str, str]],
        floor_sub: Optional[str],
    ) -> None:
        """决策②同事务：proposal verified + acks 全量 + 地板轮转一个 BEGIN。

        floor_sub 为 None（提议人已 leave、地板已在 leave 时交接）时不动 floor_sub，
        只提交 ack/verified。
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE proposals SET status = ?, verified_at = ? WHERE id = ?",
                (status, verified_at, proposal_id),
            )
            conn.execute("DELETE FROM proposal_acks WHERE proposal_id = ?", (proposal_id,))
            for ack in acks:
                conn.execute(
                    "INSERT INTO proposal_acks (proposal_id, sub, at) VALUES (?, ?, ?)",
                    (proposal_id, ack["sub"], ack["at"]),
                )
            if floor_sub is not None:
                conn.execute(
                    "UPDATE circles SET floor_sub = ? WHERE id = ?",
                    (floor_sub, circle_id),
                )

    # ------------------------------------------------------------------ #
    # 读（hydrate 用：JSON 列已还原，形状与内存 dict 一致）
    # ------------------------------------------------------------------ #

    def list_circles(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM circles ORDER BY rowid").fetchall()
            return [dict(r) for r in rows]

    def list_members(self, circle_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sub, role, builder_tags, joined_at FROM circle_members "
                "WHERE circle_id = ? ORDER BY rowid",
                (circle_id,),
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["builder_tags"] = _jloads(item["builder_tags"], [])
                out.append(item)
            return out

    def list_proposals(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM proposals ORDER BY rowid").fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["parties"] = _jloads(item["parties"], [])
                item["score_evidence"] = _jloads(item["score_evidence"], [])
                out.append(item)
            return out

    def list_acks(self, proposal_id: str) -> List[Dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sub, at FROM proposal_acks WHERE proposal_id = ? ORDER BY rowid",
                (proposal_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # 旁观（施工单「围坐会场_旁观在场可见实施.md」§0–§9）
    # ------------------------------------------------------------------ #

    def upsert_watcher(self, circle_id: str, sub: str, observed_at: str) -> None:
        """登记/刷新旁观（决策②⑧）：重复 observe 幂等，刷新时间并清 left_at。"""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO circle_watchers (circle_id, sub, observed_at, left_at) "
                "VALUES (?, ?, ?, NULL) "
                "ON CONFLICT(circle_id, sub) DO UPDATE SET "
                "observed_at = excluded.observed_at, left_at = NULL",
                (circle_id, sub, observed_at),
            )

    def leave_watcher(self, circle_id: str, sub: str) -> None:
        """离开旁观 / join 摘 watcher（决策⑤⑥）：写 left_at，历史旁观行保留。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE circle_watchers SET left_at = ? "
                "WHERE circle_id = ? AND sub = ? AND left_at IS NULL",
                (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()), circle_id, sub),
            )

    def list_watchers(self, circle_id: str) -> List[Dict[str, Any]]:
        """当前在册旁观（left_at IS NULL），按登记顺序。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sub, observed_at FROM circle_watchers "
                "WHERE circle_id = ? AND left_at IS NULL ORDER BY rowid",
                (circle_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_all_watchers(self) -> Dict[str, List[Dict[str, Any]]]:
        """hydrate 用：一次取全部在册旁观，按圈分组（决策③：重启仍可见谁在听）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT circle_id, sub, observed_at FROM circle_watchers "
                "WHERE left_at IS NULL ORDER BY rowid"
            ).fetchall()
            out: Dict[str, List[Dict[str, Any]]] = {}
            for r in rows:
                out.setdefault(r["circle_id"], []).append(
                    {"sub": r["sub"], "observed_at": r["observed_at"]}
                )
            return out


_store: Optional[CircleFlowStore] = None


def get_store() -> Optional[CircleFlowStore]:
    """装配用单例。stub → None（adapter 纯内存，单测隔离，不碰开发者库）。"""
    global _store
    if _store is not None:
        return _store
    provider = (
        os.getenv("CIRCLE_FLOW_PROVIDER", "").strip().lower()
        or os.getenv("STORE_PROVIDER", "stub").strip().lower()
    )
    if provider == "stub":
        return None
    _store = CircleFlowStore(db_path=_db_path())
    return _store
