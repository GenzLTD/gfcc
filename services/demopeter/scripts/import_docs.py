"""
szpeter2026 - 批量文档导入脚本
用法：python scripts/import_docs.py [--path 文档目录]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import config
from src.db_manager import DBManager
from src.doc_processor import DocumentProcessor
from src.vector_store import VectorStore
from src.pgvector_store import PgvectorStore
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

console = Console()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="导入文档到 szpeter2026 知识库")
    parser.add_argument("--path", default=str(config.DOCS_DIR), help="文档目录路径")
    parser.add_argument("--force", action="store_true", help="强制重新导入已存在的文档")
    args = parser.parse_args()

    db = DBManager()
    processor = DocumentProcessor()
    vector_store = VectorStore()
    pgvector_store = PgvectorStore()

    doc_dir = Path(args.path)
    if not doc_dir.exists():
        console.print(f"[red]❌ 目录不存在: {doc_dir}[/red]")
        return

    console.print(f"\n[bold cyan]📥 szpeter2026 文档导入[/bold cyan]")
    console.print(f"  目录: {doc_dir}")
    console.print(f"  Chroma: {'[green]可用[/green]' if vector_store.is_available else '[yellow]不可用[/yellow]'}")
    console.print()

    # 扫描文件
    files = processor.scan_directory(doc_dir)
    console.print(f"  发现 [bold]{len(files)}[/bold] 个可导入文件\n")

    if not files:
        console.print("[yellow]⚠️  没有可导入的文件[/yellow]")
        return

    # 获取已存在的文件
    if not args.force:
        existing = {d.get("file_path", "") for d in db.get_documents() if isinstance(d, dict)}
    else:
        existing = set()

    success = 0
    skipped = 0
    failed = 0

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}")
    ) as progress:
        task = progress.add_task("导入中...", total=len(files))

        for file_info in files:
            progress.update(task, description=f"处理: {file_info['title'][:40]}")

            if file_info["file_path"] in existing:
                skipped += 1
                progress.advance(task)
                continue

            try:
                doc_id = db.register_document(
                    title=file_info["title"],
                    file_path=file_info["file_path"],
                    doc_type=file_info["doc_type"],
                    file_size=file_info.get("file_size", 0),
                )
                _, chunks = processor.process_file(file_info["file_path"])
                db.save_chunks(doc_id, chunks)

                if vector_store.is_available:
                    vector_store.add_documents(str(doc_id), chunks)

                if pgvector_store.is_available:
                    pgvector_store.add_documents(doc_id, chunks)

                db.update_document_status(doc_id, "completed", len(chunks))
                success += 1

            except Exception as e:
                console.print(f"  [red]✗ {file_info['title']}: {e}[/red]")
                failed += 1

            progress.advance(task)

    # 汇总
    stats = db.get_stats()
    console.print(f"\n[bold green]✅ 导入完成！[/bold green]")
    console.print(f"  成功: {success} | 跳过: {skipped} | 失败: {failed}")

    # 知识库统计
    table = Table(title="知识库统计")
    table.add_column("指标", style="cyan")
    table.add_column("数值", style="green")
    table.add_row("文档总数", str(stats["documents_total"]))
    table.add_row("已处理", str(stats["documents_completed"]))
    table.add_row("分块总数", str(stats["chunks_total"]))
    table.add_row("总字符数", f"{stats['total_characters']:,}")
    console.print(table)


if __name__ == "__main__":
    main()
