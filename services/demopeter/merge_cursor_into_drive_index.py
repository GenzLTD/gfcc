"""
把 merged_chroma 中 cursor_conversations 集合的内容合并写入 d_drive_index。

策略：
  - 以 chunk_id 去重（前缀改为 cursor_ 避免与 d_drive_index 原有 id 冲突）
  - 在 metadata 中加 source_collection=cursor_conversations 标记
  - 重新 embed（DefaultEmbeddingFunction，384维，与 d_drive_index 一致）
  - 写入完成后，可选删除 cursor_conversations 集合（默认保留）

用法:
    python merge_cursor_into_drive_index.py [--dry-run] [--delete-src]
"""
import sys
import time

sys.path.insert(0, "static")
sys.path.insert(0, ".")
import bootstrap_paths  # noqa

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

MERGED_PATH = "db/merged_chroma"
SRC_COL     = "cursor_conversations"
DST_COL     = "d_drive_index"
BATCH_SIZE  = 100


def fmt(n):
    return f"{n:,}"


def main():
    dry_run    = "--dry-run" in sys.argv
    delete_src = "--delete-src" in sys.argv

    if dry_run:
        print("【DRY-RUN 模式】只统计，不写入\n")

    client = chromadb.PersistentClient(path=MERGED_PATH)

    src_col = client.get_collection(SRC_COL)
    dst_col = client.get_collection(DST_COL)

    src_cnt = src_col.count()
    dst_cnt = dst_col.count()
    print(f"源集合 [{SRC_COL}]: {fmt(src_cnt)} 条")
    print(f"目标集合 [{DST_COL}]: {fmt(dst_cnt)} 条（合并前）\n")

    # 读取 cursor_conversations 全量数据
    print("读取 cursor_conversations 数据…")
    all_ids   = []
    all_docs  = []
    all_metas = []

    page = 0
    page_size = 500
    while True:
        batch = src_col.get(
            limit=page_size,
            offset=page * page_size,
            include=["documents", "metadatas"],
        )
        ids   = batch.get("ids") or []
        docs  = batch.get("documents") or []
        metas = batch.get("metadatas") or []
        if not ids:
            break
        all_ids.extend(ids)
        all_docs.extend(docs)
        all_metas.extend(metas)
        page += 1
        print(f"  读取进度: {fmt(len(all_ids))}/{fmt(src_cnt)}", end="\r")

    print(f"\n  共读取 {fmt(len(all_ids))} 条记录")

    # 生成目标 id（加 cursor_ 前缀，避免与 d_drive_index 原有 id 冲突）
    # 检查目标库已有哪些 id
    print("\n检查去重…")
    existing = set(dst_col.get(include=[])["ids"])
    print(f"  目标库现有 id: {fmt(len(existing))} 条")

    new_ids   = []
    new_docs  = []
    new_metas = []

    for eid, doc, meta in zip(all_ids, all_docs, all_metas):
        # 为 cursor 来源的 id 加前缀，防止与 d_drive_index 原有 id 重复
        target_id = f"cursor_{eid}" if not eid.startswith("cursor_") else eid
        if target_id in existing:
            continue
        # 清理 chroma: 保留字，并打标记
        clean_meta = {k: v for k, v in (meta or {}).items() if not k.startswith("chroma:")}
        clean_meta["source_collection"] = "cursor_conversations"
        new_ids.append(target_id)
        new_docs.append(doc or "")
        new_metas.append(clean_meta)

    skip_cnt = len(all_ids) - len(new_ids)
    print(f"  需要写入: {fmt(len(new_ids))} 条（跳过 {fmt(skip_cnt)} 重复）")

    if dry_run or not new_ids:
        if new_ids:
            sample = list(zip(new_ids[:2], new_docs[:2], new_metas[:2]))
            print("\n样本预览:")
            for sid, sdoc, smeta in sample:
                print(f"  id={sid[:20]}... doc={sdoc[:80]}... meta={smeta}")
        print(f"\n[DRY-RUN] 将向 {DST_COL} 写入 {fmt(len(new_ids))} 条，退出。")
        return

    # 重新 embed 并写入
    ef = DefaultEmbeddingFunction()
    new_cnt = 0
    err_cnt = 0
    t0 = time.time()

    print(f"\n开始写入 {fmt(len(new_ids))} 条到 [{DST_COL}]…")
    for i in range(0, len(new_ids), BATCH_SIZE):
        b_ids   = new_ids[i : i + BATCH_SIZE]
        b_docs  = new_docs[i : i + BATCH_SIZE]
        b_metas = new_metas[i : i + BATCH_SIZE]
        try:
            embeddings = ef(b_docs)
            dst_col.add(
                ids=b_ids,
                embeddings=embeddings,
                documents=b_docs,
                metadatas=b_metas,
            )
            new_cnt += len(b_ids)
        except Exception as e:
            print(f"\n  [ERROR] batch {i}: {e}")
            err_cnt += len(b_ids)

        done    = min(i + BATCH_SIZE, len(new_ids))
        elapsed = time.time() - t0
        pct     = done / len(new_ids) * 100
        print(
            f"  进度: {fmt(done)}/{fmt(len(new_ids))} ({pct:.1f}%) "
            f"| 新增 {fmt(new_cnt)} | 错误 {fmt(err_cnt)} | 耗时 {elapsed:.0f}s",
            end="\r",
        )

    print()

    # 结果
    final_cnt = dst_col.count()
    elapsed   = time.time() - t0
    print(f"\n✅ 写入完成！")
    print(f"   新增: {fmt(new_cnt)}  错误: {fmt(err_cnt)}")
    print(f"   [{DST_COL}] 最终向量数: {fmt(final_cnt)}  (原 {fmt(dst_cnt)} → 现 {fmt(final_cnt)})")
    print(f"   耗时: {elapsed:.1f}s")

    # 可选：删除 cursor_conversations 集合
    if delete_src:
        client.delete_collection(SRC_COL)
        print(f"\n🗑  已删除源集合 [{SRC_COL}]（--delete-src 指定）")
    else:
        print(f"\n提示：cursor_conversations 集合仍保留（如需删除，重新运行时加 --delete-src）")


if __name__ == "__main__":
    main()
