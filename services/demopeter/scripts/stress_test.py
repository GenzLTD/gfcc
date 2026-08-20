#!/usr/bin/env python3
"""
DemoPeter 压测脚本 — 语料导入 + 检索延迟基准

示例:
  # 导入前 200 篇文档试跑
  python scripts/stress_test.py --limit 200

  # 全量导入 md_documents_collected 并跑检索基准
  python scripts/stress_test.py --full-import

  # 仅检索基准（跳过导入）
  python scripts/stress_test.py --search-only
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table

from config.settings import config
from src.kb_service import KnowledgeBaseService
from src.rag_engine import RAGEngine

console = Console()

DEFAULT_QUERIES = [
    "科锐国际2019年营业收入",
    "科锐国际第三季度报告主要业务",
    "pandas 数据清洗方法",
    "matplotlib 可视化图表",
    "scikit-learn 机器学习模型",
    "WorldCup 世界杯数据分析",
    "Kobe 篮球数据 CSV",
    "numpy 数组运算",
]


def run_import(kb: KnowledgeBaseService, corpus: Path, limit: int | None) -> dict:
    console.print(f"\n[bold cyan]📥 导入压测[/bold cyan]  目录: {corpus}")
    if limit:
        console.print(f"  限制: 前 {limit} 个文件")

    summary = kb.import_directory(corpus, limit=limit)
    stats = kb.stats()

    table = Table(title="导入结果")
    table.add_column("指标", style="cyan")
    table.add_column("数值", style="green")
    table.add_row("扫描文件", str(summary.total))
    table.add_row("成功", str(summary.success))
    table.add_row("跳过", str(summary.skipped))
    table.add_row("失败", str(summary.failed))
    table.add_row("耗时 (s)", str(summary.elapsed_sec))
    table.add_row("吞吐 (doc/s)", str(summary.docs_per_sec))
    table.add_row("文档总数", str(stats.get("documents_total", 0)))
    table.add_row("分块总数", str(stats.get("chunks_total", 0)))
    table.add_row("向量库", "可用" if stats.get("vector", {}).get("available") else "不可用")
    console.print(table)

    if summary.errors:
        console.print("[yellow]部分错误:[/yellow]")
        for err in summary.errors[:5]:
            console.print(f"  • {err}")

    return {
        "import": {
            "total": summary.total,
            "success": summary.success,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "elapsed_sec": summary.elapsed_sec,
            "docs_per_sec": summary.docs_per_sec,
        },
        "stats": stats,
    }


def run_search_benchmark(rag: RAGEngine, queries: list[str], top_k: int) -> dict:
    console.print(f"\n[bold cyan]🔍 检索压测[/bold cyan]  模式: {config.SEARCH_MODE}")
    latencies: list[float] = []
    modes: set[str] = set()
    hit_counts: list[int] = []

    table = Table(title="检索延迟")
    table.add_column("查询", style="cyan", max_width=40)
    table.add_column("模式", style="magenta")
    table.add_column("命中", style="green")
    table.add_column("ms", style="yellow")

    for q in queries:
        result = rag.search_only(q, top_k=top_k)
        ms = result["response_time_ms"]
        latencies.append(ms)
        modes.add(result["retrieval_mode"])
        hit_counts.append(len(result["hits"]))
        table.add_row(q[:38], result["retrieval_mode"], str(len(result["hits"])), f"{ms:.1f}")

    console.print(table)

    summary = {
        "queries": len(queries),
        "search_mode": config.SEARCH_MODE,
        "retrieval_modes": sorted(modes),
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else 0,
            "max": round(max(latencies), 2) if latencies else 0,
            "avg": round(statistics.mean(latencies), 2) if latencies else 0,
            "p50": round(statistics.median(latencies), 2) if latencies else 0,
        },
        "avg_hits": round(statistics.mean(hit_counts), 2) if hit_counts else 0,
    }

    console.print(
        f"\n[green]延迟 p50={summary['latency_ms']['p50']}ms "
        f"avg={summary['latency_ms']['avg']}ms "
        f"max={summary['latency_ms']['max']}ms[/green]"
    )
    return summary


def run_fused_import(kb: KnowledgeBaseService, limit_per_source: int | None) -> dict:
    console.print("\n[bold cyan]📥 融合语料导入压测[/bold cyan]")
    console.print("  科锐国际 + 数据分析与Python实战")
    if limit_per_source:
        console.print(f"  每个语料源限制: {limit_per_source} 个文件")

    summary = kb.import_fused_corpus(limit_per_source=limit_per_source)
    stats = kb.stats()

    table = Table(title="融合导入结果")
    table.add_column("指标", style="cyan")
    table.add_column("数值", style="green")
    table.add_row("扫描总数", str(summary.total))
    table.add_row("成功", str(summary.success))
    table.add_row("跳过", str(summary.skipped))
    table.add_row("失败", str(summary.failed))
    table.add_row("耗时 (s)", str(summary.elapsed_sec))
    table.add_row("吞吐 (doc/s)", str(summary.docs_per_sec))
    for label, n in summary.by_corpus.items():
        table.add_row(f"  └ {label}", str(n))
    table.add_row("文档总数", str(stats.get("documents_total", 0)))
    table.add_row("分块总数", str(stats.get("chunks_total", 0)))
    table.add_row("向量库", "可用" if stats.get("vector", {}).get("available") else "不可用")
    console.print(table)

    return {
        "mode": "fused",
        "sources": kb.list_corpus_sources(),
        "total": summary.total,
        "success": summary.success,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "elapsed_sec": summary.elapsed_sec,
        "docs_per_sec": summary.docs_per_sec,
        "by_corpus": summary.by_corpus,
    }


def main():
    parser = argparse.ArgumentParser(description="DemoPeter 知识库压测")
    parser.add_argument(
        "--corpus",
        default=None,
        help="单目录语料路径（指定后不使用融合语料）",
    )
    parser.add_argument(
        "--fused",
        action="store_true",
        default=None,
        help="使用融合语料（科锐国际 + Python实战，默认随 USE_FUSED_CORPUS）",
    )
    parser.add_argument("--limit", type=int, default=0, help="导入文件数上限（单目录或每语料源）")
    parser.add_argument("--full-import", action="store_true", help="全量导入语料")
    parser.add_argument("--search-only", action="store_true", help="跳过导入，仅检索压测")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--queries", default="", help="逗号分隔的自定义查询")
    parser.add_argument("--output", default="", help="JSON 报告输出路径")
    args = parser.parse_args()

    use_fused = args.fused
    if use_fused is None:
        use_fused = config.USE_FUSED_CORPUS and args.corpus is None

    corpus = Path(args.corpus).expanduser() if args.corpus else None
    queries = [q.strip() for q in args.queries.split(",") if q.strip()] or DEFAULT_QUERIES

    kb = KnowledgeBaseService()
    rag = RAGEngine()

    report: dict = {
        "mode": "fused" if use_fused else "single",
        "corpus": str(corpus) if corpus else "fused:careerintl+python_data_analysis",
        "search_mode": config.SEARCH_MODE,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if not args.search_only:
        if use_fused:
            limit = None if args.full_import else (args.limit or None)
            report["import_benchmark"] = run_fused_import(kb, limit)
        else:
            if corpus is None:
                corpus = config.DEFAULT_CORPUS_DIR
            if not corpus.exists():
                console.print(f"[red]语料目录不存在: {corpus}[/red]")
                sys.exit(1)
            limit = None if args.full_import else (args.limit or 100)
            report["import_benchmark"] = run_import(kb, corpus, limit)

    report["search_benchmark"] = run_search_benchmark(rag, queries, args.top_k)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"\n[dim]报告已写入 {out}[/dim]")


if __name__ == "__main__":
    main()
