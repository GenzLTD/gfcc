"""
D-Indexer 全量扫描进度监控
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from d_indexer.checkpoint import ScanCheckpoint
from d_indexer.projects import D_PROJECT_ROOTS

cp = ScanCheckpoint()
progress = cp.get_all_progress()

print("=" * 70)
print(f"D-Indexer 全量扫描进度监控")
print("=" * 70)

status_count = {"completed": 0, "in_progress": 0, "pending": 0, "failed": 0}
total_scanned = 0
total_indexed = 0
total_chunks = 0

for p in progress:
    status_count[p.status] = status_count.get(p.status, 0) + 1
    total_scanned += p.files_scanned
    total_indexed += p.files_indexed
    total_chunks += p.chunks_indexed
    name = p.project_root.split("/")[-1] if "/" in p.project_root else p.project_root
    dirs = len(p.completed_dirs)
    bar_len = min(30, int(dirs / max(1, dirs + 1) * 30)) if p.status == "in_progress" else (30 if p.status == "completed" else 0)
    bar = "█" * bar_len + "░" * (30 - bar_len)
    print(f"  [{p.status:>11}] {name:<30} |{bar}| scanned={p.files_scanned:>6} indexed={p.files_indexed:>6} chunks={p.chunks_indexed:>8} dirs={dirs:>4}")

print(f"\n  总计: completed={status_count['completed']} in_progress={status_count['in_progress']} pending={status_count['pending']} failed={status_count['failed']}")
print(f"  文件: scanned={total_scanned} indexed={total_indexed} chunks={total_chunks}")

# 检查缺失项目
tracked = set(p.project_root for p in progress)
missing = [r for r in D_PROJECT_ROOTS if r not in tracked]
if missing:
    print(f"\n  尚未开始的 {len(missing)} 个项目:")
    for m in missing:
        print(f"    - {m}")

# 估算进度
total_configured = len(D_PROJECT_ROOTS)
pct = status_count['completed'] / max(1, total_configured) * 100
print(f"\n  整体进度: {status_count['completed']}/{total_configured} 项目完成 ({pct:.0f}%)")
