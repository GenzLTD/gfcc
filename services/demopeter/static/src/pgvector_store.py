"""
szpeter2026 — pgvector 向量存储
PostgreSQL + pgvector 作为 Chroma 的替代/补充方案
Embedding 由 Ollama nomic-embed-text 模型生成
"""
import json
import time
from typing import Optional

import requests

from config.settings import config


class PgvectorStore:
    """pgvector 向量数据库 — 嵌入生成 + 存储 + 搜索"""

    def __init__(self):
        self._conn = None
        self._available = False
        self._init_connection()

    def _init_connection(self):
        """初始化 PostgreSQL 连接"""
        if not config.PGVECTOR_ENABLED:
            return
        try:
            import psycopg2
            import psycopg2.extras
            self._conn = psycopg2.connect(
                host=config.PGVECTOR_HOST,
                port=config.PGVECTOR_PORT,
                user=config.PGVECTOR_USER,
                password=config.PGVECTOR_PASSWORD,
                database=config.PGVECTOR_DATABASE,
            )
            self._conn.autocommit = False
            self._available = True
        except ImportError:
            self._available = False
        except Exception:
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    # ===== Embedding 生成 =====

    def _embed(self, text: str) -> list[float]:
        """通过 Ollama 生成文本向量"""
        resp = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/embeddings",
            json={"model": config.OLLAMA_EMBEDDING_MODEL, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量"""
        embeddings = []
        for i, text in enumerate(texts):
            vec = self._embed(text)
            embeddings.append(vec)
            if (i + 1) % 50 == 0:
                time.sleep(0.1)  # 限速
        return embeddings

    # ===== 向量写入 =====

    def add_documents(self, doc_id: int, chunks: list[dict]) -> int:
        """批量写入分块向量（先确保 documents 表有记录）"""
        if not self.is_available:
            return 0

        texts = [c["content"] for c in chunks]
        try:
            embeddings = self._embed_batch(texts)
        except Exception as e:
            print(f"[pgvector] Embedding 失败 (Ollama 不可用?): {e}")
            return 0

        with self._conn.cursor() as cur:
            # 确保 documents 表有对应的记录（否则 search 时 JOIN 会失败）
            cur.execute(
                """INSERT INTO documents (id, title, file_path, doc_type, file_size, status, chunk_count)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (doc_id, str(doc_id), "", "md", 0, "completed", len(chunks)),
            )

            for i, chunk in enumerate(chunks):
                cur.execute(
                    """INSERT INTO chunks (document_id, chunk_index, content, char_count, embedding, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (
                        doc_id,
                        chunk["index"],
                        chunk["content"],
                        len(chunk["content"]),
                        embeddings[i],
                        json.dumps(chunk.get("metadata", {})),
                    ),
                )
            self._conn.commit()

        return len(embeddings)

    # ===== 向量搜索 =====

    def search(self, query: str, top_k: int = 5,
               threshold: float = 0.5) -> list[dict]:
        """余弦相似度搜索"""
        if not self.is_available:
            return []

        try:
            query_vec = self._embed(query)
        except Exception:
            return []

        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT c.id, c.content, c.chunk_index, c.metadata,
                          1 - (c.embedding <=> %s::vector) AS similarity,
                          d.title, d.file_path
                   FROM chunks c
                   JOIN documents d ON d.id = c.document_id
                   WHERE 1 - (c.embedding <=> %s::vector) >= %s
                   ORDER BY c.embedding <=> %s::vector
                   LIMIT %s""",
                (query_vec, query_vec, threshold, query_vec, top_k),
            )
            rows = cur.fetchall()

        return [
            {
                "id": f"pgvec_{r[0]}",
                "content": r[1],
                "chunk_index": r[2],
                "metadata": {**r[3], "source_file": r[5] or "", "source_path": r[6] or ""},
                "similarity": round(r[4], 4),
            }
            for r in rows
        ]

    def delete_document(self, doc_id: int):
        """删除文档的所有向量"""
        if not self.is_available:
            return
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
            self._conn.commit()

    def get_stats(self) -> dict:
        """获取统计"""
        if not self.is_available:
            return {"available": False}
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM chunks")
                chunks = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL")
                vectors = cur.fetchone()[0]
            return {
                "available": True,
                "mode": "pgvector",
                "host": f"{config.PGVECTOR_HOST}:{config.PGVECTOR_PORT}",
                "total_chunks": chunks,
                "total_vectors": vectors,
                "embedding_model": config.OLLAMA_EMBEDDING_MODEL,
                "dimensions": config.PGVECTOR_EMBEDDING_DIM,
            }
        except Exception as e:
            return {"available": True, "mode": "pgvector", "error": str(e)[:100]}

    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
