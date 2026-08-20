"""混合检索单元测试"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bootstrap_paths  # noqa: F401

from src.hybrid_search import hit_key, reciprocal_rank_fusion, weighted_fusion, filter_by_threshold


class TestHybridSearch(unittest.TestCase):
    def test_hit_key_doc_chunk(self):
        hit = {"metadata": {"doc_id": 3, "chunk_index": 1}, "content": "x"}
        self.assertEqual(hit_key(hit), "3:1")

    def test_rrf_prefers_both_lists(self):
        vector = [
            {"id": "a", "content": "alpha", "metadata": {"doc_id": 1, "chunk_index": 0}, "similarity": 0.9},
            {"id": "b", "content": "beta", "metadata": {"doc_id": 2, "chunk_index": 0}, "similarity": 0.8},
        ]
        keyword = [
            {"id": "b", "content": "beta", "metadata": {"doc_id": 2, "chunk_index": 0}, "similarity": 0.6},
            {"id": "c", "content": "gamma", "metadata": {"doc_id": 3, "chunk_index": 0}, "similarity": 0.5},
        ]
        merged = reciprocal_rank_fusion([vector, keyword], top_k=3, k=60)
        keys = {hit_key(h) for h in merged}
        self.assertIn("2:0", keys)
        self.assertEqual(len(merged), 3)

    def test_weighted_fusion(self):
        vector = [{"id": "v1", "content": "v", "metadata": {}, "similarity": 1.0}]
        keyword = [{"id": "k1", "content": "k", "metadata": {}, "similarity": 0.5}]
        merged = weighted_fusion(vector, keyword, top_k=2)
        self.assertEqual(len(merged), 2)

    def test_rrf_display_similarity_not_tiny(self):
        vector = [
            {"id": "a", "content": "alpha", "metadata": {"doc_id": 1, "chunk_index": 0}, "similarity": 0.72},
        ]
        keyword = [
            {"id": "a", "content": "alpha", "metadata": {"doc_id": 1, "chunk_index": 0}, "similarity": 0.55},
        ]
        merged = reciprocal_rank_fusion([vector, keyword], top_k=1, lane_names=["vector", "keyword"])
        self.assertGreaterEqual(merged[0]["similarity"], 0.72)

    def test_filter_by_threshold(self):
        hits = [{"similarity": 0.8}, {"similarity": 0.3}]
        filtered = filter_by_threshold(hits, 0.5)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["similarity"], 0.8)


if __name__ == "__main__":
    unittest.main()
