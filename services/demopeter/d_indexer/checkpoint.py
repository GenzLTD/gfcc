"""
checkpoint - D 盘扫描断点管理器

核心设计：
1. 目录级断点：每处理完一个目录就保存（可靠，不受文件系统排序影响）
2. 本地文件索引缓存：存 (path, size, mtime, fingerprint)，比 ChromaDB get() 快 100 倍
3. 崩溃恢复：启动时检测 in_progress 状态，跳过已完成的目录

断点粒度：
- 项目根目录级别：completed / in_progress / pending
- 目录级别：completed_dirs 列表，每完成一个目录立即保存
- 文件级别：indexed_files_cache 用于快速跳过未变更文件
"""
import json
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config.logging_config import get_logger
from config.settings import config as app_config

logger = get_logger("checkpoint")


# ===== SQL Schema =====
CHECKPOINT_SCHEMA = """
-- 扫描断点表（每个项目根目录一条记录）
CREATE TABLE IF NOT EXISTS scan_checkpoints (
    project_root    TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | completed | failed
    completed_dirs  TEXT DEFAULT '[]',                 -- JSON 数组，已完整处理过的目录路径
    current_dir     TEXT,                              -- 当前正在处理的目录
    current_file    TEXT,                              -- 当前正在处理的文件（用于断点日志）
    files_scanned   INTEGER DEFAULT 0,
    files_indexed   INTEGER DEFAULT 0,                 -- 实际写入 Chroma 的文件数
    chunks_indexed  INTEGER DEFAULT 0,
    started_at      TEXT,
    updated_at      TEXT,
    completed_at    TEXT,
    error_message   TEXT
);

-- 本地文件索引缓存（快速跳过未变更文件，避免查 ChromaDB）
CREATE TABLE IF NOT EXISTS indexed_files_cache (
    file_path       TEXT PRIMARY KEY,
    project_root    TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    last_modified   REAL NOT NULL,
    fingerprint     TEXT NOT NULL,
    chunks_count    INTEGER DEFAULT 0,
    indexed_at      TEXT NOT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_ifc_project ON indexed_files_cache(project_root);
CREATE INDEX IF NOT EXISTS idx_ifc_mtime ON indexed_files_cache(file_path, size_bytes, last_modified);
"""


@dataclass
class ScanProgress:
    """扫描进度快照"""
    project_root: str
    status: str
    completed_dirs: list = field(default_factory=list)
    current_dir: str = ""
    current_file: str = ""
    files_scanned: int = 0
    files_indexed: int = 0
    chunks_indexed: int = 0
    total_files: int = 0  # 估算的总文件数
    started_at: str = ""
    updated_at: str = ""

    @property
    def completion_pct(self) -> float:
        if self.total_files == 0:
            return 0.0
        return min(100.0, self.files_scanned / self.total_files * 100)


class ScanCheckpoint:
    """断点管理器 —— 基于 SQLite 持久化扫描状态"""

    # 自动保存间隔
    AUTO_SAVE_EVERY_N_FILES = 50       # 每处理 50 个文件保存一次
    AUTO_SAVE_EVERY_N_SECONDS = 30     # 或每 30 秒保存一次

    def __init__(self, db_path: str = None):
        self.db_path = db_path or app_config.METADATA_DB
        self._last_save_time = 0.0
        self._files_since_save = 0
        self._init_db()

    def _init_db(self):
        """初始化断点表结构"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(CHECKPOINT_SCHEMA)
            conn.commit()
        logger.debug("断点表已就绪: %s", self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    # ===== 断点生命周期 =====

    def start_scan(self, project_root: str) -> bool:
        """
        开始扫描某个项目根目录。
        Returns: True 表示这是新扫描，False 表示已完成（跳过）
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM scan_checkpoints WHERE project_root=?",
                (project_root,)
            ).fetchone()

            if row and row["status"] == "completed":
                logger.info("项目已完成，跳过: %s", project_root)
                return False

            now = datetime.now().isoformat()
            if row and row["status"] == "in_progress":
                logger.info("恢复未完成的扫描: %s", project_root)
                conn.execute(
                    """UPDATE scan_checkpoints 
                       SET updated_at=? 
                       WHERE project_root=?""",
                    (now, project_root)
                )
            else:
                # 新建或重置
                conn.execute(
                    """INSERT OR REPLACE INTO scan_checkpoints 
                       (project_root, status, completed_dirs, files_scanned, 
                        files_indexed, chunks_indexed, started_at, updated_at)
                       VALUES (?, 'in_progress', '[]', 0, 0, 0, ?, ?)""",
                    (project_root, now, now)
                )
            conn.commit()

        self._last_save_time = time.time()
        self._files_since_save = 0
        return True

    def get_completed_dirs(self, project_root: str) -> set:
        """获取已完成目录集合"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT completed_dirs FROM scan_checkpoints WHERE project_root=?",
                (project_root,)
            ).fetchone()
            if row:
                try:
                    return set(json.loads(row["completed_dirs"]))
                except (json.JSONDecodeError, TypeError):
                    pass
        return set()

    def save_progress(self, project_root: str, completed_dir: str = None,
                       current_dir: str = None, current_file: str = None,
                       files_scanned: int = None, files_indexed: int = None,
                       chunks_indexed: int = None):
        """
        保存扫描进度的增量更新。
        当 completed_dir 指定时，将其加入已完成目录列表。
        """
        now = datetime.now().isoformat()
        with self._conn() as conn:
            if completed_dir:
                # 追加到已完成目录列表
                row = conn.execute(
                    "SELECT completed_dirs FROM scan_checkpoints WHERE project_root=?",
                    (project_root,)
                ).fetchone()
                completed = set()
                if row:
                    try:
                        completed = set(json.loads(row["completed_dirs"]))
                    except (json.JSONDecodeError, TypeError):
                        pass
                completed.add(completed_dir)
                completed_dirs_json = json.dumps(sorted(completed))
            else:
                completed_dirs_json = None

            # 构建 SET 子句
            sets = ["updated_at=?"]
            params = [now]

            if completed_dirs_json is not None:
                sets.append("completed_dirs=?")
                params.append(completed_dirs_json)

            if current_dir is not None:
                sets.append("current_dir=?")
                params.append(current_dir)

            if current_file is not None:
                sets.append("current_file=?")
                params.append(current_file)

            if files_scanned is not None:
                sets.append("files_scanned=?")
                params.append(files_scanned)

            if files_indexed is not None:
                sets.append("files_indexed=?")
                params.append(files_indexed)

            if chunks_indexed is not None:
                sets.append("chunks_indexed=?")
                params.append(chunks_indexed)

            params.append(project_root)
            conn.execute(
                f"UPDATE scan_checkpoints SET {', '.join(sets)} WHERE project_root=?",
                params
            )
            conn.commit()

        self._files_since_save = 0
        self._last_save_time = time.time()

    def maybe_save(self, project_root: str, force: bool = False, **kwargs) -> bool:
        """
        按时间/文件数量阈值自动决定是否保存。
        Returns: True 如果执行了保存
        """
        self._files_since_save += 1
        elapsed = time.time() - self._last_save_time

        if force or \
           self._files_since_save >= self.AUTO_SAVE_EVERY_N_FILES or \
           elapsed >= self.AUTO_SAVE_EVERY_N_SECONDS:
            self.save_progress(project_root, **kwargs)
            return True
        return False

    def complete_scan(self, project_root: str, files_scanned: int = 0,
                       files_indexed: int = 0, chunks_indexed: int = 0):
        """标记项目扫描完成"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """UPDATE scan_checkpoints 
                   SET status='completed', files_scanned=?, files_indexed=?,
                       chunks_indexed=?, completed_at=?, updated_at=?
                   WHERE project_root=?""",
                (files_scanned, files_indexed, chunks_indexed, now, now, project_root)
            )
            conn.commit()
        logger.info("项目扫描完成: %s (%d 文件, %d chunks)", 
                     project_root, files_scanned, chunks_indexed)

    def fail_scan(self, project_root: str, error: str):
        """标记扫描失败"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """UPDATE scan_checkpoints 
                   SET status='failed', error_message=?, updated_at=?
                   WHERE project_root=?""",
                (error, now, project_root)
            )
            conn.commit()

    def get_progress(self, project_root: str) -> Optional[ScanProgress]:
        """读取扫描进度"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM scan_checkpoints WHERE project_root=?",
                (project_root,)
            ).fetchone()
            if not row:
                return None
            completed_dirs = []
            try:
                completed_dirs = json.loads(row["completed_dirs"] or "[]")
            except (json.JSONDecodeError, TypeError):
                pass
            return ScanProgress(
                project_root=row["project_root"],
                status=row["status"],
                completed_dirs=completed_dirs,
                current_dir=row["current_dir"] or "",
                current_file=row["current_file"] or "",
                files_scanned=row["files_scanned"] or 0,
                files_indexed=row["files_indexed"] or 0,
                chunks_indexed=row["chunks_indexed"] or 0,
                started_at=row["started_at"] or "",
                updated_at=row["updated_at"] or "",
            )

    def get_all_progress(self) -> list[ScanProgress]:
        """获取所有项目的扫描进度"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scan_checkpoints ORDER BY started_at DESC"
            ).fetchall()
            results = []
            for row in rows:
                completed_dirs = []
                try:
                    completed_dirs = json.loads(row["completed_dirs"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    pass
                results.append(ScanProgress(
                    project_root=row["project_root"],
                    status=row["status"],
                    completed_dirs=completed_dirs,
                    current_dir=row["current_dir"] or "",
                    current_file=row["current_file"] or "",
                    files_scanned=row["files_scanned"] or 0,
                    files_indexed=row["files_indexed"] or 0,
                    chunks_indexed=row["chunks_indexed"] or 0,
                    started_at=row["started_at"] or "",
                    updated_at=row["updated_at"] or "",
                ))
            return results

    def has_incomplete(self) -> bool:
        """是否有未完成的扫描"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM scan_checkpoints WHERE status='in_progress'"
            ).fetchone()
            return row["cnt"] > 0

    def reset_project(self, project_root: str):
        """重置某个项目的断点"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE scan_checkpoints SET status='pending', completed_dirs='[]', "
                "current_dir=NULL, current_file=NULL, error_message=NULL WHERE project_root=?",
                (project_root,)
            )
            conn.commit()

    def reset_all(self):
        """重置所有断点"""
        with self._conn() as conn:
            conn.execute("DELETE FROM scan_checkpoints")
            conn.commit()

    # ===== 文件索引缓存 =====

    def lookup_file_cache(self, file_path: str, size_bytes: int, 
                           last_modified: float) -> Optional[str]:
        """
        快速查找文件是否已索引且未变更。
        同时匹配 path + size + mtime，三个字段全匹配才认为未变更。
        
        Returns: fingerprint 如果命中缓存，None 表示需要重新索引
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT fingerprint FROM indexed_files_cache 
                   WHERE file_path=? AND size_bytes=? AND last_modified=?""",
                (file_path, size_bytes, last_modified)
            ).fetchone()
            return row["fingerprint"] if row else None

    def cache_file(self, file_path: str, project_root: str, size_bytes: int,
                    last_modified: float, fingerprint: str, chunks_count: int):
        """缓存已索引的文件信息"""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO indexed_files_cache 
                   (file_path, project_root, size_bytes, last_modified, 
                    fingerprint, chunks_count, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (file_path, project_root, size_bytes, last_modified,
                 fingerprint, chunks_count, datetime.now().isoformat())
            )
            conn.commit()

    def delete_file_cache(self, file_path: str):
        """删除某个文件的缓存（文件被删除或需要强制重索引）"""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM indexed_files_cache WHERE file_path=?",
                (file_path,)
            )
            conn.commit()

    def delete_project_cache(self, project_root: str):
        """清空某个项目的所有文件缓存"""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM indexed_files_cache WHERE project_root=?",
                (project_root,)
            )
            conn.commit()

    def get_cache_stats(self) -> dict:
        """获取缓存统计"""
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM indexed_files_cache"
            ).fetchone()[0]
            by_project = conn.execute(
                """SELECT project_root, COUNT(*) as cnt 
                   FROM indexed_files_cache 
                   GROUP BY project_root 
                   ORDER BY cnt DESC"""
            ).fetchall()
            return {
                "total_cached_files": total,
                "by_project": [{"project": r["project_root"], "files": r["cnt"]} 
                               for r in by_project],
            }
