"""
clean_noise_vectors.py — 清洗 d_drive_index 中的噪声向量

噪声类型：
  1. CMS 目录内容（szbolent / woocms / bolent / wp-content / woocommerce）
  2. CSS/lock 文件中的超长 Base64 字符串

用法:
  python clean_noise_vectors.py --dry-run   # 预览，不删除
  python clean_noise_vectors.py             # 正式删除
"""
import sys
import re
import time
import argparse
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent / "static"))
sys.path.insert(0, str(Path(__file__).parent))
import bootstrap_paths  # noqa

import chromadb
from config.settings import config

# ─── 配置 ────────────────────────────────────────────────────────────────────
TARGET_DB   = "db/merged_chroma"
COLLECTION  = "d_drive_index"
BATCH_SIZE  = 2000
DELETE_BATCH = 500   # Chroma 单次 delete 上限建议 ≤1000

# CMS/框架目录关键字（路径中包含任意一个即视为噪声）
CMS_KEYWORDS = [
    "szbolent", "woocms", "bolent",
    "wp-content", "woocommerce",
    "rcsc",          # CodeIgniter 旧框架
]

# Base64 噪声规则：200+ 连续 base64 字符
BASE64_PAT = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
BASE64_TYPES = {"css", "lock", "html"}   # 只在这些类型里检测

# ─── 主逻辑 ──────────────────────────────────────────────────────────────────

def is_noise(file_path: str, file_type: str, document: str) -> tuple[bool, str]:
    """判断一条向量是否是噪声，返回 (is_noise, reason)"""
    fp_lower = file_path.lower()

    # 规则 1：CMS 目录
    for kw in CMS_KEYWORDS:
        if kw in fp_lower:
            return True, f"cms_dir:{kw}"

    # 规则 2：特定类型文件含超长 Base64
    if file_type in BASE64_TYPES and document and BASE64_PAT.search(document):
        return True, f"base64_in_{file_type}"

    return False, ""


def scan_noise(col) -> list[str]:
    """全量扫描，返回所有噪声 id 列表"""
    total = col.count()
    noise_ids = []
    reasons = Counter()

    offset = 0
    t0 = time.time()
    while offset < total:
        batch = col.get(
            limit=BATCH_SIZE,
            offset=offset,
            include=["metadatas", "documents"],
        )
        ids   = batch.get("ids") or []
        metas = batch.get("metadatas") or []
        docs  = batch.get("documents") or []

        for vid, m, d in zip(ids, metas, docs):
            fp = m.get("file_path") or ""
            ft = m.get("file_type") or ""
            noise, reason = is_noise(fp, ft, d or "")
            if noise:
                noise_ids.append(vid)
                reasons[reason] += 1

        offset += BATCH_SIZE
        elapsed = time.time() - t0
        pct = offset / total * 100
        print(f"\r  扫描进度: {min(offset,total):,}/{total:,} ({pct:.0f}%) "
              f"噪声: {len(noise_ids):,}  {elapsed:.0f}s", end="", flush=True)

    print()
    return noise_ids, reasons


def delete_in_batches(col, ids: list[str]) -> int:
    """分批删除，返回实际删除数"""
    deleted = 0
    for i in range(0, len(ids), DELETE_BATCH):
        batch = ids[i : i + DELETE_BATCH]
        col.delete(ids=batch)
        deleted += len(batch)
        pct = deleted / len(ids) * 100
        print(f"\r  删除进度: {deleted:,}/{len(ids):,} ({pct:.0f}%)", end="", flush=True)
    print()
    return deleted


def main():
    parser = argparse.ArgumentParser(description="清洗 d_drive_index 中的噪声向量")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    args = parser.parse_args()

    print(f"目标库: {TARGET_DB}")
    print(f"集合: {COLLECTION}")
    print(f"模式: {'DRY-RUN（仅统计）' if args.dry_run else '正式删除'}")
    print()

    client = chromadb.PersistentClient(path=TARGET_DB)
    col = client.get_collection(COLLECTION)
    total_before = col.count()
    print(f"当前向量总数: {total_before:,}")
    print()

    # ── 扫描噪声 ──
    print("第一步：扫描噪声…")
    noise_ids, reasons = scan_noise(col)

    print(f"\n噪声统计：")
    print(f"  总计: {len(noise_ids):,} 条 ({len(noise_ids)/total_before*100:.1f}%)")
    for reason, cnt in reasons.most_common():
        print(f"  [{reason}]: {cnt:,}")

    if args.dry_run:
        print("\n[DRY-RUN] 不执行删除，退出。")
        return

    if not noise_ids:
        print("\n无噪声数据，无需清洗。")
        return

    # ── 确认 ──
    print(f"\n第二步：删除 {len(noise_ids):,} 条噪声向量…")
    t0 = time.time()
    deleted = delete_in_batches(col, noise_ids)
    elapsed = time.time() - t0

    total_after = col.count()
    print(f"\n清洗完成！")
    print(f"  删除: {deleted:,} 条")
    print(f"  耗时: {elapsed:.1f}s")
    print(f"  清洗前: {total_before:,} | 清洗后: {total_after:,}")
    print(f"  保留率: {total_after/total_before*100:.1f}%")


if __name__ == "__main__":
    main()
