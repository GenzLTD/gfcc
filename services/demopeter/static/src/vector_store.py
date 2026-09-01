"""
szpeter2026 - 向量存储
吸收自 72changes 的 Chroma 集成，管理文档向量化和检索
支持本地持久化（PersistentClient，零依赖）和远程服务（HttpClient）双模式
"""
import os
from typing import Optional

from config.settings import config
from config.logging_config import get_logger

# text2vec-base-chinese 嵌入（102M, 768 维, C-MTEB 前列；重建索引统一用 MPS）
EMBED_MODEL = "shibing624/text2vec-base-chinese"
# 嵌入输入安全长度：与 scripts/reindex_embeddings.py 的 MAX_CHARS 一致（512 token 内
# 检索语义最集中，且与库内向量截断对齐，保证查询/写入语义一致）
EMBED_MAX_CHARS = 512
# text2vec-base-chinese 向量维度
EMBED_DIM = 768

logger = get_logger("vector_store")

try:
    import chromadb
except ImportError:  # 优雅降级：无 chroma 时 STEmbeddingFunction 退化为普通类
    chromadb = None

if chromadb is not None:
    _ST_BASE = chromadb.api.types.EmbeddingFunction[list[str]]
else:
    _ST_BASE = object


class STEmbeddingFunction(_ST_BASE):
    """sentence-transformers 嵌入函数（text2vec-base-chinese）。

    MPS 优先、CPU 回退；encode 时 L2 归一化（与 squared_l2_to_cosine_similarity
    的前提一致）。输入截断 EMBED_MAX_CHARS，与重建索引时一致。
    chroma 1.5.9 的 EmbeddingFunction 接口重构为方法（name()/get_config()/
    build_from_config()），未实现会 is_legacy()=True 而静默降级为默认嵌入函数，
    因此此处完整实现以保证查询嵌入始终走 text2vec。
    """
    def __init__(self, model_name: str = EMBED_MODEL):
        self._model_name = model_name
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name, device=device)

    @staticmethod
    def name() -> str:
        return EMBED_MODEL

    def default_space(self) -> str:
        return "cosine"

    def get_config(self) -> dict:
        return {"model_name": self._model_name}

    @staticmethod
    def build_from_config(config: dict) -> "STEmbeddingFunction":
        return STEmbeddingFunction(config.get("model_name", EMBED_MODEL))

    def __call__(self, input: list[str]):
        texts = [t[:EMBED_MAX_CHARS] for t in input]
        vecs = self._model.encode(
            texts, batch_size=min(len(texts), 128),
            normalize_embeddings=True, show_progress_bar=False,
        )
        return [v.tolist() for v in vecs]


# ST 嵌入函数单例（模型加载 ~3s，避免每次调用重建）
_embed_fn = None


def _get_embed_fn() -> STEmbeddingFunction:
    global _embed_fn
    if _embed_fn is None:
        _embed_fn = STEmbeddingFunction()
    return _embed_fn


def squared_l2_to_cosine_similarity(squared_l2: float) -> float:
    """将 Chroma 返回的 squared L2 距离转为余弦相似度 [0, 1]。

    前提：embedding 向量已 L2 归一化（STEmbeddingFunction / text2vec 的
    encode(normalize_embeddings=True) 满足）。对归一化向量有
    ||a-b||² = 2(1 - cos(a,b))，故 cos_sim = 1 - squared_l2/2。
    若换用未归一化的 embedding 模型，需改用对应距离→相似度公式。
    """
    similarity = 1.0 - squared_l2 / 2.0
    return max(0.0, min(1.0, similarity))


class VectorStore:
    """Chroma 向量数据库管理器
    
    初始化优先级：
    1. 本地持久化模式 (PersistentClient) — 数据存 db/chroma_data/，零依赖
    2. 远程服务模式 (HttpClient) — 需要 Docker/远程 Chroma 服务
    3. 不可用 — is_available = False
    """

    def __init__(self):
        self.collection_name = config.CHROMA_COLLECTION
        self._client = None
        self._collection = None
        self._mode = "unavailable"
        self._init_client()

    def _init_client(self):
        """初始化 Chroma 客户端，按配置的模式选择"""
        try:
            import chromadb
        except ImportError:
            self._client = None
            self._collection = None
            self._mode = "unavailable"
            return

        mode = config.CHROMA_MODE

        if mode == "persistent":
            self._try_persistent()
        elif mode == "remote":
            self._try_remote()
        else:  # "auto": 优先远程 → 回退本地
            if not self._try_remote():
                self._try_persistent()

    def _try_remote(self) -> bool:
        """尝试连接远程 Chroma 服务"""
        try:
            import chromadb
            self._client = chromadb.HttpClient(
                host=config.CHROMA_HOST,
                port=config.CHROMA_PORT,
            )
            # 心跳检测
            self._client.heartbeat()
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "szpeter2026 知识库向量存储 (remote)"},
            )
            self._mode = "remote"
            return True
        except Exception:
            self._client = None
            self._collection = None
            return False

    def _try_persistent(self) -> bool:
        """尝试本地持久化模式。

        库内向量由 text2vec-base-chinese 重建（768 维）。不得回退 Chroma
        默认 MiniLM（384 维），否则查询空间与库不一致。
        不传 embedding_function：collection 持久化配置是 legacy default，
        chroma 1.5.9 再传新函数会报 conflict。查询/写入均手动传向量。
        """
        try:
            import chromadb

            try:
                _get_embed_fn()(["连接测试"])  # 预热，尽早发现模型加载问题
                logger.info("使用 ST embedding: %s", EMBED_MODEL)
            except Exception as e:
                logger.error("text2vec embedding 不可用: %s", e)
                logger.error("请安装 sentence-transformers，并设置 HF_ENDPOINT=https://hf-mirror.com")
                self._client = None
                self._collection = None
                self._mode = "unavailable"
                return False

            os.makedirs(config.CHROMA_PERSIST_DIR, exist_ok=True)
            self._client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "szpeter2026 知识库向量存储 (persistent)"},
            )
            self._mode = "persistent"
            return True
        except Exception as e:
            logger.error("本地持久化初始化失败: %s", e)
            self._client = None
            self._collection = None
            self._mode = "unavailable"
            return False

    @property
    def is_available(self) -> bool:
        return self._collection is not None

    def add_documents(self, doc_id: str, chunks: list[dict]) -> int:
        """批量添加文档分块到向量库"""
        if not self.is_available:
            return 0

        ids = []
        documents = []
        metadatas = []
        for i, chunk in enumerate(chunks):
            ids.append(f"{doc_id}_chunk_{i}")
            documents.append(chunk["content"])
            metadatas.append({
                "doc_id": doc_id,
                "chunk_index": i,
                **(chunk.get("metadata", {})),
            })

        # 手动计算 embedding：sentence-transformers（text2vec，STEmbeddingFunction
        # 内部按 EMBED_MAX_CHARS 截断，与重建索引一致）；失败条目逐条降级为零向量
        # （不参与命中），避免整个文档因单条 chunk 失败而被跳过。
        fn = _get_embed_fn()
        try:
            embeddings = fn(documents)
        except Exception as e:
            logger.warning("批量 embedding 失败(%s)，逐条降级", e)
            embeddings = []
            for d in documents:
                try:
                    embeddings.append(fn([d])[0])
                except Exception:
                    logger.warning("单条 embedding 失败，置零向量")
                    embeddings.append([0.0] * EMBED_DIM)

        # 分批插入（Chroma 有限制）
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            add_kwargs = dict(
                ids=ids[i:i + batch_size],
                documents=documents[i:i + batch_size],
                metadatas=metadatas[i:i + batch_size],
            )
            if embeddings is not None:
                add_kwargs["embeddings"] = embeddings[i:i + batch_size]
            self._collection.add(**add_kwargs)

        return len(ids)

    def search(self, query: str, top_k: int = 5,
               threshold: float = 0.7) -> list[dict]:
        """语义搜索"""
        if not self.is_available:
            return []

        # 手动嵌入查询（collection 无 embedding_function，见 _try_persistent）
        query_emb = _get_embed_fn()([query])[0]
        results = self._collection.query(
            query_embeddings=[query_emb],
            n_results=top_k,
        )

        hits = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                distance = results.get("distances", [[0]] * top_k)[0][i]
                similarity = squared_l2_to_cosine_similarity(distance)
                if similarity >= threshold:
                    hits.append({
                        "id": results["ids"][0][i],
                        "content": results["documents"][0][i],
                        "metadata": results.get("metadatas", [[{}]])[0][i],
                        "similarity": round(similarity, 4),
                    })

        return hits

    def delete_document(self, doc_id: str):
        """删除文档的所有向量"""
        if not self.is_available:
            return
        try:
            self._collection.delete(where={"doc_id": doc_id})
        except Exception:
            pass

    def health_check(self) -> dict:
        """健康检查：验证向量存储和 embedding 是否正常工作
        
        返回:
            dict: {
                "available": bool,         # 集合是否已初始化
                "mode": str,               # persistent / remote / unavailable
                "total_vectors": int,      # 向量总数
                "embedding_ok": bool|None, # embedding 函数是否正常 (None=无数据无法验证)
                "embedding_error": str|None, # embedding 错误信息
            }
        """
        if not self.is_available:
            return {"available": False, "mode": self._mode,
                    "total_vectors": 0, "embedding_ok": False,
                    "embedding_error": "collection not initialized"}

        result = {
            "available": True,
            "mode": self._mode,
            "total_vectors": self._collection.count(),
        }

        # 如果有向量数据，执行测试查询验证 embedding 函数可用
        if result["total_vectors"] > 0:
            try:
                test_emb = _get_embed_fn()(["健康检查测试"])[0]
                test_result = self._collection.query(
                    query_embeddings=[test_emb],
                    n_results=1,
                )
                has_ids = bool(test_result.get("ids") and test_result["ids"][0])
                result["embedding_ok"] = has_ids
                if not has_ids:
                    result["embedding_error"] = "query returned no results"
            except Exception as e:
                result["embedding_ok"] = False
                result["embedding_error"] = str(e)[:200]
        else:
            result["embedding_ok"] = None  # 无数据，无法验证

        return result

    def get_collection_stats(self) -> dict:
        """获取集合统计"""
        if not self.is_available:
            return {"available": False}
        count = self._collection.count()
        return {
            "available": True,
            "mode": self._mode,
            "collection_name": self.collection_name,
            "total_vectors": count,
        }

    def delete_collection(self):
        """重置集合"""
        if not self.is_available:
            return
        try:
            self._client.delete_collection(self.collection_name)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": f"szpeter2026 知识库向量存储 ({self._mode})"},
        )
