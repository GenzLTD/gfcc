"""调试 list_projects 为何返回空"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "static"))

from d_indexer.indexer import DIndexer
from d_indexer.scanner import DScanner, ScanConfig
from d_indexer.projects import D_PROJECT_ROOTS
from d_indexer.checkpoint import ScanCheckpoint

cp = ScanCheckpoint()
scanner = DScanner(ScanConfig(project_roots=D_PROJECT_ROOTS))
idx = DIndexer(scanner=scanner, persist_dir="db/d_index_data", checkpoint=cp)

print(f"available={idx.is_available}")
print(f"count={idx._collection.count()}")

# 1. peek 看元数据结构
try:
    p = idx._collection.peek(limit=3)
    print(f"\npeek ids: {p.get('ids', [])}")
    metas = p.get('metadatas', [])
    if metas:
        print(f"peek meta keys: {list(metas[0].keys())}")
        print(f"peek meta sample: {metas[0]}")
    else:
        print("NO METADATA returned from peek!")
except Exception as e:
    print(f"peek error: {e}")

# 2. where 查询
try:
    r = idx._collection.get(where={"project_name": "jobfirst-claw"}, limit=3, include=["metadatas"])
    print(f"\nwhere jobfirst-claw: {len(r.get('ids', []))} results")
    m = r.get("metadatas", [])
    if m:
        print(f"  meta sample: {m[0]}")
    else:
        print("  NO METADATA")
except Exception as e:
    print(f"where error: {e}")
    import traceback
    traceback.print_exc()

# 3. get without where
try:
    r = idx._collection.get(limit=3, include=["metadatas"])
    print(f"\nget(limit=3): {len(r.get('ids', []))} results")
    m = r.get("metadatas", [])
    if m:
        print(f"  meta sample: {m[0]}")
    else:
        print("  NO METADATA")
except Exception as e:
    print(f"get limit error: {e}")

# 4. 直接测 list_projects
print("\n=== list_projects ===")
result = idx.list_projects()
print(f"result: {result}")
