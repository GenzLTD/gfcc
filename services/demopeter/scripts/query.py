"""
szpeter2026 - CLI 查询工具
用法：python scripts/query.py "你的问题"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bootstrap_paths  # noqa: F401

from src.rag_engine import RAGEngine
from src.vector_store import VectorStore
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


def main():
    if len(sys.argv) < 2:
        console.print("[red]用法: python scripts/query.py \"你的问题\"[/red]")
        return

    query_text = " ".join(sys.argv[1:])

    # 检查向量库
    vs = VectorStore()
    if not vs.is_available:
        console.print("[yellow]⚠️  Chroma 向量库不可用，将使用纯 AI 回答[/yellow]\n")

    rag = RAGEngine()

    console.print(f"\n[bold cyan]🔍 查询:[/bold cyan] {query_text}")
    console.print("[dim]正在检索知识库并生成回答...[/dim]\n")

    result = rag.query(query_text)

    # 输出回答
    console.print(Panel(
        result.answer,
        title="💡 回答",
        border_style="green",
        padding=(1, 2),
    ))

    # 输出元数据
    console.print(f"[dim]⏱ {result.response_time_ms:.0f}ms | 📚 {result.chunk_count} 块参考[/dim]")

    # 输出来源
    if result.sources:
        console.print("\n[bold]📚 参考来源:[/bold]")
        for i, src in enumerate(result.sources):
            console.print(f"  [{i + 1}] {src['source']} (相似度: {src['similarity']*100:.1f}%)")
            console.print(f"      {src['content'][:150]}...")
            console.print()


if __name__ == "__main__":
    main()
