#!/usr/bin/env python3
"""
融合语料导入 — 科锐国际 + 数据分析与Python实战

用法:
  python scripts/import_corpus.py              # 融合导入全部
  python scripts/import_corpus.py --list       # 预览可导入文件
  python scripts/import_corpus.py --force      # 强制重新导入
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table

from config.corpus_loader import load_corpus_sources
from src.kb_service import KnowledgeBaseService

console = Console()


def main():
    parser = argparse.ArgumentParser(description="融合导入 Projects 测试语料")
    parser.add_argument("--list", action="store_true", help="仅列出语料源与文件数")
    parser.add_argument("--force", action="store_true", help="强制重新导入")
    parser.add_argument("--limit", type=int, default=0, help="每个语料源最多导入 N 个文件")
    args = parser.parse_args()

    kb = KnowledgeBaseService()
    sources = load_corpus_sources()

    table = Table(title="融合语料源")
    table.add_column("ID", style="cyan")
    table.add_column("标签", style="green")
    table.add_column("路径")
    table.add_column("文件数", justify="right")

    for s in sources:
        exists = s.path.exists()
        count = len(kb.processor.scan_directory(s.path, corpus_label=s.label)) if exists else 0
        table.add_row(
            s.id,
            s.label,
            str(s.path) + ("" if exists else " [red](不存在)[/red]"),
            str(count),
        )
    console.print(table)

    if args.list:
        return

    limit = args.limit if args.limit > 0 else None
    console.print("\n[bold cyan]📥 开始融合导入...[/bold cyan]")
    summary = kb.import_fused_corpus(sources, force=args.force, limit_per_source=limit)

    result = Table(title="导入结果")
    result.add_column("指标", style="cyan")
    result.add_column("数值", style="green")
    result.add_row("扫描总数", str(summary.total))
    result.add_row("成功", str(summary.success))
    result.add_row("跳过", str(summary.skipped))
    result.add_row("失败", str(summary.failed))
    result.add_row("耗时 (s)", str(summary.elapsed_sec))
    for label, n in summary.by_corpus.items():
        result.add_row(f"  └ {label}", str(n))
    console.print(result)

    if summary.errors:
        console.print("[yellow]错误样例:[/yellow]")
        for err in summary.errors[:8]:
            console.print(f"  • {err}")


if __name__ == "__main__":
    main()
