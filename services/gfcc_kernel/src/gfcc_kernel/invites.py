"""邀请码 SQLite 落盘层（独立库文件 data/circle_invites.db）。

设计（对齐施工单 §4）：
- 只存 code_hash（SHA-256 hex）与 sub/exp/兑换时间，库泄漏不能直接兑换。
- 兑换码 16 位 Crockford Base32（去 0O1lI 易混字符），10 bytes ≈ 80 bit 熵。
- 同 sub 再签发：作废（DELETE）未兑换旧码再写新码——避免一人多条有效链；
  旧码 redeem 视为未知（404）。测试按此写死。
- redeem 四态：200 有效兑换 / 400 非法格式 / 404 未知或过期 / 410 已兑换。
  过期码语义 = 未知码（404），测试写死。

库路径：默认内核根 data/circle_invites.db；环境变量 CIRCLE_INVITES_DB 可覆盖
（本地联调/测试用临时库，避免污染真实数据）。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional, Tuple

# Crockford Base32：去 0O1lI（易混），留 32 字符
_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CODE_LEN = 16  # 10 bytes = 80 bit = 16 chars × 5 bit

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "circle_invites.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS circle_invites (
    code_hash    TEXT PRIMARY KEY,
    sub          TEXT NOT NULL,
    exp          INTEGER NOT NULL,
    redeemed_at  INTEGER,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_circle_invites_sub ON circle_invites (sub);
"""


def _db_path() -> Path:
    return Path(os.getenv("CIRCLE_INVITES_DB", str(_DEFAULT_DB)))


def generate_code() -> str:
    """16 位 Crockford Base32 兑换码（secrets 真随机）。"""
    n = int.from_bytes(secrets.token_bytes(10), "big")
    chars = [_CODE_ALPHABET[(n >> (5 * (15 - i))) & 31] for i in range(_CODE_LEN)]
    return "".join(chars)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def is_valid_code(code: str) -> bool:
    """严格格式：16 位且全部落在 Crockford 字符集（防 0O/1Il 混用）。"""
    return len(code) == _CODE_LEN and all(c in _CODE_ALPHABET for c in code)


class InviteStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db = Path(db_path) if db_path is not None else _db_path()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def issue(self, sub: str, code: str, exp: int) -> None:
        """签发：作废该 sub 未兑换旧码，再写新码。exp 为 epoch 秒。"""
        now = int(time.time())
        code_hash = _hash_code(code)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM circle_invites WHERE sub = ? AND redeemed_at IS NULL",
                (sub,),
            )
            conn.execute(
                "INSERT INTO circle_invites (code_hash, sub, exp, created_at) VALUES (?, ?, ?, ?)",
                (code_hash, sub, int(exp), now),
            )

    def redeem(self, code: str) -> Tuple[str, Optional[str], Optional[int]]:
        """兑换：返回 (status, sub, exp)。

        status: ok=成功（已标记已兑换） / missing=未知或过期 / used=已兑换。
        """
        now = int(time.time())
        code_hash = _hash_code(code)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sub, exp, redeemed_at FROM circle_invites WHERE code_hash = ?",
                (code_hash,),
            ).fetchone()
            if row is None:
                return ("missing", None, None)
            if row["redeemed_at"] is not None:
                return ("used", None, None)
            if int(row["exp"]) < now:
                # 过期 = 未知（404），与施工单 §4 测试口径一致
                return ("missing", None, None)
            conn.execute(
                "UPDATE circle_invites SET redeemed_at = ? WHERE code_hash = ?",
                (now, code_hash),
            )
            return ("ok", row["sub"], int(row["exp"]))


_store: Optional[InviteStore] = None


def get_store() -> InviteStore:
    """模块级单例；测试用 monkeypatch 替换 invites._store 指向临时库。"""
    global _store
    if _store is None:
        _store = InviteStore()
    return _store
