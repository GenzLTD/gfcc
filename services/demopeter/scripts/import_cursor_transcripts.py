r"""
Cursor 对话导入 DemoPeter RAG 知识库

将 C:\Users\HUAWEI\.cursor\projects\ 下的 AI 辅助开发对话
解析、脱敏、分块后导入 Chroma 向量库，支持语义检索。

功能:
  1. 扫描所有 Cursor 项目中的 JSONL 对话文件
  2. 按对话轮次边界智能分块（保留上下文完整性）
  3. 导入 Chroma 独立 collection "cursor_conversations"
  4. 可选：生成 Chronicle 事件种子
  5. 支持增量导入（按 session_id 去重）

用法:
  # 扫描预览（不写入）
  python scripts/import_cursor_transcripts.py --dry-run

  # 完整导入
  python scripts/import_cursor_transcripts.py

  # 仅导入指定项目
  python scripts/import_cursor_transcripts.py --project "e-Nezha"

  # 同时生成 Chronicle 事件
  python scripts/import_cursor_transcripts.py --chronicle

  # 强制重新导入
  python scripts/import_cursor_transcripts.py --force

Chroma Collection: cursor_conversations
元数据字段: session_id, project_name, d_project, tags, turn_start, turn_end
"""

import sys
import io
from pathlib import Path

# 强制 UTF-8 输出（Windows GBK 终端不支持 emoji）
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 路径引导
_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT / "static"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse
import json
import os
from datetime import datetime
from typing import Optional

from config.settings import config
from config.logging_config import get_logger

logger = get_logger("cursor_import")

# 导入解析器
from scripts.cursor_parser import (
    CursorParser,
    CursorSession,
    ConversationChunk,
    CURSOR_PROJECTS_DIR,
    PROJECT_MAPPING,
)

# ===== 常量 =====
COLLECTION_NAME = "cursor_conversations"
CHROMA_BATCH_SIZE = 100


class CursorImporter:
    """Cursor 对话 Chroma 导入器"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.parser = CursorParser()
        self._client = None
        self._collection = None
        self._stats = {
            "sessions_total": 0,
            "sessions_imported": 0,
            "sessions_skipped": 0,
            "chunks_total": 0,
            "chunks_imported": 0,
            "chars_total": 0,
            "errors": 0,
        }

        if not dry_run:
            self._init_chroma()

    def _init_chroma(self):
        """初始化 Chroma 客户端和 collection"""
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            # 显式加载 embedding 函数
            try:
                embedding_fn = embedding_functions.DefaultEmbeddingFunction()
            except Exception as e:
                logger.error("Embedding 函数加载失败: %s", e)
                logger.error("请安装 onnxruntime: pip install onnxruntime")
                raise

            os.makedirs(config.CHROMA_PERSIST_DIR, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=config.CHROMA_PERSIST_DIR,
            )
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_fn,
                metadata={
                    "description": (
                        "Cursor AI 辅助开发对话记录 — "
                        "涵盖 Zervi 微服务/Nezha Spring AI/Iamgeek 社区/"
                        "SmartJobs 招聘/TimesSquare 知识库等项目"
                    ),
                    "source": "C:\\Users\\HUAWEI\\.cursor\\projects",
                    "created_at": datetime.now().isoformat(),
                },
            )
            logger.info(
                "Chroma 就绪: collection=%s, mode=persistent, path=%s",
                COLLECTION_NAME, config.CHROMA_PERSIST_DIR,
            )
        except Exception as e:
            logger.error("Chroma 初始化失败: %s", e)
            raise

    @property
    def is_available(self) -> bool:
        return self._collection is not None

    # ===== 主流程 =====

    def import_all(
        self,
        project_filter: str | None = None,
        force: bool = False,
        with_chronicle: bool = False,
    ) -> dict:
        """主入口：扫描并导入所有 Cursor 对话"""
        print("\n" + "=" * 60)
        print("  Cursor 对话 → DemoPeter RAG 知识库 导入工具")
        print("=" * 60)
        print(f"  源目录: {CURSOR_PROJECTS_DIR}")
        print(f"  模式: {'🔍 预览 (dry-run)' if self.dry_run else '📥 正式导入'}")
        if project_filter:
            print(f"  过滤: {project_filter}")
        print()

        # 1. 扫描
        print("🔍 扫描 Cursor 项目目录...")
        sessions = self.parser.scan_all_projects(skip_temp=True)
        self._stats["sessions_total"] = len(sessions)

        if project_filter:
            sessions = [
                s for s in sessions
                if project_filter.lower() in s.project_dir.lower()
                or project_filter.lower() in s.project_name.lower()
            ]
            print(f"  过滤后: {len(sessions)} 个会话")

        # 2. 统计概览
        total_chars = sum(s.total_chars for s in sessions)
        total_turns = sum(s.turn_count for s in sessions)
        self._stats["chars_total"] = total_chars

        print(f"  发现 {len(sessions)} 个会话, {total_turns} 轮对话, {total_chars:,} 字符\n")

        # 3. 获取已导入的 session_id 列表（去重）
        imported_ids = set()
        if not force and self.is_available:
            try:
                existing = self._collection.get()
                if existing.get("metadatas"):
                    for meta in existing["metadatas"]:
                        sid = meta.get("session_id", "")
                        if sid:
                            imported_ids.add(sid)
                if imported_ids:
                    print(f"  已导入 {len(imported_ids)} 个会话，将跳过重复项\n")
            except Exception:
                pass

        # 4. 逐会话导入
        project_sessions: dict[str, list] = {}
        for s in sessions:
            project_sessions.setdefault(s.project_name, []).append(s)

        for project_name, proj_sessions in sorted(project_sessions.items()):
            print(f"📂 {project_name} ({len(proj_sessions)} 会话)")
            for session in proj_sessions:
                self._import_session(session, imported_ids, force)

        # 5. Chronicle 播种
        if with_chronicle and not self.dry_run:
            self._seed_chronicle(sessions)

        # 6. 汇总
        self._print_summary()
        return self._stats

    def _import_session(
        self,
        session: CursorSession,
        imported_ids: set,
        force: bool,
    ):
        """导入单个会话"""
        sid = session.session_id

        if sid in imported_ids and not force:
            self._stats["sessions_skipped"] += 1
            print(f"  ⏭ {sid[:12]}... (已导入，跳过)")
            return

        # 分块
        chunks = self.parser.session_to_chunks(session)
        self._stats["chunks_total"] += len(chunks)

        if self.dry_run:
            self._stats["sessions_imported"] += 1
            print(f"  📄 {sid[:12]}... → {len(chunks)} 块, {session.turn_count} 轮 "
                  f"[{session.project_name}]")
            if chunks:
                preview = chunks[0].content[:120].replace("\n", " ")
                print(f"     └ 预览: {preview}...")
            return

        # 写入 Chroma
        try:
            self._write_chunks(chunks)
            self._stats["sessions_imported"] += 1
            self._stats["chunks_imported"] += len(chunks)
            print(f"  ✅ {sid[:12]}... → {len(chunks)} 块 "
                  f"[{session.project_name}]")
        except Exception as e:
            self._stats["errors"] += 1
            print(f"  ❌ {sid[:12]}... 导入失败: {e}")
            logger.error("导入失败 session=%s: %s", sid, e)

    def _write_chunks(self, chunks: list[ConversationChunk]):
        """批量写入 Chroma"""
        if not self.is_available:
            return

        for i in range(0, len(chunks), CHROMA_BATCH_SIZE):
            batch = chunks[i:i + CHROMA_BATCH_SIZE]
            ids = [c.chunk_id for c in batch]
            documents = [c.content for c in batch]
            metadatas = [c.metadata for c in batch]

            self._collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

    def _seed_chronicle(self, sessions: list[CursorSession]):
        """从对话中提取 Chronicle 事件"""
        print("\n📜 提取 Chronicle 事件种子...")
        all_events = []
        for session in sessions:
            events = self.parser.extract_chronicle_events(session)
            all_events.extend(events)

        if not all_events:
            print("  无事件可提取")
            return

        print(f"  提取 {len(all_events)} 条事件")

        # 去重（按标题）
        seen_titles = set()
        unique_events = []
        for e in all_events:
            if e["title"] not in seen_titles:
                seen_titles.add(e["title"])
                unique_events.append(e)

        print(f"  去重后: {len(unique_events)} 条")

        # 写入 JSON 种子文件（供 chronicle/ingest.py 使用）
        seed_dir = Path(config.DB_DIR) / "chronicle_seeds"
        seed_dir.mkdir(parents=True, exist_ok=True)
        seed_file = seed_dir / f"cursor_seed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(seed_file, "w", encoding="utf-8") as f:
            json.dump(unique_events, f, ensure_ascii=False, indent=2)

        print(f"  💾 种子文件: {seed_file}")
        print(f"  💡 运行 chronicle 导入: python -m chronicle.ingest --seed {seed_file}")

    # ===== 搜索 =====

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """在已导入的对话中语义搜索"""
        if not self.is_available:
            return []

        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
        )

        hits = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                distance = results.get("distances", [[0]] * top_k)[0][i]
                # squared L2 → cosine similarity
                similarity = max(0.0, min(1.0, 1.0 - distance / 2.0))
                hits.append({
                    "id": results["ids"][0][i],
                    "content": results["documents"][0][i][:500],
                    "metadata": results.get("metadatas", [[{}]])[0][i],
                    "similarity": round(similarity, 4),
                })

        return hits

    # ===== 统计 =====

    def get_stats(self) -> dict:
        """获取 collection 统计"""
        if not self.is_available:
            return {"available": False}

        count = self._collection.count()
        return {
            "available": True,
            "collection": COLLECTION_NAME,
            "total_vectors": count,
            **self._stats,
        }

    def _print_summary(self):
        """打印导入汇总"""
        s = self._stats
        print("\n" + "=" * 60)
        print("  导入汇总")
        print("=" * 60)
        print(f"  会话总数:    {s['sessions_total']}")
        print(f"  已导入:      {s['sessions_imported']}")
        print(f"  已跳过:      {s['sessions_skipped']}")
        print(f"  分块总数:    {s['chunks_total']}")
        print(f"  已入库分块:  {s['chunks_imported']}")
        print(f"  总字符数:    {s['chars_total']:,}")
        if s["errors"]:
            print(f"  错误:        {s['errors']}")
        if self.is_available:
            print(f"  Collection:  {self._collection.count()} 向量")
        print("=" * 60)

        if not self.dry_run and s["sessions_imported"] > 0:
            print("\n💡 使用方式:")
            print("  # 在 Web 面板中搜索对话")
            print(f"  http://{config.WEB_HOST}:{config.WEB_PORT}/query")
            print()
            print("  # 或在代码中:")
            print("  from scripts.import_cursor_transcripts import CursorImporter")
            print("  importer = CursorImporter()")
            print("  results = importer.search('SmartJobs 的 Consul 配置')")
            print()


# ===== CLI =====

def main():
    parser = argparse.ArgumentParser(
        description="导入 Cursor AI 对话到 DemoPeter RAG 知识库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/import_cursor_transcripts.py --dry-run
  python scripts/import_cursor_transcripts.py
  python scripts/import_cursor_transcripts.py --project Nezha
  python scripts/import_cursor_transcripts.py --chronicle --force
        """,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：扫描但不写入 Chroma",
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="仅导入指定项目（按目录名或项目名过滤）",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="强制重新导入所有会话（忽略去重）",
    )
    parser.add_argument(
        "--chronicle", action="store_true",
        help="同时生成 Chronicle 事件种子文件",
    )
    parser.add_argument(
        "--search", type=str, default=None,
        help="在已导入的对话中搜索（测试用）",
    )

    args = parser.parse_args()

    # 搜索模式
    if args.search:
        importer = CursorImporter(dry_run=False)
        if not importer.is_available:
            print("❌ Chroma 不可用，无法搜索")
            return
        print(f"\n🔍 搜索: {args.search}\n")
        results = importer.search(args.search, top_k=5)
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r['metadata'].get('project_name', '?')}] "
                  f"相似度={r['similarity']}")
            print(f"   {r['content'][:200]}...\n")
        return

    # 导入模式
    importer = CursorImporter(dry_run=args.dry_run)
    try:
        importer.import_all(
            project_filter=args.project,
            force=args.force,
            with_chronicle=args.chronicle,
        )
    except KeyboardInterrupt:
        print("\n⚠ 用户中断")
    except Exception as e:
        print(f"\n❌ 导入失败: {e}")
        logger.exception("导入异常")


if __name__ == "__main__":
    main()
