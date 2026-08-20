"""
知识库服务层 — 供 MCP、压测脚本、Web 面板共用的导入/检索/统计接口
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from config.corpus_loader import CorpusSource, load_corpus_sources
from config.settings import config
from src.db_manager import DBManager
from src.doc_processor import DocumentProcessor
from src.pgvector_store import PgvectorStore
from src.vector_store import VectorStore


@dataclass
class ImportSummary:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_sec: float = 0.0
    errors: list[str] = field(default_factory=list)
    by_corpus: dict[str, int] = field(default_factory=dict)

    @property
    def docs_per_sec(self) -> float:
        if self.elapsed_sec <= 0:
            return 0.0
        return round(self.success / self.elapsed_sec, 2)


class KnowledgeBaseService:
    """文档导入与知识库统计的统一入口。"""

    def __init__(self):
        self.db = DBManager()
        self.processor = DocumentProcessor()
        self.vector_store = VectorStore()
        self.pgvector_store = PgvectorStore()

    def _find_doc_by_path(self, file_path: str) -> dict | None:
        for doc in self.db.get_documents():
            if doc.get("file_path") == file_path:
                return doc
        return None

    def _import_files(
        self,
        files: list[dict],
        *,
        force: bool = False,
    ) -> ImportSummary:
        summary = ImportSummary(total=len(files))
        start = time.time()

        for file_info in files:
            label = file_info.get("corpus_label", "default")
            existing_doc = self._find_doc_by_path(file_info["file_path"])
            if existing_doc and not force:
                summary.skipped += 1
                continue
            if existing_doc and force:
                self.db.delete_document(existing_doc["id"])
                if self.vector_store.is_available:
                    self.vector_store.delete_document(str(existing_doc["id"]))
                if self.pgvector_store.is_available:
                    self.pgvector_store.delete_document(existing_doc["id"])

            doc_id = None
            try:
                doc_meta = {
                    "corpus_id": file_info.get("corpus_id", ""),
                    "corpus_label": label,
                }
                doc_id = self.db.register_document(
                    title=file_info["title"],
                    file_path=file_info["file_path"],
                    doc_type=file_info["doc_type"],
                    file_size=file_info.get("file_size", 0),
                    metadata=doc_meta,
                )
                _, chunks = self.processor.process_file(
                    file_info["file_path"],
                    extra_metadata=doc_meta,
                )
                self.db.save_chunks(doc_id, chunks)

                if self.vector_store.is_available:
                    self.vector_store.add_documents(str(doc_id), chunks)
                if self.pgvector_store.is_available:
                    self.pgvector_store.add_documents(doc_id, chunks)

                self.db.update_document_status(doc_id, "completed", len(chunks))
                summary.success += 1
                summary.by_corpus[label] = summary.by_corpus.get(label, 0) + 1
            except Exception as exc:
                if doc_id is not None:
                    self.db.delete_document(doc_id)
                summary.failed += 1
                summary.errors.append(f"[{label}] {file_info['title']}: {exc}")

        summary.elapsed_sec = round(time.time() - start, 2)
        return summary

    def import_directory(
        self,
        directory: str | Path,
        *,
        force: bool = False,
        limit: int | None = None,
        corpus_label: str = "",
        corpus_id: str = "",
    ) -> ImportSummary:
        directory = Path(directory).resolve()
        if not directory.exists():
            raise FileNotFoundError(f"目录不存在: {directory}")

        files = self.processor.scan_directory(
            directory,
            corpus_label=corpus_label or directory.name,
        )
        for f in files:
            f["corpus_id"] = corpus_id
        if limit is not None:
            files = files[:limit]
        return self._import_files(files, force=force)

    def import_fused_corpus(
        self,
        sources: list[CorpusSource] | None = None,
        *,
        force: bool = False,
        limit_per_source: int | None = None,
    ) -> ImportSummary:
        """融合导入多个语料源（科锐国际 + Python实战 等）。"""
        sources = sources or load_corpus_sources()
        all_files: list[dict] = []

        for source in sources:
            if not source.path.exists():
                continue
            files = self.processor.scan_directory(
                source.path,
                corpus_label=source.label,
            )
            for f in files:
                f["corpus_id"] = source.id
                f["corpus_label"] = source.label
            if limit_per_source is not None:
                files = files[:limit_per_source]
            all_files.extend(files)

        summary = self._import_files(all_files, force=force)
        return summary

    def import_jsonl(
        self,
        jsonl_path: str | Path,
        *,
        force: bool = False,
        label: str = "md_import_staging",
    ) -> ImportSummary:
        """从预处理 JSONL 文件批量入库（跳过磁盘重读，直接使用预处理 content）。"""
        jsonl_path = Path(jsonl_path).resolve()
        if not jsonl_path.exists():
            raise FileNotFoundError(f"JSONL 文件不存在: {jsonl_path}")

        with open(jsonl_path, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]

        summary = ImportSummary(total=len(records))
        start = time.time()

        for rec in records:
            file_path = rec.get("source_file", "")
            title     = rec.get("title", Path(file_path).stem)
            language  = rec.get("language", "unknown")
            content   = rec.get("content", "")
            doc_type  = rec.get("content_type", "general")

            if not content or not file_path:
                summary.skipped += 1
                continue

            existing_doc = self._find_doc_by_path(file_path)
            if existing_doc and not force:
                summary.skipped += 1
                continue
            if existing_doc and force:
                self.db.delete_document(existing_doc["id"])
                if self.vector_store.is_available:
                    self.vector_store.delete_document(str(existing_doc["id"]))
                if self.pgvector_store.is_available:
                    self.pgvector_store.delete_document(existing_doc["id"])

            doc_id = None
            try:
                meta = {
                    "corpus_id": label,
                    "corpus_label": label,
                    "language": language,
                    "content_type": doc_type,
                    "preprocessed": True,
                }
                doc_id = self.db.register_document(
                    title=title,
                    file_path=file_path,
                    doc_type=doc_type,
                    file_size=len(content.encode("utf-8")),
                    metadata=meta,
                )

                # 直接用预处理好的 content 做分块
                chunks = self.processor.chunk_text(
                    content,
                    metadata={**meta, "source_file": file_path, "title": title},
                )
                self.db.save_chunks(doc_id, chunks)

                if self.vector_store.is_available:
                    self.vector_store.add_documents(str(doc_id), chunks)
                if self.pgvector_store.is_available:
                    self.pgvector_store.add_documents(doc_id, chunks)

                self.db.update_document_status(doc_id, "completed", len(chunks))
                summary.success += 1
                summary.by_corpus[label] = summary.by_corpus.get(label, 0) + 1

            except Exception as exc:
                if doc_id is not None:
                    self.db.delete_document(doc_id)
                summary.failed += 1
                summary.errors.append(f"[{label}] {title}: {exc}")

        summary.elapsed_sec = round(time.time() - start, 2)
        return summary

    def list_corpus_sources(self) -> list[dict]:
        sources = load_corpus_sources()
        result = []
        for s in sources:
            count = 0
            if s.path.exists():
                count = len(self.processor.scan_directory(s.path, corpus_label=s.label))
            result.append({
                "id": s.id,
                "label": s.label,
                "path": str(s.path),
                "exists": s.path.exists(),
                "file_count": count,
                "description": s.description,
            })
        return result

    def stats(self) -> dict:
        db_stats = self.db.get_stats()
        vector_stats = self.vector_store.get_collection_stats()
        pg_stats = self.pgvector_store.get_stats()
        return {
            **db_stats,
            "vector": vector_stats,
            "pgvector": pg_stats,
            "search_mode": config.SEARCH_MODE,
            "ai_provider": config.AI_PROVIDER,
            "corpus_sources": self.list_corpus_sources(),
        }
