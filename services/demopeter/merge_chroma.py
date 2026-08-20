"""
Chroma 向量库合并去重脚本
====================================================
策略：
  1. 以 d_index_data 为主库（目标库，381K 向量）
  2. 把 d_index_v2 的增量数据合并进主库（去重：跳过已存在 id）
  3. 可选：从 old_main（D盘旧库）复制非 d_drive_index 集合
     （cursor_conversations / chronicle / szpeter2026_kb）
  4. 生成合并后的新目录 db/merged_chroma，不动原库

去重方案：以 Chroma 的 document id 为唯一键
  d_index_data 的 id 格式：{md5_hash}_chunk_{i}
  d_index_v2   的 id 格式：相同格式，大部分与 d_index_data 重叠

用法：
  python merge_chroma.py [--dry-run] [--with-old-main]
  python merge_chroma.py            # 默认：合并本地两库，不含 D 盘旧库

注意：
  - 脚本不会修改原库，输出到 db/merged_chroma/
  - 执行完毕后请手动检查，再修改 .env
"""

import sys
import io
import time
import os
import argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "static"))
import bootstrap_paths  # noqa

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# ─── 路径配置 ────────────────────────────────────────────────
MAIN_DB      = str(PROJECT_ROOT / "db" / "d_index_data")       # 主力库 381K
V2_DB        = str(PROJECT_ROOT / "db" / "d_index_v2")         # 增量库 1.2K
OLD_MAIN_DB  = "D:/surface-zervi/DemoPeter/db/chroma_data"      # D 盘旧库（可选）
TARGET_DB    = str(PROJECT_ROOT / "db" / "merged_chroma")       # 输出目标

COLLECTION_D_INDEX = "d_drive_index"
# D 盘旧库中需要迁移的其他集合（非 d_drive_index）
OLD_OTHER_COLS = ["cursor_conversations", "chronicle", "szpeter2026_kb"]


DIV = "─" * 70


def open_client(path: str) -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=path)


def collection_ids_set(col) -> set:
    """分批拉取所有 id，返回 set"""
    all_ids = set()
    offset = 0
    batch = 2000
    total = col.count()
    while offset < total:
        res = col.get(limit=batch, offset=offset, include=[])
        ids = res.get("ids") or []
        all_ids.update(ids)
        offset += len(ids)
        if not ids:
            break
    return all_ids


def copy_collection_batched(
    src_col,
    dst_col,
    skip_ids: set,
    batch_size: int = 500,
    dry_run: bool = False,
    label: str = "",
) -> dict:
    """
    把 src_col 中不在 skip_ids 里的记录批量写入 dst_col。
    返回统计 {'total': int, 'inserted': int, 'skipped': int, 'errors': int}
    """
    total = src_col.count()
    inserted = skipped = errors = 0
    offset = 0
    t0 = time.time()

    while offset < total:
        res = src_col.get(
            limit=batch_size,
            offset=offset,
            include=["embeddings", "metadatas", "documents"],
        )
        ids      = res.get("ids") or []
        embs_raw = res.get("embeddings")
        embs     = embs_raw if embs_raw is not None else []
        metas    = res.get("metadatas") or []
        docs     = res.get("documents") or []

        if not ids:
            break

        # 过滤出需要插入的
        new_ids   = []
        new_embs  = []
        new_metas = []
        new_docs  = []

        for j, rid in enumerate(ids):
            if rid in skip_ids:
                skipped += 1
                continue
            new_ids.append(rid)
            new_embs.append(embs[j] if j < len(embs) else None)
            new_metas.append(metas[j] if j < len(metas) else {})
            new_docs.append(docs[j] if j < len(docs) else "")

        if new_ids and not dry_run:
            try:
                # 过滤掉 embedding 为 None 的（无法插入）
                valid = [(i, e, m, d) for i, e, m, d in
                         zip(new_ids, new_embs, new_metas, new_docs) if e is not None]
                if valid:
                    vi, ve, vm, vd = zip(*valid)
                    dst_col.add(
                        ids=list(vi),
                        embeddings=list(ve),
                        metadatas=list(vm),
                        documents=list(vd),
                    )
                    inserted += len(vi)
                    skip_ids.update(vi)
                skipped_no_emb = len(new_ids) - len(valid)
                if skipped_no_emb:
                    print(f"  ⚠  {skipped_no_emb} records skipped (no embedding)")
            except Exception as e:
                errors += 1
                print(f"  ❌ Batch error at offset {offset}: {e}")

        elif new_ids and dry_run:
            inserted += len(new_ids)

        offset += len(ids)

        # 进度报告（每 10000 条）
        if (inserted + skipped) % 10000 < batch_size:
            elapsed = time.time() - t0
            print(f"  {label} progress: {offset}/{total} processed | "
                  f"+{inserted} new | {skipped} dup | {elapsed:.0f}s")

    return {"total": total, "inserted": inserted, "skipped": skipped, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Merge Chroma vector stores")
    parser.add_argument("--dry-run", action="store_true",
                        help="统计但不写入")
    parser.add_argument("--with-old-main", action="store_true",
                        help="同时从 D 盘旧库迁移 cursor_conversations 等集合")
    args = parser.parse_args()

    DRY = args.dry_run
    if DRY:
        print("⚠️  DRY-RUN 模式：只统计，不写入")
    print(DIV)
    print("  Nazha Chroma 合并去重工具")
    print(f"  主库:   {MAIN_DB}")
    print(f"  增量库: {V2_DB}")
    print(f"  目标库: {TARGET_DB}")
    print(DIV)

    # ── 1. 打开主库 ──────────────────────────────────────────
    print("\n[1] 读取主库 d_index_data ...")
    main_client = open_client(MAIN_DB)
    main_col    = main_client.get_collection(COLLECTION_D_INDEX)
    main_count  = main_col.count()
    print(f"  主库向量数: {main_count:,}")

    print("  加载主库 id 集合（用于去重）...")
    t0 = time.time()
    main_ids = collection_ids_set(main_col)
    print(f"  已加载 {len(main_ids):,} 个 id，耗时 {time.time()-t0:.1f}s")

    # ── 2. 创建目标库（复制主库到 merged_chroma） ────────────
    if not DRY:
        # 先检查目标库是否已存在
        target_sqlite = Path(TARGET_DB) / "chroma.sqlite3"
        if target_sqlite.exists():
            print(f"\n[!] 目标库已存在: {TARGET_DB}")
            print("    请删除后重试，或使用 --dry-run 先预览。")
            print("    命令: rmdir /S /Q db\\merged_chroma")
            sys.exit(1)

        print(f"\n[2] 创建目标库 {TARGET_DB} ...")
        # 目标库：先把主库内容整体复制过去（用 Python shutil）
        import shutil
        print("  复制主库文件（约 381K 向量）...")
        shutil.copytree(MAIN_DB, TARGET_DB)
        print("  ✅ 主库复制完成")
    else:
        print(f"\n[2] [DRY] 跳过创建目标库")

    # ── 3. 打开目标库 ─────────────────────────────────────────
    target_client = open_client(TARGET_DB if not DRY else MAIN_DB)
    target_col    = (target_client.get_or_create_collection(COLLECTION_D_INDEX)
                     if not DRY else main_col)
    target_count_before = target_col.count()
    print(f"\n  目标库当前向量数: {target_count_before:,}")

    # 目标库 id 集合（去重用）
    target_ids = set(main_ids)  # 从主库 id 开始

    # ── 4. 合并 d_index_v2 ────────────────────────────────────
    print(f"\n[3] 合并 d_index_v2 ({V2_DB}) ...")
    v2_client = open_client(V2_DB)
    v2_col    = v2_client.get_collection(COLLECTION_D_INDEX)
    v2_count  = v2_col.count()
    print(f"  v2 库向量数: {v2_count:,}")

    stats_v2 = copy_collection_batched(
        src_col=v2_col,
        dst_col=target_col,
        skip_ids=target_ids,
        batch_size=500,
        dry_run=DRY,
        label="v2",
    )
    print(f"  v2 合并完成: total={stats_v2['total']:,} | "
          f"inserted={stats_v2['inserted']:,} | "
          f"skipped(dup)={stats_v2['skipped']:,} | "
          f"errors={stats_v2['errors']}")

    # ── 5. 可选：从 D 盘旧库迁移其他集合 ──────────────────────
    old_stats = {}
    if args.with_old_main:
        print(f"\n[4] 从 D 盘旧库迁移其他集合 ({OLD_MAIN_DB}) ...")
        if not os.path.exists(OLD_MAIN_DB):
            print(f"  ❌ 路径不存在，跳过: {OLD_MAIN_DB}")
        else:
            try:
                old_client = open_client(OLD_MAIN_DB)
                existing_cols = {c.name for c in old_client.list_collections()}
                for col_name in OLD_OTHER_COLS:
                    if col_name not in existing_cols:
                        print(f"  [skip] {col_name}: 不存在于旧库")
                        continue
                    src_col = old_client.get_collection(col_name)
                    src_cnt = src_col.count()
                    print(f"\n  迁移 [{col_name}] ({src_cnt:,} vectors) ...")
                    dst_col = (target_client.get_or_create_collection(col_name)
                               if not DRY else src_col)
                    # 各集合独立去重
                    dst_ids = collection_ids_set(dst_col) if not DRY else set()
                    s = copy_collection_batched(
                        src_col=src_col,
                        dst_col=dst_col,
                        skip_ids=dst_ids,
                        dry_run=DRY,
                        label=col_name,
                    )
                    old_stats[col_name] = s
                    print(f"  {col_name}: inserted={s['inserted']:,}, skipped={s['skipped']:,}")
            except Exception as e:
                print(f"  ❌ 旧库读取失败: {e}")
    else:
        print("\n[4] 跳过 D 盘旧库（需要加 --with-old-main 参数）")

    # ── 6. 汇总报告 ───────────────────────────────────────────
    print(f"\n{DIV}")
    print("  合并完成汇总")
    print(DIV)
    if not DRY:
        final_count = target_col.count()
        print(f"  目标库最终向量数: {final_count:,}")
        print(f"  新增向量数:        {final_count - target_count_before:,}")
        print(f"  位置:              {TARGET_DB}")
    else:
        estimated = target_count_before + stats_v2["inserted"]
        print(f"  [DRY] 估算最终向量数: {estimated:,}")
        print(f"  [DRY] 估算新增:       {stats_v2['inserted']:,}")

    print(f"\n  d_index_v2 贡献: +{stats_v2['inserted']:,} (去重 {stats_v2['skipped']:,} 重复)")
    for col_name, s in old_stats.items():
        print(f"  {col_name}: +{s['inserted']:,} (去重 {s['skipped']:,})")

    if not DRY:
        print(f"""
  ─── 后续步骤 ───────────────────────────────────────────────
  1. 验证合并结果: python test_rag_diag.py（需先临时改 .env）
  2. 确认无误后修改 .env:
       CHROMA_PERSIST_DIR=C:/Users/HUAWEI/DemoPeter/db/merged_chroma
       CHROMA_COLLECTION=d_drive_index
  ─────────────────────────────────────────────────────────────
""")
    else:
        print("\n  [DRY] 实际合并请去掉 --dry-run 重新运行。")


if __name__ == "__main__":
    main()
