"""
DIndexer - D 盘文件 Chroma 索引器

将扫描器产出的 chunk 写入 Chroma 向量库，
支持去重（同文件同内容不重复索引）和语义搜索。

断点续传机制：
- 目录级 checkpoint：每处理完一个目录就保存状态，崩溃后跳过已完成的目录
- 文件级缓存：本地 SQLite 记录 (path, size, mtime, fingerprint)，避免查 ChromaDB
- 自动续传：启动时检测 in_progress 状态，从中断处继续
"""
import os
import json
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from .scanner import DScanner, ScanConfig, Chunk
from .checkpoint import ScanCheckpoint
from config.settings import config as app_config
from config.logging_config import get_logger

logger = get_logger("d_indexer")


# D 盘索引专用 Collection
INDEX_COLLECTION = "d_drive_index"


@dataclass
class SearchResult:
    """搜索结果"""
    chunk_id: str
    file_path: str          # 主路径（source_paths[0] 或原始路径）
    project_name: str
    content: str
    file_type: str
    similarity: float
    last_modified: str
    source_paths: list = field(default_factory=list)   # 所有路径（跨路径去重后可能有多个）
    source_count: int = 1                               # 路径数量


@dataclass
class IndexStats:
    """索引统计"""
    collection_name: str
    total_chunks: int
    total_files: int
    last_scan_time: str = ""
    scan_duration_seconds: float = 0
    new_chunks: int = 0
    skipped_files: int = 0  # 跳过的文件数（未变更）
    skipped_chunks: int = 0  # 跳过的 chunk 数（已废弃，保留兼容）


class DIndexer:
    """D 盘文件 Chroma 索引器（支持断点续传）"""

    def __init__(self, scanner: DScanner = None, persist_dir: str = None,
                  checkpoint: ScanCheckpoint = None):
        self.scanner = scanner or DScanner()
        self.persist_dir = persist_dir or app_config.CHROMA_PERSIST_DIR
        self.checkpoint = checkpoint or ScanCheckpoint()
        self._client = None
        self._collection = None
        self._mode = "unavailable"
        self._init_chroma()

    def _init_chroma(self):
        """初始化 Chroma PersistentClient"""
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            try:
                embedding_fn = embedding_functions.DefaultEmbeddingFunction()
            except Exception as e:
                logger.error("Embedding 加载失败: %s", e)
                return

            os.makedirs(self.persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=INDEX_COLLECTION,
                embedding_function=embedding_fn,
                metadata={
                    "description": "D: drive project file index",
                    "hnsw:space": "cosine",
                },
            )
            self._mode = "persistent"
            logger.info("Chroma 已连接 collection=%s path=%s", INDEX_COLLECTION, self.persist_dir)
        except Exception as e:
            logger.error("Chroma 初始化失败: %s", e)
            self._client = None
            self._collection = None
            self._mode = "unavailable"

    @property
    def is_available(self) -> bool:
        return self._collection is not None

    @property
    def count(self) -> int:
        if not self.is_available:
            return 0
        return self._collection.count()

    # 批量 upsert 大小
    BATCH_SIZE = 200

    def index_all(self) -> IndexStats:
        """全量扫描并索引（首次运行或强制刷新）"""
        return self.index_with_resume(resume=False)

    def index_with_resume(self, resume: bool = True) -> IndexStats:
        """
        断点续传式全量扫描索引。
        
        Args:
            resume: True = 自动检测并继续未完成的扫描
                    False = 忽略 checkpoint，从零开始（强制全量）
        
        流程：
        1. 检查 checkpoint，确定哪些项目已完成、哪些在进度中
        2. 对 in_progress 项目，从已完成目录之后继续
        3. 对 pending 项目，从零开始
        4. 每处理完一个目录就保存 checkpoint
        5. 用文件缓存跳过未变更文件（避免读内容 + 查 ChromaDB）
        """
        stats = IndexStats(
            collection_name=INDEX_COLLECTION,
            total_chunks=0,
            total_files=0,
        )
        start_time = time.time()
        batch_chunks: list = []

        # 确定项目列表
        project_roots = self.scanner.config.project_roots
        if not project_roots:
            logger.warning("未配置项目根目录，跳过扫描")
            return stats

        has_incomplete = resume and self.checkpoint.has_incomplete()
        if resume and has_incomplete:
            logger.info("检测到未完成的扫描，将从中断处继续...")

        for project_root in project_roots:
            root_path = Path(project_root) if not isinstance(project_root, Path) else project_root
            if not root_path.exists():
                logger.warning("项目路径不存在: %s", project_root)
                continue

            project_name = root_path.name

            # ===== 检查 checkpoint =====
            if not resume:
                self.checkpoint.reset_project(project_root)

            if not self.checkpoint.start_scan(project_root):
                # 已完成，跳过
                continue

            completed_dirs = self.checkpoint.get_completed_dirs(project_root)
            if completed_dirs:
                logger.info("项目 [%s] 续传模式: 已完成 %d 个目录",
                           project_name, len(completed_dirs))

            # ===== 扫描文件 + 断点续传 =====
            scanned_files = 0
            files_indexed = 0
            chunks_indexed = 0
            current_dir = ""
            prev_dir = ""

            for sf in self.scanner.scan_single_root(
                project_root, completed_dirs=completed_dirs):
                sf_dir = str(Path(sf.file_path).parent)
                scanned_files += 1
                stats.total_files += 1

                # === 目录边界检测：完成一个目录时保存 checkpoint ===
                if sf_dir != current_dir:
                    prev_dir = current_dir
                    current_dir = sf_dir
                    if prev_dir:
                        # 上一个目录完成，保存 checkpoint
                        self.checkpoint.save_progress(
                            project_root,
                            completed_dir=prev_dir,
                            current_dir=current_dir,
                            files_scanned=scanned_files,
                            files_indexed=files_indexed,
                            chunks_indexed=chunks_indexed + len(batch_chunks),
                        )
                        logger.debug("目录完成: %s (%d files in project so far)",
                                     prev_dir, scanned_files)

                # === 文件缓存快速跳过 ===
                try:
                    fstat = Path(sf.file_path).stat()
                    cached_fp = self.checkpoint.lookup_file_cache(
                        sf.file_path, fstat.st_size, fstat.st_mtime
                    )
                except OSError:
                    cached_fp = None

                if cached_fp:
                    # 文件未变更，跳过读内容+索引
                    sf.fingerprint = cached_fp
                    sf.last_modified = fstat.st_mtime
                    sf.size_bytes = fstat.st_size
                    stats.skipped_files += 1

                    # 定期保存（即使跳过，也更新进度）
                    self.checkpoint.maybe_save(
                        project_root,
                        current_dir=current_dir,
                        current_file=sf.file_path,
                        files_scanned=scanned_files,
                        files_indexed=files_indexed,
                        chunks_indexed=chunks_indexed + len(batch_chunks),
                    )
                    continue

                # === 文件已变更，需要重新索引 ===
                sf = self.scanner.read_and_fingerprint(sf)
                if not sf.content:
                    stats.skipped_files += 1
                    continue

                # 删除旧 chunk（如果存在）
                self._delete_by_path(sf.file_path)

                # 分块
                chunks = self.scanner.chunk_file(sf)
                batch_chunks.extend(chunks)
                stats.total_chunks += len(chunks)

                # 缓存文件信息（INSERT OR REPLACE 自动覆盖旧记录）
                self.checkpoint.cache_file(
                    sf.file_path, project_root,
                    sf.size_bytes, sf.last_modified,
                    sf.fingerprint, len(chunks)
                )

                files_indexed += 1

                # 进度输出
                if scanned_files % 100 == 0:
                    elapsed = time.time() - start_time
                    logger.info("[%s] 已扫描 %d 文件 (已索引 %d, 跳过 %d, %.0fs)...",
                               project_name, scanned_files, files_indexed,
                               stats.skipped_files, elapsed)

                # 批量写入 ChromaDB
                if len(batch_chunks) >= self.BATCH_SIZE:
                    n = self._batch_upsert(batch_chunks)
                    chunks_indexed += n
                    stats.new_chunks += n
                    stats.skipped_chunks += len(batch_chunks) - n
                    batch_chunks = []

                # 定期保存断点
                self.checkpoint.maybe_save(
                    project_root,
                    current_dir=current_dir,
                    current_file=sf.file_path,
                    files_scanned=scanned_files,
                    files_indexed=files_indexed,
                    chunks_indexed=chunks_indexed + len(batch_chunks),
                )

            # === 目录循环结束，处理剩余 ===
            # 保存最后一个目录为完成
            if current_dir:
                self.checkpoint.save_progress(
                    project_root,
                    completed_dir=current_dir,
                    files_scanned=scanned_files,
                    files_indexed=files_indexed,
                    chunks_indexed=chunks_indexed + len(batch_chunks),
                )

            # 写入剩余 batch
            if batch_chunks:
                n = self._batch_upsert(batch_chunks)
                chunks_indexed += n
                stats.new_chunks += n
                stats.skipped_chunks += len(batch_chunks) - n
                batch_chunks = []

            # 标记项目完成
            self.checkpoint.complete_scan(
                project_root,
                files_scanned=scanned_files,
                files_indexed=files_indexed,
                chunks_indexed=chunks_indexed,
            )

            logger.info("项目 [%s] 索引完成: %d 文件 (%d 新索引, %d 跳过), %d chunks",
                       project_name, scanned_files, files_indexed,
                       scanned_files - files_indexed, chunks_indexed)

        stats.scan_duration_seconds = round(time.time() - start_time, 2)
        stats.last_scan_time = datetime.now().isoformat()

        logger.info("全量索引完成: %d 文件 %d 新chunks 耗时 %.1fs",
                    stats.total_files, stats.new_chunks, stats.scan_duration_seconds)
        return stats

    def incremental_scan(self) -> IndexStats:
        """
        增量扫描：只索引变更的文件。
        使用本地文件缓存跳过未变更文件（比查 ChromaDB 快 100 倍）。
        """
        stats = IndexStats(
            collection_name=INDEX_COLLECTION,
            total_chunks=0,
            total_files=0,
        )
        start_time = time.time()
        scanned_files = 0
        seen_paths = set()
        batch_chunks: list = []

        for sf in self.scanner.scan():
            # 去重
            if sf.file_path in seen_paths:
                stats.skipped_files += 1
                continue
            seen_paths.add(sf.file_path)
            scanned_files += 1

            # === 文件缓存快速跳过 ===
            try:
                fstat = Path(sf.file_path).stat()
                cached_fp = self.checkpoint.lookup_file_cache(
                    sf.file_path, fstat.st_size, fstat.st_mtime
                )
            except OSError:
                cached_fp = None

            if cached_fp:
                # 文件未变更 (path + size + mtime 全匹配)
                sf.fingerprint = cached_fp
                stats.skipped_files += 1
                continue

            # === 文件已变更，读取并索引 ===
            sf = self.scanner.read_and_fingerprint(sf)
            if not sf.content:
                stats.skipped_files += 1
                continue

            # 删除旧 chunk 再重新写入
            self._delete_by_path(sf.file_path)

            chunks = self.scanner.chunk_file(sf)
            batch_chunks.extend(chunks)
            stats.total_chunks += len(chunks)

            # 更新文件缓存
            project_name = Path(sf.project_root).name
            self.checkpoint.cache_file(
                sf.file_path, project_name,
                sf.size_bytes, sf.last_modified,
                sf.fingerprint, len(chunks)
            )

            if scanned_files % 50 == 0:
                elapsed = time.time() - start_time
                logger.info("增量扫描: 已处理 %d 文件 (%d chunks, %.0fs)...",
                           scanned_files, stats.total_chunks, elapsed)

            if len(batch_chunks) >= self.BATCH_SIZE:
                n = self._batch_upsert(batch_chunks)
                stats.new_chunks += n
                batch_chunks = []

        if batch_chunks:
            n = self._batch_upsert(batch_chunks)
            stats.new_chunks += n

        stats.total_files = scanned_files
        stats.scan_duration_seconds = round(time.time() - start_time, 2)
        stats.last_scan_time = datetime.now().isoformat()
        return stats

    def _batch_upsert(self, chunks: list) -> int:
        """批量写入 chunk 到 Chroma，支持跨路径去重（空间维度）

        核心逻辑：
        1. 同一批内 chunk_id 相同的先合并 source_paths（可能来自不同路径的同内容文件）
        2. 查询 Chroma 中已存在的 chunk，将其 source_paths 与新路径合并
        3. upsert 写入（已有的更新路径列表，没有的新建）
        """
        if not self.is_available or not chunks:
            return 0
        try:
            # --- 步骤 1：批内合并（同 chunk_id 不同路径） ---
            merged: dict[str, dict] = {}  # chunk_id -> {chunk, source_paths: set}
            for c in chunks:
                if c.chunk_id not in merged:
                    merged[c.chunk_id] = {
                        "chunk": c,
                        "source_paths": {c.file_path},
                        "project_names": {c.project_name},
                    }
                else:
                    merged[c.chunk_id]["source_paths"].add(c.file_path)
                    merged[c.chunk_id]["project_names"].add(c.project_name)

            if len(merged) < len(chunks):
                logger.info("批内空间去重: %d -> %d chunks（%d 条跨路径合并）",
                            len(chunks), len(merged), len(chunks) - len(merged))

            # --- 步骤 2：查 Chroma 中已有的 chunk，合并旧 source_paths ---
            existing_ids = list(merged.keys())
            try:
                existing = self._collection.get(
                    ids=existing_ids,
                    include=["metadatas"],
                )
                for i, eid in enumerate(existing.get("ids", [])):
                    if eid in merged:
                        old_meta = existing["metadatas"][i] if existing.get("metadatas") else {}
                        old_paths_raw = old_meta.get("source_paths", "")
                        if old_paths_raw:
                            try:
                                old_paths = set(json.loads(old_paths_raw))
                            except (json.JSONDecodeError, TypeError):
                                old_paths = {old_paths_raw}
                            merged[eid]["source_paths"].update(old_paths)
                        old_projects_raw = old_meta.get("project_names", "")
                        if old_projects_raw:
                            try:
                                old_projects = set(json.loads(old_projects_raw))
                            except (json.JSONDecodeError, TypeError):
                                old_projects = {old_projects_raw}
                            merged[eid]["project_names"].update(old_projects)
            except Exception as e:
                logger.debug("查询已有 chunk 失败（首次写入正常）: %s", e)

            # --- 步骤 3：构建 upsert 数据 ---
            ids = []
            documents = []
            metadatas = []

            for chunk_id, data in merged.items():
                c = data["chunk"]
                paths_sorted = sorted(data["source_paths"])
                projects_sorted = sorted(data["project_names"])

                ids.append(chunk_id)
                documents.append(c.content)
                metadatas.append({
                    "file_path": paths_sorted[0],        # 主路径（兼容旧字段）
                    "source_paths": json.dumps(paths_sorted, ensure_ascii=False),
                    "source_count": len(paths_sorted),
                    "project_name": projects_sorted[0],  # 主项目（兼容旧字段）
                    "project_names": json.dumps(projects_sorted, ensure_ascii=False),
                    "file_type": c.file_type,
                    "chunk_index": c.chunk_index,
                    "total_chunks": c.total_chunks,
                    "last_modified": c.last_modified,
                })

            self._collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            return len(ids)
        except Exception as e:
            logger.error("批量 upsert 失败: %s", e)
            return 0

    def _needs_update_by_mtime(self, sf) -> bool:
        """检查文件是否需要重新索引（基于路径+修改时间）"""
        if not self.is_available:
            return True
        try:
            results = self._collection.get(
                where={"file_path": sf.file_path},
                include=["metadatas"],
            )
            if not results["ids"]:
                return True
            # 检查是否有不同的修改时间
            for meta in results.get("metadatas", []):
                if meta.get("last_modified") != sf.last_modified:
                    return True
            return False
        except Exception:
            return True

    def _needs_update(self, sf) -> bool:
        """检查文件是否需要重新索引"""
        if not self.is_available:
            return True
        try:
            results = self._collection.get(
                ids=[f"{sf.fingerprint}_chunk_0"],
            )
            return len(results["ids"]) == 0
        except Exception:
            return True

    def _delete_by_path(self, file_path: str):
        """从索引中移除某个文件路径

        空间去重策略下，一个 chunk 可能被多个路径共享：
        - 如果该 chunk 还有其他路径 → 只从 source_paths 中移除该路径，保留 chunk
        - 如果该 chunk 只有这一个路径 → 删除 chunk
        """
        if not self.is_available:
            return
        try:
            results = self._collection.get(
                where={"file_path": file_path},
                include=["metadatas"],
            )
            if not results.get("ids"):
                return

            ids_to_delete = []
            ids_to_update = []
            updated_metadatas = []

            for i, chunk_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results.get("metadatas") else {}
                raw = meta.get("source_paths", "")
                try:
                    paths = set(json.loads(raw)) if raw else {meta.get("file_path", file_path)}
                except (json.JSONDecodeError, TypeError):
                    paths = {raw} if raw else {file_path}

                paths.discard(file_path)

                if not paths:
                    # 没有其他路径，删除 chunk
                    ids_to_delete.append(chunk_id)
                else:
                    # 还有其他路径，更新 source_paths
                    paths_sorted = sorted(paths)
                    new_meta = dict(meta)
                    new_meta["file_path"] = paths_sorted[0]
                    new_meta["source_paths"] = json.dumps(paths_sorted, ensure_ascii=False)
                    new_meta["source_count"] = len(paths_sorted)
                    ids_to_update.append(chunk_id)
                    updated_metadatas.append(new_meta)

            if ids_to_delete:
                self._collection.delete(ids=ids_to_delete)
                logger.debug("删除孤立 chunk: %d 个（文件: %s）", len(ids_to_delete), file_path)

            if ids_to_update:
                # ChromaDB 没有 update-only-metadata，用 upsert（不更新 embedding）
                existing_docs = self._collection.get(ids=ids_to_update, include=["documents"])
                docs = existing_docs.get("documents") or [""] * len(ids_to_update)
                self._collection.upsert(
                    ids=ids_to_update,
                    documents=docs,
                    metadatas=updated_metadatas,
                )
                logger.debug("从 source_paths 移除路径: %d 个 chunk 保留（文件: %s）",
                             len(ids_to_update), file_path)

        except Exception as e:
            logger.error("_delete_by_path 失败: %s", e)

    def search(self, query: str, top_k: int = 10,
               project_filter: str = None,
               file_type_filter: str = None) -> list[SearchResult]:
        """语义搜索 D 盘文件内容"""
        if not self.is_available:
            return []

        where = {}
        if project_filter:
            where["project_name"] = project_filter
        if file_type_filter:
            where["file_type"] = file_type_filter
        if not where:
            where = None

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error("搜索失败: %s", e)
            return []

        hits = []
        if results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
                distance = results.get("distances", [[1.0]])[0][i]
                similarity = max(0.0, min(1.0, 1.0 - distance / 2.0))

                last_mod = datetime.fromtimestamp(
                    metadata.get("last_modified", 0)
                ).strftime("%Y-%m-%d %H:%M")

                # 解析 source_paths（兼容新旧格式）
                raw_paths = metadata.get("source_paths", "")
                if raw_paths:
                    try:
                        source_paths = json.loads(raw_paths)
                    except (json.JSONDecodeError, TypeError):
                        source_paths = [raw_paths]
                else:
                    source_paths = [metadata.get("file_path", "")]

                primary_path = source_paths[0] if source_paths else metadata.get("file_path", "")

                # project_names 兼容
                raw_projects = metadata.get("project_names", "")
                if raw_projects:
                    try:
                        project_names = json.loads(raw_projects)
                        primary_project = project_names[0]
                    except (json.JSONDecodeError, TypeError):
                        primary_project = metadata.get("project_name", "")
                else:
                    primary_project = metadata.get("project_name", "")

                hits.append(SearchResult(
                    chunk_id=results["ids"][0][i],
                    file_path=primary_path,
                    project_name=primary_project,
                    content=results["documents"][0][i][:300] if results.get("documents") else "",
                    file_type=metadata.get("file_type", ""),
                    similarity=round(similarity, 4),
                    last_modified=last_mod,
                    source_paths=source_paths,
                    source_count=len(source_paths),
                ))

        return hits

    def list_projects(self) -> list[dict]:
        """
        列出已索引的项目及文件数。
        通过遍历已知项目根目录后逐个查询，避免一次捞全部 metadata 导致 OOM。
        """
        if not self.is_available:
            return []

        # 从已配置的项目根目录推导项目名
        configured_names = set()
        for root in self.scanner.config.project_roots:
            try:
                configured_names.add(Path(root).name)
            except Exception:
                pass

        # 也查 ChromaDB 中实际存在的 project_name（可能有多余的）
        all_names = set(configured_names)
        try:
            # 用 peek 快速看看存储层有没有额外项目
            sample = self._collection.peek(limit=100)
            for meta in sample.get("metadatas", []):
                pn = meta.get("project_name", "")
                if pn:
                    all_names.add(pn)
        except Exception:
            pass

        result = []
        for name in sorted(all_names):
            try:
                # 按项目名查询该项目的 chunk 数
                where_result = self._collection.get(
                    where={"project_name": name},
                    include=[],
                )
                chunk_count = len(where_result.get("ids", []))
                if chunk_count == 0:
                    continue
            except Exception:
                chunk_count = 0
                continue

            # 估算文件数：取前 500 个元数据来去重 file_path
            file_set = set()
            types_set = set()
            try:
                sample = self._collection.get(
                    where={"project_name": name},
                    include=["metadatas"],
                    limit=500,
                )
                for meta in sample.get("metadatas", []):
                    fp = meta.get("file_path", "")
                    ft = meta.get("file_type", "")
                    if fp:
                        file_set.add(fp)
                    if ft:
                        types_set.add(ft)
            except Exception:
                pass

            file_estimate = len(file_set)
            if chunk_count > 500 and file_estimate >= 500:
                # 样本饱和，标记为估算
                file_estimate = f">={file_estimate}"

            result.append({
                "project": name,
                "files": file_estimate,
                "chunks": chunk_count,
                "file_types": sorted(types_set)[:10],
            })

        return result

    def _count_by_project(self, project_name: str) -> int:
        try:
            result = self._collection.get(
                where={"project_name": project_name},
                include=[],
            )
            return len(result.get("ids", []))
        except Exception:
            return 0

    def clear_index(self):
        """清空索引"""
        if not self.is_available:
            return
        try:
            self._client.delete_collection(INDEX_COLLECTION)
            self._init_chroma()
        except Exception:
            pass
