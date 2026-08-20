"""
Chronicle 批量播种 — 从 JSON 种子文件导入事件到 Chroma

使用方式:
  # 导入 import_cursor_transcripts.py 生成的种子文件
  python -m scripts.seed_chronicle --seed db/chronicle_seeds/cursor_seed_20260612_090000.json

  # 或直接从 Cursor 对话生成并导入
  python -m scripts.seed_chronicle --from-cursor
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT / "static"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse
import io
import json
import os
from datetime import datetime

# 强制 UTF-8 输出
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config.settings import config
from config.logging_config import get_logger

logger = get_logger("chronicle_seed")


def load_seed_file(seed_path: str) -> list[dict]:
    """加载种子 JSON 文件"""
    with open(seed_path, "r", encoding="utf-8") as f:
        events = json.load(f)
    print(f"📂 加载 {len(events)} 条事件: {seed_path}")
    return events


def import_to_chronicle(events: list[dict]) -> int:
    """将事件列表导入 Chronicle Chroma collection"""
    try:
        from chronicle.schema import ChronicleEvent, EventType, ProjectTag
        from chronicle.ingest import ChronicleIngest
    except ImportError as e:
        print(f"❌ 无法导入 chronicle 模块: {e}")
        return 0

    # 初始化 Chronicle 写入器
    ingester = ChronicleIngest(
        persist_dir=config.CHROMA_PERSIST_DIR,
        ollama_url=config.OLLAMA_BASE_URL,
        embedding_model=config.OLLAMA_EMBEDDING_MODEL,
    )

    imported = 0
    skipped = 0

    for i, raw in enumerate(events):
        try:
            # 映射事件类型
            event_type_map = {
                "决策": EventType.DECISION,
                "操作": EventType.ACTION,
                "发现": EventType.DISCOVERY,
                "配置": EventType.CONFIG,
                "对话": EventType.CONVERSATION,
            }
            event_type = event_type_map.get(raw.get("event_type", "对话"), EventType.CONVERSATION)

            # 映射项目标签
            project_name = raw.get("project", "DemoPeter")
            try:
                project_tag = ProjectTag(project_name)
            except ValueError:
                # 不在枚举中的项目，使用字符串
                project_tag = project_name

            event = ChronicleEvent(
                title=raw.get("title", f"事件 #{i}"),
                event_type=event_type,
                full_text=raw.get("full_text", ""),
                project=project_tag,
                summary=raw.get("summary", ""),
                tags=raw.get("tags", []),
                participants=raw.get("participants", ["Cursor AI"]),
                source=raw.get("source", "cursor_transcript"),
                metadata=raw.get("metadata", {}),
            )

            ingester.ingest(event)
            imported += 1

            if (imported % 50) == 0:
                print(f"  已导入 {imported}/{len(events)}...")

        except Exception as e:
            skipped += 1
            if skipped <= 3:
                print(f"  ⚠ 跳过事件 #{i}: {e}")

    print(f"✅ 导入完成: {imported} 条成功, {skipped} 条跳过")
    print(f"   Chronicle 总量: {ingester.count} 条")
    return imported


def from_cursor_direct() -> int:
    """直接从 Cursor 对话提取并导入 Chronicle"""
    from scripts.cursor_parser import CursorParser

    parser = CursorParser()
    sessions = parser.scan_all_projects(skip_temp=True)
    print(f"🔍 扫描到 {len(sessions)} 个 Cursor 会话")

    all_events = []
    for session in sessions:
        events = parser.extract_chronicle_events(session)
        all_events.extend(events)

    # 去重
    seen = set()
    unique = []
    for e in all_events:
        key = e["title"]
        if key not in seen:
            seen.add(key)
            unique.append(e)

    print(f"📊 提取 {len(all_events)} 条, 去重后 {len(unique)} 条")
    return import_to_chronicle(unique)


def main():
    parser = argparse.ArgumentParser(description="Chronicle 事件批量播种")
    parser.add_argument(
        "--seed", type=str, default=None,
        help="JSON 种子文件路径",
    )
    parser.add_argument(
        "--from-cursor", action="store_true",
        help="直接从 Cursor 对话提取事件",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：只显示统计，不写入",
    )

    args = parser.parse_args()

    if not args.seed and not args.from_cursor:
        parser.print_help()
        print("\n💡 示例:")
        print("  python -m scripts.seed_chronicle --from-cursor --dry-run")
        print("  python -m scripts.seed_chronicle --seed db/chronicle_seeds/cursor_seed_20260612.json")
        return

    if args.dry_run:
        if args.from_cursor:
            from scripts.cursor_parser import CursorParser
            p = CursorParser()
            sessions = p.scan_all_projects(skip_temp=True)
            events = []
            for s in sessions:
                events.extend(p.extract_chronicle_events(s))
            seen = set()
            unique = [e for e in events if e["title"] not in seen and not seen.add(e["title"])]
            print(f"🔍 预览: {len(sessions)} 会话 → {len(events)} 事件 → {len(unique)} 去重后")
            print("\n事件类型分布:")
            from collections import Counter
            type_dist = Counter(e["event_type"] for e in unique)
            for t, c in type_dist.most_common():
                print(f"  {t}: {c}")
            return

        if args.seed:
            events = load_seed_file(args.seed)
            print(f"🔍 预览: {len(events)} 条事件 (不写入)")
            return

    # 实际导入
    try:
        if args.from_cursor:
            from_cursor_direct()
        elif args.seed:
            events = load_seed_file(args.seed)
            import_to_chronicle(events)
    except KeyboardInterrupt:
        print("\n⚠ 用户中断")
    except Exception as e:
        print(f"❌ 错误: {e}")
        logger.exception("播种异常")


if __name__ == "__main__":
    main()
