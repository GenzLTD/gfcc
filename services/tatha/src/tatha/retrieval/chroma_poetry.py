"""Chroma 诗词向量检索（78,656 首全唐诗+宋词）"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

# Chroma 索引路径
CHROMA_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".data" / "chroma" / "poetry_full"

_client: chromadb.PersistentClient | None = None
_collection: Any = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = _client.get_collection("poetry_full")
    return _collection


def search_poems(query: str, n_results: int = 5) -> list[dict]:
    """
    向量检索诗词。
    返回: [{"title": ..., "author": ..., "dynasty": ..., "content": ..., "distance": ...}, ...]
    """
    col = _get_collection()
    results = col.query(query_texts=[query], n_results=n_results)

    poems = []
    if results["documents"] and results["documents"][0]:
        for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
            # doc 格式: "《标题》 作者\n正文..."
            lines = doc.split("\n", 1)
            header = lines[0]
            content = lines[1] if len(lines) > 1 else ""
            poems.append({
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "dynasty": meta.get("dynasty", ""),
                "content": content.strip(),
                "header": header.strip(),
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })
    return poems
