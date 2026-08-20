# 向量索引与检索（LlamaIndex + FAISS；可选 Haystack 流水线；Chroma 诗词检索）

# LlamaIndex 可能因 HF 网络问题导入失败，改为懒加载
def _lazy_import_llama():
    from .llama_index_rag import (
        build_index_from_dir,
        build_index_from_documents,
        load_index,
        get_query_engine,
        get_retriever,
    )
    return locals()

def __getattr__(name):
    if name in ("build_index_from_dir", "build_index_from_documents", "load_index", "get_query_engine", "get_retriever"):
        return _lazy_import_llama()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# chroma_poetry 是独立模块，不依赖 llama_index
from . import chroma_poetry
