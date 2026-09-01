"""向量存储：相似度转换与健康检查单元测试"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bootstrap_paths  # noqa: F401

from src.vector_store import (
    EMBED_MODEL,
    STEmbeddingFunction,
    VectorStore,
    squared_l2_to_cosine_similarity,
)


class TestSquaredL2ToCosineSimilarity(unittest.TestCase):
    def test_identical_vectors(self):
        self.assertEqual(squared_l2_to_cosine_similarity(0.0), 1.0)

    def test_opposite_vectors(self):
        self.assertEqual(squared_l2_to_cosine_similarity(4.0), 0.0)

    def test_midpoint(self):
        self.assertEqual(squared_l2_to_cosine_similarity(1.0), 0.5)

    def test_clamps_above_one(self):
        self.assertEqual(squared_l2_to_cosine_similarity(-0.5), 1.0)

    def test_clamps_below_zero(self):
        self.assertEqual(squared_l2_to_cosine_similarity(5.0), 0.0)


class TestSTEmbeddingFunctionInterface(unittest.TestCase):
    def test_chroma_protocol_methods_exist(self):
        self.assertEqual(STEmbeddingFunction.name(), EMBED_MODEL)
        self.assertTrue(callable(STEmbeddingFunction.get_config))
        self.assertTrue(callable(STEmbeddingFunction.build_from_config))
        self.assertTrue(callable(STEmbeddingFunction.default_space))


class TestVectorStoreHealthCheck(unittest.TestCase):
    def _make_store(self, *, available: bool, mode: str = "persistent"):
        store = VectorStore.__new__(VectorStore)
        store._mode = mode
        store.collection_name = "test"
        store._client = MagicMock() if available else None
        store._collection = MagicMock() if available else None
        return store

    def test_unavailable_collection(self):
        store = self._make_store(available=False, mode="unavailable")
        result = store.health_check()
        self.assertFalse(result["available"])
        self.assertFalse(result["embedding_ok"])
        self.assertEqual(result["embedding_error"], "collection not initialized")

    def test_empty_collection_skips_embedding_probe(self):
        store = self._make_store(available=True)
        store._collection.count.return_value = 0
        result = store.health_check()
        self.assertTrue(result["available"])
        self.assertIsNone(result["embedding_ok"])
        store._collection.query.assert_not_called()

    @patch("src.vector_store._get_embed_fn")
    def test_embedding_ok_when_query_returns_ids(self, mock_fn):
        mock_fn.return_value = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        store = self._make_store(available=True)
        store._collection.count.return_value = 3
        store._collection.query.return_value = {"ids": [["chunk_0"]]}
        result = store.health_check()
        self.assertTrue(result["embedding_ok"])
        self.assertNotIn("embedding_error", result)
        kwargs = store._collection.query.call_args.kwargs
        self.assertIn("query_embeddings", kwargs)

    @patch("src.vector_store._get_embed_fn")
    def test_embedding_error_when_query_empty(self, mock_fn):
        mock_fn.return_value = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        store = self._make_store(available=True)
        store._collection.count.return_value = 3
        store._collection.query.return_value = {"ids": [[]]}
        result = store.health_check()
        self.assertFalse(result["embedding_ok"])
        self.assertEqual(result["embedding_error"], "query returned no results")

    @patch("src.vector_store._get_embed_fn")
    def test_embedding_error_when_query_raises(self, mock_fn):
        mock_fn.return_value = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        store = self._make_store(available=True)
        store._collection.count.return_value = 1
        store._collection.query.side_effect = RuntimeError("embedding failed")
        result = store.health_check()
        self.assertFalse(result["embedding_ok"])
        self.assertIn("embedding failed", result["embedding_error"])


class TestVectorStoreSearchSimilarity(unittest.TestCase):
    @patch("src.vector_store._get_embed_fn")
    def test_search_uses_squared_l2_conversion(self, mock_fn):
        mock_fn.return_value = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        store = VectorStore.__new__(VectorStore)
        store._collection = MagicMock()
        store._collection.query.return_value = {
            "ids": [["a"]],
            "documents": [["hello"]],
            "metadatas": [[{"doc_id": "1"}]],
            "distances": [[0.0]],
        }

        hits = store.search("test", top_k=1, threshold=0.0)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["similarity"], 1.0)
        kwargs = store._collection.query.call_args.kwargs
        self.assertIn("query_embeddings", kwargs)
        self.assertNotIn("query_texts", kwargs)


if __name__ == "__main__":
    unittest.main()
