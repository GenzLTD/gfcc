"""
将 D:/surface-zervi/DemoPeter/db/chroma_data 中的集合迁移到 merged_chroma

策略：用 sqlite3 只读 URI 直接读取 Chroma 底层数据库，无需 Chroma 客户端打开源库
     → 避免沙箱对 WAL journal 文件的写权限拦截
     → 读 embedding_metadata 表获取文档内容和元数据
     → HNSW 向量文件单独存放在同级目录，通过文件名找到对应 segment，直接读 binary 或重新 embed

注意：Chroma 1.x 的向量存在 HNSW 二进制文件中（非 SQLite），重新 embed 成本高。
      本脚本优先尝试直接读取 HNSW 文件，失败则 fallback 到重新 embed（需 Ollama/API）。

      实际上更简单的方法：先用 sqlite3 导出 doc+meta，再用 Chroma 默认 EF 重新 embed。
      cursor_conversations 只有 1939 条，重新 embed 约 2-3 分钟。

目标集合：cursor_conversations, chronicle, szpeter2026_kb
"""
import sys
import os
import json
import sqlite3
import time
import struct

sys.path.insert(0, "static")
sys.path.insert(0, ".")
import bootstrap_paths  # noqa

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

SRC_DB     = "D:/surface-zervi/DemoPeter/db/chroma_data/chroma.sqlite3"
SRC_DIR    = "D:/surface-zervi/DemoPeter/db/chroma_data"
DST_PATH   = "db/merged_chroma"
BATCH_SIZE = 100

COLLECTIONS_TO_IMPORT = ["cursor_conversations", "chronicle", "szpeter2026_kb"]


def read_src_collections(src_db: str) -> dict:
    """用 sqlite3 只读模式读取集合基本信息"""
    con = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    cur = con.cursor()

    cur.execute("SELECT id, name FROM collections ORDER BY name")
    cols = {name: cid for cid, name in cur.fetchall()}

    cur.execute("SELECT id, scope, collection FROM segments")
    segs = cur.fetchall()

    seg_map = {}  # collection_id -> {METADATA: seg_id, VECTOR: seg_id}
    for seg_id, scope, col_id in segs:
        seg_map.setdefault(col_id, {})[scope] = seg_id

    con.close()
    return cols, seg_map


def export_collection_sqlite(src_db: str, meta_seg_id: str) -> list:
    """
    从 embedding_metadata 表重建 documents 和 metadata。
    Chroma 将每个字段存为独立行，需要 pivot。
    返回 list of {id, document, metadata}
    """
    con = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    cur = con.cursor()

    # embedding_metadata: id=embedding_rowid, key, string_value/int_value/float_value/bool_value
    # 先拿所有 rowid 属于这个 segment 的 embeddings
    cur.execute(
        "SELECT id, embedding_id FROM embeddings WHERE segment_id=? ORDER BY id",
        (meta_seg_id,),
    )
    emb_rows = cur.fetchall()  # (rowid, embedding_id_str)

    rowid2eid = {rowid: eid for rowid, eid in emb_rows}
    all_rowids = list(rowid2eid.keys())

    if not all_rowids:
        con.close()
        return []

    # 读取所有 metadata
    placeholders = ",".join("?" * len(all_rowids))
    cur.execute(
        f"SELECT id, key, string_value, int_value, float_value, bool_value "
        f"FROM embedding_metadata WHERE id IN ({placeholders})",
        all_rowids,
    )
    meta_rows = cur.fetchall()

    # 读取 fulltext search content (document text)
    cur.execute(
        f"SELECT rowid, c0 FROM embedding_fulltext_search_content WHERE rowid IN ({placeholders})",
        all_rowids,
    )
    fts_rows = {rowid: c0 for rowid, c0 in cur.fetchall()}

    con.close()

    # Pivot metadata
    meta_map = {}  # rowid -> {key: value}
    for rowid, key, sv, iv, fv, bv in meta_rows:
        if rowid not in meta_map:
            meta_map[rowid] = {}
        if sv is not None:
            meta_map[rowid][key] = sv
        elif iv is not None:
            meta_map[rowid][key] = iv
        elif fv is not None:
            meta_map[rowid][key] = fv
        elif bv is not None:
            meta_map[rowid][key] = bool(bv)

    records = []
    for rowid, eid in rowid2eid.items():
        doc = fts_rows.get(rowid, "")
        meta = meta_map.get(rowid, {})
        records.append({"id": eid, "document": doc or "", "metadata": meta})

    return records


def fmt(n):
    return f"{n:,}"


def migrate_collection(
    src_db: str, dst_client, col_name: str, meta_seg_id: str, dry_run: bool = False
):
    print(f"\n{'='*60}")
    print(f"  集合: {col_name}  (meta_seg={meta_seg_id[:8]}...)")
    print(f"{'='*60}")

    records = export_collection_sqlite(src_db, meta_seg_id)
    total = len(records)
    print(f"  从 SQLite 读取: {fmt(total)} 条记录")

    if total == 0:
        print("  [SKIP] 无记录")
        return 0

    if dry_run:
        sample = records[:2]
        print(f"  [DRY-RUN] 样本:")
        for r in sample:
            print(f"    id={r['id'][:16]}... doc={r['document'][:80]} meta={r['metadata']}")
        print(f"  [DRY-RUN] 将向 merged_chroma 写入 {fmt(total)} 条（重新 embed）")
        return total

    # 目标集合
    dst_col = dst_client.get_or_create_collection(
        name=col_name,
        metadata={"hnsw:space": "cosine"},
    )

    # 获取目标库已有 id（去重）
    existing_ids = set(dst_col.get(include=[])["ids"])
    print(f"  目标库已有: {fmt(len(existing_ids))} 条，将过滤重复")

    new_records = [r for r in records if r["id"] not in existing_ids]
    print(f"  需要写入: {fmt(len(new_records))} 条（跳过 {fmt(total - len(new_records))} 重复）")

    if not new_records:
        print("  [SKIP] 全部重复，无需写入")
        return 0

    ef = DefaultEmbeddingFunction()
    new_cnt = 0
    err_cnt = 0
    t0 = time.time()

    for i in range(0, len(new_records), BATCH_SIZE):
        batch = new_records[i : i + BATCH_SIZE]
        ids   = [r["id"] for r in batch]
        docs  = [r["document"] for r in batch]
        # 过滤掉旧版 Chroma 内部保留键（chroma:document 等），新版 Chroma 1.x 不允许
        metas = [
            {k: v for k, v in r["metadata"].items() if not k.startswith("chroma:")}
            for r in batch
        ]

        # 重新 embed（DefaultEmbeddingFunction 使用 all-MiniLM-L6-v2，384维）
        try:
            embeddings = ef(docs)
            dst_col.add(
                ids=ids,
                embeddings=embeddings,
                documents=docs,
                metadatas=metas,
            )
            new_cnt += len(batch)
        except Exception as e:
            print(f"\n  [ERROR] batch {i}: {e}")
            err_cnt += len(batch)

        done = min(i + BATCH_SIZE, len(new_records))
        elapsed = time.time() - t0
        pct = done / len(new_records) * 100
        print(
            f"  进度: {fmt(done)}/{fmt(len(new_records))} ({pct:.1f}%) "
            f"| 新增 {fmt(new_cnt)} | 耗时 {elapsed:.0f}s",
            end="\r",
        )

    print()
    print(f"  ✅ 完成: 新增 {fmt(new_cnt)} | 错误 {fmt(err_cnt)}")
    return new_cnt


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("【DRY-RUN 模式】只统计，不写入")

    print(f"\n源库 SQLite: {SRC_DB}")
    print(f"目标库: {DST_PATH}")

    # 读源库集合信息（只读 sqlite3）
    col_ids, seg_map = read_src_collections(SRC_DB)
    print(f"\n源库集合:")
    for name, cid in col_ids.items():
        segs = seg_map.get(cid, {})
        meta_seg = segs.get("METADATA", "N/A")
        marker = "→ 将迁移" if name in COLLECTIONS_TO_IMPORT else "  (跳过)"
        print(f"  {marker} [{name}]  col_id={cid[:8]}...  meta_seg={str(meta_seg)[:8]}...")

    if not dry_run:
        dst_client = chromadb.PersistentClient(path=DST_PATH)
        print(f"\n目标库现有集合:")
        for c in dst_client.list_collections():
            col = dst_client.get_collection(c.name)
            print(f"  [{c.name}]  {col.count():,}")
    else:
        dst_client = None

    total_new = 0
    t0 = time.time()

    for col_name in COLLECTIONS_TO_IMPORT:
        if col_name not in col_ids:
            print(f"\n[SKIP] {col_name} 不在源库中")
            continue
        cid = col_ids[col_name]
        meta_seg_id = seg_map.get(cid, {}).get("METADATA")
        if not meta_seg_id:
            print(f"\n[SKIP] {col_name} 没有 METADATA segment")
            continue
        added = migrate_collection(SRC_DB, dst_client, col_name, meta_seg_id, dry_run=dry_run)
        total_new += added

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  全部完成！共新增 {fmt(total_new)} 条，耗时 {elapsed:.1f}s")

    if not dry_run:
        print(f"\n目标库最终状态:")
        for c in dst_client.list_collections():
            col = dst_client.get_collection(c.name)
            print(f"  [{c.name}]  {col.count():,} vectors")


if __name__ == "__main__":
    main()
