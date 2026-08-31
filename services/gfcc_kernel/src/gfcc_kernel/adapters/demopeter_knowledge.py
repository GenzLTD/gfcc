"""L3 厂商适配器：knowledge.demopeter —— RAG 知识检索工具（非一等端口）。

对齐 contracts/registry.v1.json optional_adapters["knowledge.demopeter"]：
- "RAG sample. Not a 格契 first-class port. Insight/observe is memory.observe,
  not this adapter."
- mode: profile.demo（默认模式禁止，FORBIDDEN_IN_DEFAULT_TOOLS）。

红线：
- 不进 /v1/ask 信封的 port；独立工具入口 /v1/knowledge/query（对标 signal-ingest）；
- 输出只作 contribution/参考证据，不写 identity/memory 主存；
- 洞察（insight/observe）一律走 memory.observe，不经本适配器。

远端真实 API（demopeter 5220）：
- POST /api/rag/query  {"query","top_k","threshold"} → answer+sources+retrieval_mode
- GET  /api/d-index/search?q=   → D 盘代码/文档索引语义检索
- GET  /api/health/config       → 探测
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from ..envelope import PortOpResult

logger = logging.getLogger("gfcc_kernel")


class DemoPeterKnowledge:
    """demopeter 知识库 RAG 工具适配器。"""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 15.0) -> None:
        self._base = (base_url or os.getenv("DEMOPETER_URL", "http://127.0.0.1:5220")).rstrip("/")
        self._timeout = timeout
        self._available: Optional[bool] = None
        self._checked_at: float = 0.0
        self._ttl = 5.0

    # ------------------------------------------------------------------ #
    # 探测 / 传输（集中 _post/_get，测试可 monkeypatch）
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        now = time.monotonic()
        if self._available is not None and (now - self._checked_at) < self._ttl:
            return self._available
        ok = False
        try:
            with urllib.request.urlopen(f"{self._base}/api/health/config", timeout=1.5) as resp:
                ok = resp.status == 200
        except Exception:  # noqa: BLE001
            ok = False
        self._available = ok
        self._checked_at = now
        return ok

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        req = urllib.request.Request(
            f"{self._base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, path: str, query: Dict[str, Any]) -> Dict[str, Any]:
        qs = urllib.parse.urlencode(query)
        with urllib.request.urlopen(f"{self._base}{path}?{qs}", timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #

    def query(self, question: str, top_k: int = 5, threshold: float = 0.5) -> PortOpResult:
        """RAG 问答。返回 PortOpResult，data 含 answer/sources/retrieval_mode 等。"""
        if not question or not question.strip():
            return PortOpResult(ok=False, error="question is required")
        try:
            data = self._post("/api/rag/query", {
                "query": question.strip(),
                "top_k": int(top_k),
                "threshold": float(threshold),
            })
        except urllib.error.HTTPError as exc:
            return PortOpResult(ok=False, error=f"demopeter HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge.demopeter: query failed: %s", exc)
            return PortOpResult(ok=False, error=f"demopeter unreachable: {exc}")
        return PortOpResult(ok=True, data={
            "query": data.get("query", question),
            "answer": data.get("answer", ""),
            "sources": data.get("sources", []),
            "response_time_ms": data.get("response_time_ms"),
            "chunk_count": data.get("chunk_count", 0),
            "retrieval_mode": data.get("retrieval_mode"),
        })

    def search_d_index(self, keyword: str, limit: int = 10) -> PortOpResult:
        """D 盘项目索引语义检索（只读参考证据）。"""
        if not keyword or not keyword.strip():
            return PortOpResult(ok=False, error="keyword is required")
        try:
            data = self._get("/api/d-index/search", {"q": keyword.strip(), "limit": int(limit)})
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge.demopeter: d-index search failed: %s", exc)
            return PortOpResult(ok=False, error=f"demopeter unreachable: {exc}")
        return PortOpResult(ok=True, data=data)
