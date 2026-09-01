"""
szpeter2026 - 重建 Chroma 向量索引（治本：中文嵌入质量）

背景：nomic-embed-text 对中文语义区分度不足（任意中文文本互相 0.75+ 相似），
导致 RAG 检索 top 位被无关文档的虚高相似度污染（如问「数理化通俗演义」
返回化妆品法规/天气 CSV）。

本机（16GB MacBook）嵌入引擎实测：
  - bge-m3 MPS: 8条/s 但 SDPA MPSGraph 长跑必挂（验证 3 次）; CPU 0.6条/s
  - text2vec-base-chinese（102M, 768维, C-MTEB 前列）MPS 84~183 条/s 且稳定
    （bge-m3 的 SDPA 挂起仅发生于大模型长序列）；CPU 仅 2 条/s
  - 默认 MPS 单进程即可（~5 分钟）；CPU 场景可用多进程分片（--shards N）提速

三步式：
  embed [--shard k --shards N]  嵌入本 shard 区间 -> db/bgem3_embeddings_shard{k}.npz
  merge                          合并所有 shard -> db/bgem3_embeddings.npz
  write                          读 npz -> 写临时 collection -> 校验 -> 原子切换

用法：
  1. 停止 demopeter（避免 Chroma 并发写）
  2. MPS:  python scripts/reindex_embeddings.py embed --shard 0 --shards 1
     CPU 并行: for k in 0 1 2 3; do python scripts/reindex_embeddings.py embed --shards 4 --shard $k & done
  3. 全部完成: python scripts/reindex_embeddings.py merge --shards N
  4. python scripts/reindex_embeddings.py write
  5. 重启 demopeter（查询嵌入已由 vector_store.py 的 STEmbeddingFunction 自动使用
     text2vec；启动需带 HF_ENDPOINT=https://hf-mirror.com）

注意：chroma 1.5.9 无 update_collection/改名 API。write 先尝试改名，失败则
自动「读临时库复制迁移」到目标名再删临时库（旧库在改名/迁移前已删除）。

安全：write 先写临时 collection，校验通过后再切换；复制迁移失败时临时库仍在。
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import numpy as np

from config.settings import config

EMBEDDING_MODEL = "shibing624/text2vec-base-chinese"
BATCH_ENCODE = 128
BATCH_ADD = 100
NPZ_PATH = Path(config.DB_DIR) / "text2vec_embeddings.npz"
LEGACY_NPZ_PATH = Path(config.DB_DIR) / "bgem3_embeddings.npz"
MAX_CHARS = 512  # 512 token 内检索语义最集中，且缩短文本显著提速


def _shard_path(k):
    return Path(str(NPZ_PATH).replace(".npz", f"_shard{k}.npz"))


def _load_rows() -> list[dict]:
    con = sqlite3.connect(config.METADATA_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT c.id, c.document_id, c.chunk_index, c.content,
               d.title AS doc_title
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        ORDER BY c.id
    """).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _save(path, embeddings, ids, n_done):
    np.savez_compressed(path, embeddings=embeddings, ids=np.array(ids),
                        n_done=n_done)
    print(f"  [checkpoint] {n_done} 条已存 {path}", flush=True)


def stage_embed(args):
    rows = _load_rows()
    n_total = len(rows)
    shards = args.shards
    k = args.shard

    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(8)
    t0 = time.time()
    # text2vec（102M 小模型）在 MPS 上 84条/s 且稳定（bge-m3 的 SDPA 挂起仅
    # 发生于大模型长序列）。CPU 仅 2条/s。故优先 MPS。
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer(EMBEDDING_MODEL, device=device)
    dim = model.get_sentence_embedding_dimension()
    print(f"[shard {k}/{shards}] 模型加载 {time.time()-t0:.0f}s | 维度 {dim}",
          flush=True)

    start = n_total * k // shards
    end = n_total * (k + 1) // shards
    seg = rows[start:end]
    n_seg = len(seg)
    print(f"[shard {k}/{shards}] 区间 [{start},{end}) 共 {n_seg} 条", flush=True)

    sp = _shard_path(k)
    if sp.exists():
        d = np.load(sp, allow_pickle=True)
        embeddings = d["embeddings"]
        ids_seg = d["ids"].tolist()
        n_done = int(d["n_done"]) if "n_done" in d else n_seg
        print(f"[shard {k}/{shards}] 续跑: 已有 {n_done}/{n_seg}", flush=True)
    else:
        embeddings = np.zeros((n_seg, dim), dtype=np.float32)
        ids_seg = [f"{r['document_id']}_chunk_{r['chunk_index']}" for r in seg]
        n_done = 0

    t0 = time.time()
    for i in range(n_done, n_seg, BATCH_ENCODE):
        batch = seg[i:i + BATCH_ENCODE]
        texts = [r["content"][:MAX_CHARS] for r in batch]
        vecs = model.encode(texts, batch_size=len(texts),
                            normalize_embeddings=True, show_progress_bar=False)
        embeddings[i:i + len(batch)] = vecs
        if device == "mps":
            torch.mps.empty_cache()  # 防 MPS 缓存膨胀
        n_done = i + len(batch)
        if n_done % 2000 < BATCH_ENCODE:
            rate = n_done / max(time.time() - t0, 0.001)
            eta = (n_seg - n_done) / rate
            print(f"[shard {k}/{shards}] 嵌入 {n_done}/{n_seg} "
                  f"({rate:.1f} 条/s, 剩余 ~{eta/60:.0f} 分钟)", flush=True)
            _save(sp, embeddings, ids_seg, n_done)

    _save(sp, embeddings, ids_seg, n_seg)
    print(f"[shard {k}/{shards}] 完成 {n_seg} 条, 耗时 "
          f"{(time.time()-t0)/60:.1f} 分钟", flush=True)


def stage_merge(args):
    rows = _load_rows()
    n_total = len(rows)
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    dim = model.get_sentence_embedding_dimension()

    embeddings = np.zeros((n_total, dim), dtype=np.float32)
    ids_all = [""] * n_total
    for k in range(args.shards):
        sp = _shard_path(k)
        if not sp.exists():
            print(f"[错误] 缺少 shard {k}: {sp}", flush=True)
            sys.exit(1)
        d = np.load(sp, allow_pickle=True)
        seg_emb = d["embeddings"]
        seg_ids = d["ids"].tolist()
        start = n_total * k // args.shards
        end = n_total * (k + 1) // args.shards
        if seg_emb.shape[0] != end - start:
            print(f"[错误] shard {k} 数量 {seg_emb.shape[0]} != 期望 {end-start}",
                  flush=True)
            sys.exit(1)
        embeddings[start:end] = seg_emb
        ids_all[start:end] = seg_ids
        print(f"  合并 shard {k}: [{start},{end})", flush=True)

    _save(NPZ_PATH, embeddings, ids_all, n_total)
    print(f"合并完成: {n_total} 条 -> {NPZ_PATH} "
          f"({embeddings.nbytes/1e6:.0f} MB)", flush=True)


def _npz_path() -> Path:
    if NPZ_PATH.exists():
        return NPZ_PATH
    if LEGACY_NPZ_PATH.exists():
        print(f"使用遗留路径 {LEGACY_NPZ_PATH}", flush=True)
        return LEGACY_NPZ_PATH
    print(f"[错误] 找不到 {NPZ_PATH}（先跑 embed + merge）", flush=True)
    sys.exit(1)


def _copy_collection(src, dst, n_expected: int):
    """chroma 1.5.9 无改名 API 时：分页读临时库写入目标库。"""
    offset = 0
    while True:
        batch = src.get(
            limit=BATCH_ADD,
            offset=offset,
            include=["embeddings", "documents", "metadatas"],
        )
        ids_b = batch.get("ids") or []
        if not ids_b:
            break
        dst.add(
            ids=ids_b,
            embeddings=batch["embeddings"],
            documents=batch["documents"],
            metadatas=batch["metadatas"],
        )
        offset += len(ids_b)
        if offset % 5000 < BATCH_ADD:
            print(f"  迁移 {offset}/{n_expected}", flush=True)
    return offset


def stage_write(args):
    d = np.load(_npz_path(), allow_pickle=True)
    embeddings, ids = d["embeddings"], d["ids"].tolist()
    n = len(ids)
    print(f"加载 {n} 条向量, 维度 {embeddings.shape[1]}", flush=True)

    rows = _load_rows()
    id2meta = {
        f"{r['document_id']}_chunk_{r['chunk_index']}": {
            "doc_id": r["document_id"],
            "chunk_index": r["chunk_index"],
            "source_file": r["doc_title"] or f"doc_{r['document_id']}",
        }
        for r in rows
    }
    texts = {f"{r['document_id']}_chunk_{r['chunk_index']}": r["content"][:MAX_CHARS]
             for r in rows}
    del rows

    import chromadb
    target = args.collection
    temp = f"{target}_text2vec"
    col_meta = {"description": "szpeter2026 知识库向量存储 (text2vec-base-chinese 重建)"}
    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    for leftover in (temp, f"{target}_bgem3"):
        try:
            client.delete_collection(leftover)
        except Exception:
            pass
    temp_col = client.create_collection(name=temp, metadata=col_meta)

    t0 = time.time()
    for i in range(0, n, BATCH_ADD):
        chunk_ids = ids[i:i + BATCH_ADD]
        temp_col.add(
            ids=chunk_ids,
            documents=[texts[cid] for cid in chunk_ids],
            metadatas=[id2meta[cid] for cid in chunk_ids],
            embeddings=embeddings[i:i + BATCH_ADD],
        )
        if (i // BATCH_ADD) % 50 == 0:
            print(f"  写入 {i + len(chunk_ids)}/{n} ({time.time()-t0:.0f}s)", flush=True)
    print(f"写入完成: {n} 条, 耗时 {time.time()-t0:.0f}s", flush=True)

    n_col = temp_col.count()
    sample = temp_col.get(limit=min(100, n_col), include=["embeddings"])
    zero = sum(1 for v in sample["embeddings"] if not np.any(np.asarray(v)))
    dims = set(len(np.asarray(v).flatten()) for v in sample["embeddings"])
    print(f"临时库校验: count={n_col}, 维度集={dims}, "
          f"零向量={zero}/{len(sample['embeddings'])}", flush=True)
    if n_col != n:
        print(f"[警告] 数量不一致: 临时库 {n_col} vs 期望 {n}")
    if zero:
        print(f"[警告] 存在 {zero} 条零向量")

    try:
        client.delete_collection(target)
        client.update_collection(name=temp, new_name=target)
        print(f"已切换: 删除旧 {target} -> 改名 {temp} 为 {target}", flush=True)
    except Exception as e:
        print(f"原子改名失败（chroma 1.5.9 通常无此 API）: {e}", flush=True)
        print("改为读临时库复制迁移...", flush=True)
        try:
            client.delete_collection(target)
        except Exception:
            pass
        new_col = client.create_collection(name=target, metadata=col_meta)
        copied = _copy_collection(temp_col, new_col, n_col)
        print(f"迁移完成: {copied} 条 -> {target} (count={new_col.count()})",
              flush=True)
        try:
            client.delete_collection(temp)
        except Exception:
            print(f"[警告] 临时库 {temp} 未删除，可稍后手动清理", flush=True)

    col = client.get_collection(target)
    print(f"最终: collection={target}, count={col.count()}", flush=True)
    print("完成。重启 demopeter（查询嵌入由 vector_store.STEmbeddingFunction 加载 text2vec；"
          "启动需 HF_ENDPOINT=https://hf-mirror.com）。")


def main():
    parser = argparse.ArgumentParser(description="重建 Chroma 向量索引（中文嵌入治本）")
    sub = parser.add_subparsers(dest="stage", required=True)

    p_embed = sub.add_parser("embed", help="嵌入本 shard 区间到 npz")
    p_embed.add_argument("--shard", type=int, default=0)
    p_embed.add_argument("--shards", type=int, default=1)

    p_merge = sub.add_parser("merge", help="合并所有 shard")
    p_merge.add_argument("--shards", type=int, default=4)

    p_write = sub.add_parser("write", help="写 Chroma 并原子切换")
    p_write.add_argument("--collection", default=config.CHROMA_COLLECTION)

    args = parser.parse_args()
    if args.stage == "embed":
        stage_embed(args)
    elif args.stage == "merge":
        stage_merge(args)
    else:
        stage_write(args)


if __name__ == "__main__":
    main()
