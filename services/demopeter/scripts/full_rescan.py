"""
全量重新扫描 D-Indexer
重置所有 checkpoint 并从头开始索引所有项目
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from d_indexer.scanner import DScanner, ScanConfig
from d_indexer.indexer import DIndexer
from d_indexer.checkpoint import ScanCheckpoint
from d_indexer.projects import D_PROJECT_ROOTS
from config.settings import config as app_config
from config.logging_config import setup_logging

setup_logging()

# ===== 1. 重置所有 checkpoint =====
print("=" * 60)
print("1. 重置所有 checkpoint")
print("=" * 60)

cp = ScanCheckpoint()
progress_before = cp.get_all_progress()
print(f"  当前状态: {len(progress_before)} 个项目")

# 统计哪些项目实际有索引数据
has_data = sum(1 for p in progress_before if p.chunks_indexed > 0)
no_data = sum(1 for p in progress_before if p.chunks_indexed == 0)
print(f"  有索引数据: {has_data}  无索引数据: {no_data}")

# 重置所有项目
cp.reset_all()
# 同时清除所有文件索引缓存（否则 indexer 会误以为文件未变更而跳过）
import sqlite3
db_path = app_config.METADATA_DB
conn = sqlite3.connect(db_path)
cache_count = conn.execute("SELECT COUNT(*) FROM indexed_files_cache").fetchone()[0]
conn.execute("DELETE FROM indexed_files_cache")
conn.commit()
conn.close()
print(f"  已重置所有 checkpoint + 清除 {cache_count} 条文件缓存")

# ===== 2. 初始化扫描器 =====
print("\n" + "=" * 60)
print("2. 初始化扫描器")
print("=" * 60)

scanner = DScanner(ScanConfig(project_roots=D_PROJECT_ROOTS))
indexer = DIndexer(
    scanner=scanner,
    persist_dir=str(app_config.PROJECT_ROOT / "db" / "d_index_data"),
    checkpoint=cp,
)

# 清空 ChromaDB collection 以完全重建
if indexer.is_available and indexer.count > 0:
    old_count = indexer.count
    indexer.clear_index()
    # 重建 indexer（clear_index 会重建 collection）
    indexer = DIndexer(
        scanner=scanner,
        persist_dir=str(app_config.PROJECT_ROOT / "db" / "d_index_data"),
        checkpoint=cp,
    )
    print(f"  ChromaDB 可用: {indexer.is_available}")
    print(f"  已清空旧向量:   {old_count} -> {indexer.count}")
else:
    print(f"  ChromaDB 可用: {indexer.is_available}")
    print(f"  当前向量数:     {indexer.count}")
print(f"  项目总数:       {len(D_PROJECT_ROOTS)}")

# ===== 3. 全量扫描 =====
print("\n" + "=" * 60)
print("3. 开始全量扫描（将按项目顺序依次处理）")
print("=" * 60)

# 注意：index_with_resume(resume=False) 会强制重置每个项目的 checkpoint
# 但我们已经全局重置过了，用 resume=True 让每个项目从零开始（因为 checkpoint 都是 pending）
result = indexer.index_with_resume(resume=True)

# ===== 4. 结果汇总 =====
print("\n" + "=" * 60)
print("4. 扫描完成汇总")
print("=" * 60)
print(f"  总文件数:     {result.total_files}")
print(f"  新增 chunks:  {result.new_chunks}")
print(f"  跳过文件:     {result.skipped_files}")
print(f"  耗时:         {result.scan_duration_seconds:.1f}s")
print(f"  ChromaDB 总数: {indexer.count}")

# 检查各项目最终状态
print("\n  各项目最终状态:")
final_progress = cp.get_all_progress()
for p in final_progress:
    name = p.project_root.split("/")[-1]
    status_icon = "✓" if p.status == "completed" else "✗"
    print(f"    {status_icon} {name:<30} scanned={p.files_scanned:>6}  "
          f"indexed={p.files_indexed:>6}  chunks={p.chunks_indexed:>8}")
