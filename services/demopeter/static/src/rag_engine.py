"""
szpeter2026 - RAG 检索引擎
吸收自 72changes RAGService，实现检索增强生成
支持 Chroma + pgvector 双向量后端 + SQLite FTS5 混合检索
"""
import json
import re
import time
from dataclasses import dataclass, field

from config.settings import config
from src.ai_client import AIClient
from src.db_manager import DBManager
from src.hybrid_search import reciprocal_rank_fusion, weighted_fusion, filter_by_threshold
from src.pgvector_store import PgvectorStore
from src.vector_store import VectorStore


@dataclass
class RAGResult:
    """RAG 查询结果"""
    query: str
    answer: str
    sources: list[dict] = field(default_factory=list)
    response_time_ms: float = 0
    chunk_count: int = 0
    retrieval_mode: str = ""


# RAG 提示词模板
RAG_PROMPT_TEMPLATE = """你是一个智能知识库助手，请根据以下参考资料回答用户的问题。

## 规则
1. 优先使用参考资料中的信息回答
2. 如果提供了知识库文档目录，请结合目录与正文片段做跨文档、跨年份对比与推理，明确指出时间覆盖范围与缺口（如缺哪年的完整年报）
3. 如果参考资料不足以回答问题，请诚实说明
4. 回答要简洁、准确、有条理
5. 引用资料时注明来源

{catalog_section}## 参考资料（正文片段）
{context}

## 用户问题
{query}

## 回答"""


class RAGEngine:
    """RAG 检索引擎 — 检索 → 增强 → 生成"""

    def __init__(self):
        self._ai: AIClient | None = None
        self.vector_store = VectorStore()
        self.pgvector_store = PgvectorStore()
        self.db = DBManager()

    @property
    def ai(self) -> AIClient:
        if self._ai is None:
            self._ai = AIClient()
        return self._ai

    def _vector_search(self, query_text: str, top_k: int,
                       threshold: float) -> tuple[list[dict], str]:
        """Chroma → pgvector 向量检索，返回 (结果, 来源标签)。"""
        if self.vector_store.is_available:
            hits = self.vector_store.search(
                query_text, top_k=top_k, threshold=threshold,
            )
            if hits:
                for hit in hits:
                    hit["retrieval"] = "vector_chroma"
                return hits, "vector_chroma"
        if self.pgvector_store.is_available:
            hits = self.pgvector_store.search(
                query_text, top_k=top_k, threshold=threshold,
            )
            for hit in hits:
                hit["retrieval"] = "vector_pgvector"
            return hits, "vector_pgvector"
        return [], "none"

    def _keyword_search(self, query_text: str, top_k: int) -> list[dict]:
        hits = self.db.search_chunks(query_text, top_k=top_k)
        for hit in hits:
            hit["retrieval"] = "keyword_fts5"
        return hits

    def _search_hybrid(self, query_text: str, top_k: int = 5,
                       threshold: float = 0.5) -> tuple[list[dict], str]:
        """向量 + 关键词 RRF 融合，并按 threshold 过滤低相关结果。"""
        fetch_k = max(top_k * 3, 15)
        # 向量通道：阈值略放宽，融合后再统一过滤
        vector_threshold = max(0.0, threshold - 0.15)
        vector_hits, vector_src = self._vector_search(
            query_text, top_k=fetch_k, threshold=vector_threshold,
        )
        keyword_hits = self._keyword_search(query_text, top_k=fetch_k)

        merged: list[dict] = []
        mode_label = "keyword_fts5"

        if vector_hits and keyword_hits:
            if config.SEARCH_MODE == "hybrid_weighted":
                merged = weighted_fusion(
                    vector_hits, keyword_hits, top_k=fetch_k,
                    vector_weight=config.VECTOR_WEIGHT,
                    keyword_weight=config.KEYWORD_WEIGHT,
                )
            else:
                merged = reciprocal_rank_fusion(
                    [vector_hits, keyword_hits],
                    top_k=fetch_k,
                    k=config.HYBRID_RRF_K,
                    lane_names=["vector", "keyword"],
                )
            mode_label = f"hybrid_rrf({vector_src}+keyword_fts5)"
        elif vector_hits:
            merged = vector_hits
            mode_label = vector_src
        else:
            merged = keyword_hits
            mode_label = "keyword_fts5"

        filtered = filter_by_threshold(merged, threshold)
        if filtered:
            return filtered[:top_k], mode_label

        # 阈值过严时：返回最相关的 1 条并标注
        if merged:
            best = merged[0]
            best["_below_threshold"] = True
            return [best], mode_label + "+below_threshold"

        return [], mode_label

    def _search(self, query_text: str, top_k: int = 5,
                threshold: float = 0.5) -> tuple[list[dict], str]:
        mode = config.SEARCH_MODE.lower()

        if mode == "keyword":
            return self._keyword_search(query_text, top_k=top_k), "keyword_fts5"

        if mode in ("hybrid", "hybrid_weighted"):
            return self._search_hybrid(query_text, top_k=top_k, threshold=threshold)

        # vector: 原降级链 Chroma → pgvector → keyword
        vector_hits, vector_src = self._vector_search(
            query_text, top_k=top_k, threshold=threshold,
        )
        if vector_hits:
            return vector_hits, vector_src
        return self._keyword_search(query_text, top_k=top_k), "keyword_fts5"

    def search_only(self, query_text: str, top_k: int = 5,
                    threshold: float = 0.5) -> dict:
        """仅检索，不调用 LLM（MCP / 压测用）。"""
        start = time.time()
        hits, mode = self._search(query_text, top_k=top_k, threshold=threshold)
        elapsed_ms = (time.time() - start) * 1000
        return {
            "query": query_text,
            "retrieval_mode": mode,
            "response_time_ms": round(elapsed_ms, 2),
            "hits": [
                {
                    "content": h["content"][:500],
                    "source": (h.get("metadata") or {}).get("source_file", ""),
                    "similarity": h.get("similarity", 0),
                    "retrieval": h.get("retrieval", mode),
                }
                for h in hits
            ],
        }

    def _needs_doc_catalog(self, query: str) -> bool:
        """跨文档/年份对比类问题需要注入文档目录。"""
        keys = (
            "缺失", "缺少", "缺多少", "覆盖", "哪些年", "年份", "对比", "跨",
            "有哪些", "清单", "列表", "完整", "年报", "季报", "财务数据",
        )
        return any(k in query for k in keys)

    def _doc_catalog_context(self, query: str) -> str:
        """从元数据生成文档目录，供跨文档推理使用。"""
        docs = self.db.get_documents(status="completed")
        if "科锐" in query:
            docs = [
                d for d in docs
                if json.loads(d.get("metadata") or "{}").get("corpus_label") == "科锐国际"
            ]
        if not docs:
            return ""

        seen: dict[str, str] = {}
        for doc in docs:
            title = (doc.get("title") or "").strip()
            norm = re.sub(r"\s+", "", title).lower()
            if norm and norm not in seen:
                seen[norm] = title

        titles = sorted(seen.values())
        years: dict[str, list[str]] = {}
        for title in titles:
            m = re.search(r"(20\d{2})", title)
            year = m.group(1) if m else "其他"
            years.setdefault(year, []).append(title)

        lines = [
            f"## 知识库文档目录（去重后 {len(titles)} 份，可用于跨年份对比）",
            "请据此判断：哪些年份只有季报/半年报、哪些年份缺完整年报、时间序列是否有断档。",
        ]
        for year in sorted(years):
            lines.append(f"\n### {year} 年")
            for title in years[year]:
                lines.append(f"- {title}")
        return "\n".join(lines)

    def _build_rag_prompt(self, query_text: str, hits: list[dict]) -> str:
        context_parts = []
        for i, hit in enumerate(hits):
            src = hit["metadata"].get("source_file", "未知来源")
            context_parts.append(f"[来源 {i + 1}: {src}]\n{hit['content']}")
        context = "\n\n---\n\n".join(context_parts)

        catalog_section = ""
        if self._needs_doc_catalog(query_text):
            catalog = self._doc_catalog_context(query_text)
            if catalog:
                catalog_section = catalog + "\n\n"

        return RAG_PROMPT_TEMPLATE.format(
            catalog_section=catalog_section,
            context=context,
            query=query_text,
        )

    def _format_sources(self, hits: list[dict], retrieval_mode: str) -> list[dict]:
        return [{
            "content": h["content"][:1200],
            "source": h["metadata"].get("source_file", ""),
            "similarity": h.get("similarity", 0),
            "retrieval": h.get("retrieval", retrieval_mode),
            "below_threshold": h.get("_below_threshold", False),
        } for h in hits]

    def _similarity_label(self, hit: dict) -> str:
        sim = hit.get("similarity", 0)
        pct = sim * 100
        lanes = hit.get("lane_scores") or {}
        if lanes:
            parts = [f"{k}:{v:.2f}" for k, v in lanes.items()]
            return f"匹配度 {pct:.0f}% ({', '.join(parts)})"
        return f"匹配度 {pct:.0f}%"

    def _retrieval_only_answer(self, hits: list[dict], ai_hint: str,
                               threshold: float = 0.5) -> str:
        lines = [
            "⚠️ AI 生成未启用：" + ai_hint,
            "",
            "以下为知识库检索结果（检索模式，非 AI 总结）。",
            f"当前相似度阈值: {threshold}（可在下方调节，混合检索建议 0.3~0.5）",
            "",
        ]
        if hits and hits[0].get("_below_threshold"):
            lines.append(
                f"⚠️ 未找到达到阈值 {threshold} 的结果，以下为最接近的 1 条参考，"
                "建议降低阈值或换关键词。",
            )
            lines.append("")

        for i, hit in enumerate(hits, 1):
            src = hit["metadata"].get("source_file", "未知来源")
            corpus = hit["metadata"].get("corpus_label", "")
            prefix = f"[{corpus}] " if corpus else ""
            lines.append(f"━━━ 片段 {i} ━━━")
            lines.append(f"📄 {prefix}{src}")
            lines.append(f"📊 {self._similarity_label(hit)}")
            lines.append("")
            lines.append(hit["content"].strip())
            lines.append("")
        return "\n".join(lines).strip()

    def query(self, query_text: str, top_k: int = 5,
              threshold: float = 0.5) -> RAGResult:
        """执行 RAG 查询"""
        start = time.time()

        hits, retrieval_mode = self._search(
            query_text, top_k=top_k, threshold=threshold,
        )
        chunk_count = len(hits)
        sources = self._format_sources(hits, retrieval_mode)

        if not hits:
            answer = "知识库中暂未找到与您问题相关的资料，请尝试更换关键词或导入更多文档。"
            elapsed_ms = (time.time() - start) * 1000
            self.db.log_query(query_text, config.AI_PROVIDER, elapsed_ms, 0)
            return RAGResult(
                query=query_text,
                answer=answer,
                sources=[],
                response_time_ms=round(elapsed_ms, 2),
                chunk_count=0,
                retrieval_mode=retrieval_mode,
            )

        ai_ok, ai_hint = AIClient.is_configured()
        if not ai_ok:
            answer = self._retrieval_only_answer(hits, ai_hint, threshold=threshold)
            elapsed_ms = (time.time() - start) * 1000
            self.db.log_query(query_text, "retrieval_only", elapsed_ms, chunk_count)
            return RAGResult(
                query=query_text,
                answer=answer,
                sources=sources,
                response_time_ms=round(elapsed_ms, 2),
                chunk_count=chunk_count,
                retrieval_mode=retrieval_mode + "+retrieval_only",
            )

        context_parts = []
        for i, hit in enumerate(hits):
            src = hit["metadata"].get("source_file", "未知来源")
            context_parts.append(f"[来源 {i + 1}: {src}]\n{hit['content']}")
        context = "\n\n---\n\n".join(context_parts)

        messages = [
            {"role": "system", "content": self._build_rag_prompt(query_text, hits)},
        ]

        answer, _ = self.ai.chat(messages)
        elapsed_ms = (time.time() - start) * 1000
        self.db.log_query(query_text, self.ai.provider, elapsed_ms, chunk_count)

        return RAGResult(
            query=query_text,
            answer=answer,
            sources=sources,
            response_time_ms=round(elapsed_ms, 2),
            chunk_count=chunk_count,
            retrieval_mode=retrieval_mode,
        )

    def query_stream(self, query_text: str, top_k: int = 5,
                     threshold: float = 0.5) -> tuple:
        """流式 RAG 查询，返回 (生成器, hits)"""
        hits, retrieval_mode = self._search(
            query_text, top_k=top_k, threshold=threshold,
        )

        if not hits:
            def _empty():
                yield "知识库中暂未找到与您问题相关的资料，请尝试更换关键词或导入更多文档。"
                yield 0.0
            return _empty(), []

        ai_ok, ai_hint = AIClient.is_configured()
        if not ai_ok:
            answer = self._retrieval_only_answer(hits, ai_hint, threshold=threshold)

            def _retrieval_stream():
                yield answer
                yield 0.0

            return _retrieval_stream(), hits

        messages = [{"role": "system", "content": self._build_rag_prompt(query_text, hits)}]

        return self.ai.chat_stream(messages), hits

    @property
    def is_vector_available(self) -> bool:
        return self.vector_store.is_available
