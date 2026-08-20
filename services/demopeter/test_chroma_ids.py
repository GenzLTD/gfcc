"""
测试 Chunk ID 格式是否会导致 Chroma 报错
"""
import sys
import os
import hashlib
import tempfile

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap_paths  # noqa: F401

def test_chroma_id_length():
    """测试不同 ID 格式是否能被 Chroma 接受"""
    import chromadb
    from chromadb.utils import embedding_functions
    
    with tempfile.TemporaryDirectory() as tmpdir:
        client = chromadb.PersistentClient(path=tmpdir)
        embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        
        collection = client.get_or_create_collection(
            name="test_ids",
            embedding_function=embedding_fn,
        )
        
        # 模拟各种 ID 格式
        test_ids = [
            # 格式 A: content_hash + path_hash (64 字符)
            "a" * 32 + "_" + "b" * 32 + "_chunk_0",
            
            # 格式 B: 很长的路径 + hash
            "C_" + "a" * 200 + "_chunk_0",
            
            # 格式 C: 超长 ID (400+ 字符)
            "x" * 500,
            
            # 格式 D: 包含特殊字符的路径
            "C__Users_Peter_Documents_项目A_代码_v1_测试文件_py_" + "c" * 32 + "_chunk_0",
        ]
        
        for i, id_str in enumerate(test_ids):
            try:
                collection.upsert(
                    ids=[id_str],
                    documents=[f"test document {i}"],
                    metadatas=[{"test": "true"}],
                )
                print(f"[OK] ID 格式 {i}: 长度={len(id_str)}, 成功写入")
            except Exception as e:
                print(f"[FAIL] ID 格式 {i}: 长度={len(id_str)}, 错误: {e}")
        
        print("\n建议：")
        print(f"- 格式 A (64 字符) 最安全")
        print(f"- 你的路径 MD5 + 内容 MD5 = 32+32+其他 = ~70 字符")

if __name__ == "__main__":
    test_chroma_id_length()
