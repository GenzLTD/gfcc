"""
szpeter2026 - 数据库管理器
吸收自 Wukong db_manager.py，管理 SQLite 元数据库 + 可选外部数据库连接
"""
import sqlite3
import json
import time
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

from config.settings import config


class DBManager:
    """元数据库管理器 — SQLite 为核心，可选扩展 MySQL/PostgreSQL"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.METADATA_DB
        self._ensure_db()

    def _ensure_db(self):
        """初始化数据库表结构"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    # ===== 文档管理 =====

    def register_document(self, title: str, file_path: str, doc_type: str,
                          file_size: int = 0, metadata: dict | None = None) -> int:
        """注册新文档"""
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO documents (title, file_path, doc_type, file_size, metadata, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (title, file_path, doc_type, file_size, json.dumps(metadata or {}),
                 datetime.now().isoformat())
            )
            conn.commit()
            return cursor.lastrowid

    def update_document_status(self, doc_id: int, status: str, chunk_count: int = 0):
        """更新文档处理状态"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE documents SET status=?, chunk_count=?, processed_at=? WHERE id=?",
                (status, chunk_count, datetime.now().isoformat(), doc_id)
            )
            conn.commit()

    def get_documents(self, status: str | None = None) -> list[dict]:
        """查询文档列表"""
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE status=? ORDER BY created_at DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM documents ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_document(self, doc_id: int) -> dict | None:
        """获取单个文档"""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            return dict(row) if row else None

    def delete_document(self, doc_id: int):
        """删除文档及关联数据"""
        with self._conn() as conn:
            conn.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            conn.commit()

    # ===== 分块管理 =====

    def save_chunks(self, doc_id: int, chunks: list[dict]):
        """批量保存文档分块"""
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO chunks (document_id, chunk_index, content, char_count, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                [(doc_id, c["index"], c["content"], len(c["content"]),
                  json.dumps(c.get("metadata", {})))
                 for c in chunks]
            )
            conn.commit()

    def get_chunks(self, doc_id: int) -> list[dict]:
        """获取文档的所有分块"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE document_id=? ORDER BY chunk_index", (doc_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ===== 查询日志 =====

    def log_query(self, query_text: str, provider: str, response_time_ms: float,
                  chunk_count: int = 0):
        """记录查询日志"""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO query_logs (query_text, provider, response_time_ms, chunk_count, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (query_text, provider, response_time_ms, chunk_count, datetime.now().isoformat())
            )
            conn.commit()

    # ===== 统计 =====

    def get_stats(self) -> dict:
        """获取知识库统计"""
        with self._conn() as conn:
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            doc_done = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE status='completed'").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            total_chars = conn.execute(
                "SELECT COALESCE(SUM(char_count), 0) FROM chunks").fetchone()[0]
            query_count = conn.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
            return {
                "documents_total": doc_count,
                "documents_completed": doc_done,
                "documents_pending": doc_count - doc_done,
                "chunks_total": chunk_count,
                "total_characters": total_chars,
                "queries_total": query_count,
            }

    def get_recent_queries(self, limit: int = 20) -> list[dict]:
        """获取最近查询"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM query_logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def _tokenize(self, text: str) -> list[str]:
        """中文分词 + 提取有意义的检索词"""
        tokens = []
        try:
            import jieba
            words = jieba.lcut(text)
        except ImportError:
            words = text.split()
        for w in words:
            w = w.strip()
            if len(w) > 1:
                tokens.append(w)
        return tokens

    def search_chunks(self, query_text: str, top_k: int = 5) -> list[dict]:
        """SQLite 关键词检索（向量库不可用时的兜底方案）
        
        使用 jieba 中文分词 + SQLite FTS5 全文索引 + LIKE 模糊匹配。
        """
        tokens = self._tokenize(query_text)
        if not tokens:
            return []

        with self._conn() as conn:
            # 确保 FTS5 索引存在
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts 
                USING fts5(content, content=chunks, content_rowid=id)
            """)
            conn.commit()

            results = []
            seen_ids = set()

            # 1. FTS5 全文搜索
            try:
                fts_query = ' OR '.join(f'"{t}"' for t in tokens)
                rows = conn.execute(
                    """SELECT c.id, c.document_id, c.chunk_index, c.content, 
                              c.char_count, c.metadata, d.title as doc_title,
                              rank
                       FROM chunks_fts f
                       JOIN chunks c ON c.id = f.rowid
                       JOIN documents d ON c.document_id = d.id
                       WHERE chunks_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (fts_query, top_k * 2),
                ).fetchall()
                for r in rows:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        match_score = sum(
                            1 for t in tokens if t in r["content"]
                        ) / len(tokens)
                        fts_sim = round(min(0.95, 0.45 + match_score * 0.5), 3)
                        results.append({
                            "id": f"chunk_{r['id']}",
                            "content": r["content"],
                            "metadata": {
                                "source_file": r["doc_title"] or f"doc_{r['document_id']}",
                                "doc_id": r["document_id"],
                                "chunk_index": r["chunk_index"],
                            },
                            "similarity": fts_sim,
                        })
            except Exception:
                pass

            # 2. LIKE 模糊匹配补充（安全参数化）
            if len(results) < top_k:
                conditions = []
                params = []
                for t in tokens:
                    conditions.append("c.content LIKE ?")
                    params.append(f"%{t}%")
                where_clause = " OR ".join(conditions)
                params.append(top_k)
                rows = conn.execute(
                    f"""SELECT c.id, c.document_id, c.chunk_index, c.content,
                               c.char_count, c.metadata, d.title as doc_title
                        FROM chunks c
                        JOIN documents d ON c.document_id = d.id
                        WHERE ({where_clause})
                        ORDER BY c.char_count DESC
                        LIMIT ?""",
                    params,
                ).fetchall()
                for r in rows:
                    if r["id"] not in seen_ids:
                        # 相似度按命中词数比例估算
                        match_score = sum(
                            1 for t in tokens if t in r["content"]
                        ) / len(tokens) * 0.4
                        results.append({
                            "id": f"chunk_{r['id']}",
                            "content": r["content"],
                            "metadata": {
                                "source_file": r["doc_title"] or f"doc_{r['document_id']}",
                                "doc_id": r["document_id"],
                                "chunk_index": r["chunk_index"],
                            },
                            "similarity": round(match_score, 3),
                        })

            return results[:top_k]


# ===== 数据库 Schema =====

SCHEMA_SQL = """
-- 文档表
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    doc_type TEXT NOT NULL,          -- md / pdf / txt
    file_size INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}',      -- JSON: 作者、标签、分类等
    status TEXT DEFAULT 'pending',   -- pending / processing / completed / failed
    chunk_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    processed_at TEXT
);

-- 分块表
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    char_count INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- 查询日志表
CREATE TABLE IF NOT EXISTS query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text TEXT NOT NULL,
    provider TEXT NOT NULL,          -- deepseek / ollama
    response_time_ms REAL DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_time ON query_logs(created_at);
"""
