"""
扫描结果验证脚本
检查断点状态、缓存统计，并尝试语义搜索验证索引可用性
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from d_indexer.checkpoint import ScanCheckpoint
from d_indexer.indexer import DIndexer
from d_indexer.scanner import DScanner, ScanConfig
from d_indexer.projects import D_PROJECT_ROOTS
from config.settings import config as app_config

# ===== 1. 断点状态 =====
print("=" * 60)
print("1.  CHECKPOINT 状态")
print("=" * 60)

cp = ScanCheckpoint()
progress = cp.get_all_progress()

status_count = {"completed": 0, "in_progress": 0, "pending": 0, "failed": 0}
total_files_scanned = 0
total_files_indexed = 0
total_chunks = 0

for p in progress:
    status_count[p.status] = status_count.get(p.status, 0) + 1
    total_files_scanned += p.files_scanned
    total_files_indexed += p.files_indexed
    total_chunks += p.chunks_indexed
    name = p.project_root.split("/")[-1] if "/" in p.project_root else p.project_root
    print(f"  [{p.status:>11}] {name:<30} scanned={p.files_scanned:>6}  "
          f"indexed={p.files_indexed:>6}  chunks={p.chunks_indexed:>8}  "
          f"dirs_done={len(p.completed_dirs):>4}")

print(f"\n  completed: {status_count['completed']}  "
      f"in_progress: {status_count['in_progress']}  "
      f"pending: {status_count['pending']}  "
      f"failed: {status_count['failed']}")
print(f"  files_scanned={total_files_scanned}  "
      f"files_indexed={total_files_indexed}  "
      f"chunks={total_chunks}")

# 检查缺失项目
tracked = set(p.project_root for p in progress)
missing = [r for r in D_PROJECT_ROOTS if r not in tracked]
if missing:
    print(f"\n  WARN: {len(missing)} projects not yet tracked:")
    for m in missing:
        print(f"    - {m}")

# ===== 2. 文件缓存 =====
print("\n" + "=" * 60)
print("2.  文件索引缓存")
print("=" * 60)

cs = cp.get_cache_stats()
print(f"  已缓存文件: {cs['total_cached_files']}")
for r in cs['by_project'][:15]:
    print(f"    {r['project']:<35} {r['files']:>6} files")
if len(cs['by_project']) > 15:
    print(f"    ... and {len(cs['by_project']) - 15} more")

# ===== 3. ChromaDB 可用性 =====
print("\n" + "=" * 60)
print("3.  ChromaDB 可用性 + 搜索测试")
print("=" * 60)

scanner = DScanner(ScanConfig(project_roots=D_PROJECT_ROOTS))
indexer = DIndexer(
    scanner=scanner,
    persist_dir=str(app_config.PROJECT_ROOT / "db" / "d_index_data"),
    checkpoint=cp,
)

print(f"  ChromaDB 可用: {indexer.is_available}")
print(f"  Collection:    d_drive_index")
print(f"  向量总数:      {indexer.count}")

# 尝试搜索
if indexer.is_available and indexer.count > 0:
    test_queries = [
        "用户认证登录",
        "数据库连接",
        "Rust 异步处理",
        "跨境电商",
    ]
    print(f"\n  搜索测试:")
    for q in test_queries:
        results = indexer.search(q, top_k=3)
        if results:
            top = results[0]
            print(f"    Q: {q}")
            print(f"       -> {top.file_path.split('/')[-1]} "
                  f"({top.project_name}, sim={top.similarity:.3f})")
        else:
            print(f"    Q: {q} -> NO RESULTS")
else:
    print("\n  SKIP: ChromaDB 不可用或为空")

# ===== 4. 检查 in_progress 项目是否可以续传 =====
print("\n" + "=" * 60)
print("4.  续传就绪检查")
print("=" * 60)

incomplete = [p for p in progress if p.status == "in_progress"]
if incomplete:
    print(f"  有 {len(incomplete)} 个项目未完成，可续传:")
    for p in incomplete:
        name = p.project_root.split("/")[-1]
        print(f"    {name}: {len(p.completed_dirs)} dirs done, "
              f"current: {p.current_dir or 'N/A'}")
else:
    print("  所有项目已完成或未开始")

# ===== 5. 汇总 =====
print("\n" + "=" * 60)
print("5.  健康度汇总")
print("=" * 60)

issues = []

if total_chunks == 0:
    issues.append("RED: 零 chunks — 扫描可能从未成功运行")
elif total_chunks < 100:
    issues.append(f"YELLOW: 仅 {total_chunks} chunks — 可能扫描不完整")

if indexer.count == 0:
    issues.append("RED: ChromaDB 为空 — 索引数据未写入")

if indexer.count > 0 and indexer.count < total_chunks * 0.5:
    issues.append(f"YELLOW: ChromaDB ({indexer.count}) 远小于 checkpoint chunks ({total_chunks})")

if missing:
    issues.append(f"YELLOW: {len(missing)} 个配置项目尚未开始扫描")

if incomplete:
    issues.append(f"INFO: {len(incomplete)} 个项目可以续传")

if not issues:
    print("  ALL GOOD — 扫描正常运行中")
else:
    for i in issues:
        print(f"  {i}")

print(f"\n  ChromaDB 数据大小: ~2044 MB (db/d_index_data/)")
print(f"  配置项目总数: {len(D_PROJECT_ROOTS)}")
print(f"  已索引 chunk:  {indexer.count} (ChromaDB) / {total_chunks} (checkpoint)")
