#!/usr/bin/env python3
"""
DemoPeter 知识库 MCP Server — 供 Cursor / Claude Code / ZeroClaw 等 Agent 调用

Cursor 配置示例 (~/.cursor/mcp.json 或项目 .cursor/mcp.json):

{
  "mcpServers": {
    "demopeter-kb": {
      "command": "python",
      "args": ["C:/Users/HUAWEI/DemoPeter/static/src/mcp_server.py"],
      "env": {
        "PYTHONPATH": "C:/Users/HUAWEI/DemoPeter;C:/Users/HUAWEI/DemoPeter/static"
      }
    }
  }
}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import bootstrap_paths  # noqa: F401,E402

from mcp.server.fastmcp import FastMCP

from config.settings import config
from src.kb_service import KnowledgeBaseService
from src.rag_engine import RAGEngine

mcp = FastMCP(
    "DemoPeter Knowledge Base",
    instructions=(
        "Local RAG knowledge base for szpeter2026/DemoPeter. "
        "Use kb_stats before import; kb_search for retrieval-only; "
        "kb_ask for full RAG Q&A; kb_import to ingest documents."
    ),
)

_kb = KnowledgeBaseService()
_rag = RAGEngine()


@mcp.tool()
def kb_stats() -> str:
    """Return knowledge base statistics (documents, chunks, vector store status)."""
    return json.dumps(_kb.stats(), ensure_ascii=False, indent=2)


@mcp.tool()
def kb_search(query: str, top_k: int = 5, threshold: float = 0.7) -> str:
    """Semantic + keyword hybrid search without calling the LLM."""
    result = _rag.search_only(query, top_k=top_k, threshold=threshold)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def kb_ask(query: str, top_k: int = 5, threshold: float = 0.7) -> str:
    """Full RAG query: retrieve context then generate an answer via configured AI."""
    result = _rag.query(query, top_k=top_k, threshold=threshold)
    payload = {
        "query": result.query,
        "answer": result.answer,
        "sources": result.sources,
        "chunk_count": result.chunk_count,
        "retrieval_mode": result.retrieval_mode,
        "response_time_ms": result.response_time_ms,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def kb_import(
    directory: str = "",
    force: bool = False,
    limit: int = 0,
    fused: bool = True,
) -> str:
    """Import documents. Default: fused corpus (科锐国际 + Python数据分析实战)."""
    if fused and not directory:
        summary = _kb.import_fused_corpus(
            force=force,
            limit_per_source=limit if limit > 0 else None,
        )
        return json.dumps(
            {
                "mode": "fused",
                "sources": _kb.list_corpus_sources(),
                "total": summary.total,
                "success": summary.success,
                "skipped": summary.skipped,
                "failed": summary.failed,
                "by_corpus": summary.by_corpus,
                "elapsed_sec": summary.elapsed_sec,
                "errors": summary.errors[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    target = Path(directory) if directory else config.DEFAULT_CORPUS_DIR
    summary = _kb.import_directory(
        target,
        force=force,
        limit=limit if limit > 0 else None,
    )
    return json.dumps(
        {
            "directory": str(target),
            "total": summary.total,
            "success": summary.success,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "elapsed_sec": summary.elapsed_sec,
            "docs_per_sec": summary.docs_per_sec,
            "errors": summary.errors[:10],
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()
