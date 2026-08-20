"""
混合检索 — 向量语义 + SQLite FTS5 关键词，RRF 融合排序
"""
from __future__ import annotations


def hit_key(hit: dict) -> str:
    """生成分块唯一键，用于跨检索源去重与融合。"""
    meta = hit.get("metadata") or {}
    doc_id = meta.get("doc_id")
    chunk_index = meta.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        return f"{doc_id}:{chunk_index}"
    hit_id = hit.get("id")
    if hit_id:
        return str(hit_id)
    content = hit.get("content") or ""
    return f"content:{hash(content) & 0xFFFFFFFF:08x}"


def _display_similarity(lane_scores: dict[str, float]) -> float:
    """用户可见相关度 = 各检索通道原始分的最大值（非 RRF 小数值）。"""
    if not lane_scores:
        return 0.0
    return max(lane_scores.values())


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    top_k: int = 5,
    k: int = 60,
    lane_names: list[str] | None = None,
) -> list[dict]:
    """
    Reciprocal Rank Fusion (RRF).

    score(d) = sum_i 1 / (k + rank_i(d))
    展示用 similarity 取各通道原始分最大值，便于与阈值 0~1 对齐。
    """
    if not ranked_lists:
        return []

    scores: dict[str, float] = {}
    best_hit: dict[str, dict] = {}
    lane_scores: dict[str, dict[str, float]] = {}

    for list_idx, results in enumerate(ranked_lists):
        if not results:
            continue
        lane = (lane_names or [f"lane{i}" for i in range(len(ranked_lists))])[list_idx]
        for rank, hit in enumerate(results):
            key = hit_key(hit)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            lane_scores.setdefault(key, {})[lane] = float(hit.get("similarity", 0.0))
            if key not in best_hit:
                best_hit[key] = hit

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    merged: list[dict] = []
    for key, rrf_score in ordered[:top_k]:
        hit = dict(best_hit[key])
        lanes = lane_scores.get(key, {})
        hit["lane_scores"] = lanes
        hit["rrf_score"] = round(rrf_score, 4)
        hit["similarity"] = round(_display_similarity(lanes), 4)
        hit["retrieval"] = hit.get("retrieval") or "hybrid"
        merged.append(hit)
    return merged


def weighted_fusion(
    vector_results: list[dict],
    keyword_results: list[dict],
    top_k: int = 5,
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> list[dict]:
    """加权融合（向量分 + 关键词分）。"""
    scores: dict[str, float] = {}
    best_hit: dict[str, dict] = {}
    lane_scores: dict[str, dict[str, float]] = {}

    for hit in vector_results:
        key = hit_key(hit)
        vs = float(hit.get("similarity", 0.0))
        scores[key] = scores.get(key, 0.0) + vector_weight * vs
        lane_scores.setdefault(key, {})["vector"] = vs
        best_hit.setdefault(key, hit)

    for hit in keyword_results:
        key = hit_key(hit)
        ks = float(hit.get("similarity", 0.0))
        scores[key] = scores.get(key, 0.0) + keyword_weight * ks
        lane_scores.setdefault(key, {})["keyword"] = ks
        best_hit.setdefault(key, hit)

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    merged: list[dict] = []
    for key, score in ordered[:top_k]:
        hit = dict(best_hit[key])
        lanes = lane_scores.get(key, {})
        hit["lane_scores"] = lanes
        hit["similarity"] = round(_display_similarity(lanes), 4)
        hit["fusion_score"] = round(score, 4)
        hit["retrieval"] = "hybrid_weighted"
        merged.append(hit)
    return merged


def filter_by_threshold(hits: list[dict], threshold: float) -> list[dict]:
    """按用户设置的相似度阈值过滤（基于展示用 similarity）。"""
    if threshold <= 0:
        return hits
    return [h for h in hits if h.get("similarity", 0) >= threshold]
