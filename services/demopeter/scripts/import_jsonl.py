#!/usr/bin/env python3
"""
从预处理 JSONL 批量入库 DemoPeter 知识库
用法:
  python scripts/import_jsonl.py                          # 默认导入 md_import_staging/processed/documents.jsonl
  python scripts/import_jsonl.py --file /path/to/file.jsonl
  python scripts/import_jsonl.py --force                  # 强制重新导入已存在的文档
  python scripts/import_jsonl.py --label my_corpus       # 自定义 corpus label
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table

from src.kb_service import KnowledgeBaseService, ImportSummary

console = Console()
DEFAULT_JSONL = PROJECT_ROOT / "md_import_staging" / "processed" / "documents.jsonl"


def main():
    parser = argparse.ArgumentParser(description="从预处理 JSONL 批量入库")
    parser.add_argument("--file", default=str(DEFAULT_JSONL), help="JSONL 文件路径")
    parser.add_argument("--force", action="store_true", help="强制重新导入已存在的文档")
    parser.add_argument("--label", default="md_import_staging", help="corpus label")
    args = parser.parse_args()

    jsonl_path = Path(args.file).resolve()
    if not jsonl_path.exists():
        console.print(f"[red]❌ 文件不存在: {jsonl_path}[/red]")
        sys.exit(1)

    # 读取 JSONL
    with open(jsonl_path, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    console.print(f"\n[bold cyan]📥 JSONL 批量入库[/bold cyan]")
    console.print(f"  文件: {jsonl_path.name}")
    console.print(f"  记录数: {len(records):,}")
    console.print(f"  label: {args.label}")
    console.print(f"  force: {args.force}")
    console.print()

    kb = KnowledgeBaseService()

    # 显示导入前状态
    stats_before = kb.stats()
    console.print(f"[dim]导入前: {stats_before['documents_total']} 文档 / {stats_before['chunks_total']} 分块[/dim]\n")

    # 调用 import_jsonl
    t0 = time.time()
    summary = kb.import_jsonl(
        str(jsonl_path),
        force=args.force,
        label=args.label,
    )

    # ---------- 结果展示 ----------
    elapsed = round(time.time() - t0, 1)

    console.print(f"\n[bold green]✅ 入库完成！({elapsed}s)[/bold green]\n")

    result_table = Table(title="入库结果")
    result_table.add_column("指标", style="cyan")
    result_table.add_column("数值", style="green", justify="right")
    result_table.add_row("总数", str(summary.total))
    result_table.add_row("成功", str(summary.success))
    result_table.add_row("跳过", str(summary.skipped))
    result_table.add_row("失败", str(summary.failed))
    result_table.add_row("耗时 (s)", str(summary.elapsed_sec))
    for label_name, n in summary.by_corpus.items():
        result_table.add_row(f"  └ {label_name}", str(n))
    console.print(result_table)

    if summary.errors:
        console.print("\n[yellow]⚠️  错误样例:[/yellow]")
        for err in summary.errors[:10]:
            console.print(f"  [dim]{err}[/dim]")

    # 导入后状态
    stats_after = kb.stats()
    console.print(f"\n[bold]知识库现状[/bold]")
    final = Table()
    final.add_column("指标", style="cyan")
    final.add_column("数值", style="green", justify="right")
    final.add_row("文档总数", str(stats_after["documents_total"]))
    final.add_row("已处理", str(stats_after["documents_completed"]))
    final.add_row("分块总数", str(stats_after["chunks_total"]))
    final.add_row("总字符数", f"{stats_after['total_characters']:,}")
    final.add_row("Chroma 集合", str(stats_after.get("vector", {}).get("count", "N/A")))
    console.print(final)


if __name__ == "__main__":
    main()
