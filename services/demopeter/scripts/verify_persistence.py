#!/usr/bin/env python3
"""
szpeter2026 — 数据持久化验证脚本
验证完整链路：文档导入 → 分块 → 向量化 → 存储 → 检索

用法:
    python scripts/verify_persistence.py              # 快速验证
    python scripts/verify_persistence.py --full       # 完整验证（含重新导入）
    python scripts/verify_persistence.py --docs ./data/test_docs  # 指定文档目录
"""

import sys
import os
import argparse
import tempfile
import numpy as np
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import config
from src.db_manager import DBManager
from src.vector_store import VectorStore
from src.doc_processor import DocumentProcessor
from src.pgvector_store import PgvectorStore


def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_result(label: str, ok: bool, detail: str = ""):
    icon = "✓" if ok else "✗"
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {icon} {label}")
    if detail:
        print(f"         {detail}")


def check_chroma_embedding():
    """检查 Chroma embedding 函数是否可用"""
    print_header("1. Chroma Embedding 函数检查")
    try:
        from chromadb.utils import embedding_functions
        ef = embedding_functions.DefaultEmbeddingFunction()
        # 测试一个小文本的向量化
        test_vec = ef(["测试文本"])
        ok = (
            test_vec is not None
            and len(test_vec) == 1
            and len(test_vec[0]) > 0
            and all(hasattr(v, '__float__') for v in test_vec[0])
        )
        dim = len(test_vec[0]) if ok else 0
        print_result("DefaultEmbeddingFunction 加载", True)
        print_result(f"向量维度: {dim}", True)
        print_result("测试文本向量化", ok, f"向量长度={dim}" if ok else "向量化返回空结果")
        return ok
    except ImportError as e:
        print_result("chromadb 导入", False, str(e))
        return False
    except Exception as e:
        print_result("Embedding 函数加载", False, str(e))
        return False


def check_vector_store_health(store: VectorStore):
    """检查向量存储健康状态"""
    print_header("2. Chroma 向量存储健康检查")
    health = store.health_check()
    
    print_result("集合已初始化", health["available"])
    print_result("运行模式", True, health["mode"])
    print_result("向量总数", True, str(health["total_vectors"]))
    
    emb_ok = health.get("embedding_ok")
    if emb_ok is True:
        print_result("Embedding 函数", True, "查询测试通过")
    elif emb_ok is False:
        print_result("Embedding 函数", False, health.get("embedding_error", "未知错误"))
    elif emb_ok is None:
        print_result("Embedding 函数", True, "向量库为空，跳过查询测试（正常）")
    
    return health


def test_pipeline():
    """测试完整的导入→检索管线"""
    print_header("3. 导入→检索 管线测试")
    
    # 创建临时测试文档
    test_content = """# 数据持久化测试文档

## 简介
这是一个用于验证 szpeter2026 知识库数据持久化的测试文档。

## 核心概念
向量数据库是现代 RAG 系统的核心组件，它将文本转换为高维向量，
通过余弦相似度计算实现语义检索。

## 测试要点
1. 文档导入后应在 SQLite 元数据库中有记录
2. 文本分块后应在 Chroma 向量库中有对应向量
3. 语义检索应能返回相关结果
4. 删除文档应同时清理元数据和向量数据
"""
    
    db = DBManager()
    store = VectorStore()
    processor = DocumentProcessor()
    
    # Step 1: 写入临时文件
    tmp_dir = Path(tempfile.gettempdir()) / "szpeter2026_test"
    tmp_dir.mkdir(exist_ok=True)
    test_file = tmp_dir / "persistence_test.md"
    test_file.write_text(test_content, encoding="utf-8")
    
    print(f"  → 创建测试文档: {test_file}")
    print_result("测试文档创建", test_file.exists())
    
    # Step 2: 注册文档
    try:
        doc_id = db.register_document(
            title="持久化测试文档",
            file_path=str(test_file),
            doc_type="md",
            file_size=test_file.stat().st_size,
        )
        print_result("SQLite 元数据注册", True, f"doc_id={doc_id}")
    except Exception as e:
        print_result("SQLite 元数据注册", False, str(e))
        return False
    
    # Step 3: 提取文本并分块
    try:
        text, chunks = processor.process_file(str(test_file))
        print_result("文本提取", bool(text), f"字符数={len(text)}")
        print_result("文本分块", len(chunks) > 0, f"分块数={len(chunks)}")
    except Exception as e:
        print_result("文本提取/分块", False, str(e))
        return False
    
    # Step 4: 保存分块到元数据库
    try:
        db.save_chunks(doc_id, chunks)
        print_result("分块保存到 SQLite", True, f"已保存 {len(chunks)} 个分块")
    except Exception as e:
        print_result("分块保存到 SQLite", False, str(e))
        return False
    
    # Step 5: 写入向量库
    if store.is_available:
        try:
            added = store.add_documents(str(doc_id), chunks)
            print_result("向量写入 Chroma", added > 0, f"写入 {added} 条向量")
        except Exception as e:
            print_result("向量写入 Chroma", False, str(e))
            added = 0
    else:
        print_result("向量写入 Chroma", False, "VectorStore 不可用")
        added = 0
    
    # Step 6: 写入后验证检索
    if added > 0:
        print_header("4. 检索验证")
        
        # 测试语义搜索
        test_queries = [
            "向量数据库是什么",
            "RAG 系统的核心组件",
            "余弦相似度",
        ]
        all_ok = True
        for query in test_queries:
            try:
                hits = store.search(query, top_k=3, threshold=0.0)
                found_our_doc = any(
                    str(doc_id) in h.get("id", "") for h in hits
                )
                print_result(
                    f"检索: '{query}'",
                    found_our_doc,
                    f"返回 {len(hits)} 条结果" + ("，找到测试文档" if found_our_doc else "，未找到测试文档")
                )
                if not found_our_doc:
                    all_ok = False
            except Exception as e:
                print_result(f"检索: '{query}'", False, str(e))
                all_ok = False
        
        # Health check
        health = store.health_check()
        print_result(
            "向量库健康检查",
            health.get("embedding_ok", False) is not False,
            f"embedding_ok={health.get('embedding_ok')}"
        )
    else:
        all_ok = False
        print_header("4. 检索验证")
        print_result("检索验证", False, "无向量数据，跳过")
    
    # Step 7: 清理测试数据
    print_header("5. 清理测试数据")
    try:
        store.delete_document(str(doc_id))
        print_result("向量数据清理", True)
    except Exception as e:
        print_result("向量数据清理", False, str(e))
    
    try:
        db.delete_document(doc_id)
        print_result("SQLite 元数据清理", True)
    except Exception as e:
        print_result("SQLite 元数据清理", False, str(e))
    
    # 清理临时文件
    try:
        test_file.unlink()
        tmp_dir.rmdir()
    except Exception:
        pass
    
    return all_ok


def check_pgvector():
    """检查 pgvector 状态（不影响主流程）"""
    print_header("附: pgvector 状态检查")
    try:
        pg = PgvectorStore()
        print_result("pgvector 连接", pg.is_available, 
                     "Ollama 可用的 PostgreSQL pgvector 后端" if pg.is_available else "未启用或不可达")
        if not pg.is_available:
            print("  ℹ️  pgvector 需本地运行 Ollama + PostgreSQL，不影响 Chroma 主流程")
    except Exception as e:
        print_result("pgvector 连接", False, str(e))


def main():
    parser = argparse.ArgumentParser(description="szpeter2026 数据持久化验证")
    parser.add_argument("--full", action="store_true", help="完整验证（含管线测试）")
    parser.add_argument("--skip-cleanup", action="store_true", help="保留测试数据")
    args = parser.parse_args()
    
    print("=" * 60)
    print("  szpeter2026 — 数据持久化验证")
    print(f"  项目路径: {PROJECT_ROOT}")
    print(f"  Chroma 模式: {config.CHROMA_MODE}")
    print(f"  检索模式: {config.SEARCH_MODE}")
    print("=" * 60)
    
    results = []
    
    # 1. Embedding 函数检查
    emb_ok = check_chroma_embedding()
    results.append(("Embedding 函数", emb_ok))
    
    # 2. 向量存储健康检查
    store = VectorStore()
    health = check_vector_store_health(store)
    results.append(("向量存储", health["available"]))
    
    # 3. 管线测试
    if args.full or health.get("total_vectors", 0) == 0:
        pipeline_ok = test_pipeline()
        results.append(("导入→检索 管线", pipeline_ok))
    else:
        print_header("3. 导入→检索 管线测试")
        print("  ℹ️  向量库已有数据，跳过管线测试（使用 --full 强制运行）")
    
    # 4. pgvector 状态
    check_pgvector()
    
    # 汇总
    print_header("验证结果汇总")
    all_pass = True
    for name, ok in results:
        print_result(name, ok)
        if not ok:
            all_pass = False
    
    print()
    if all_pass:
        print("  🎉 所有检查通过！数据持久化链路正常。")
    else:
        print("  ⚠️ 部分检查未通过，请根据上述 FAIL 项排查。")
        print()
        print("  常见修复步骤:")
        print("  1. pip install onnxruntime>=1.18.0")
        print("  2. 确认 .env 中 CHROMA_MODE=persistent")
        print("  3. 确认 .env 中 PGVECTOR_ENABLED=false (无 Ollama 时)")
        print("  4. 删除 db/chroma_data/ 目录后重新导入文档")
    
    print()
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
