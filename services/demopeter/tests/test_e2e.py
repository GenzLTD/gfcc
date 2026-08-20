"""
szpeter2026 - 端到端测试套件
吸收自 Wukong test_e2e.py 的结构
"""
import sys
import os
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import config
from src.db_manager import DBManager
from src.doc_processor import DocumentProcessor


class TestDBManager(unittest.TestCase):
    """元数据库管理器测试"""

    @classmethod
    def setUpClass(cls):
        cls.db = DBManager()

    def _unique_path(self, name: str) -> str:
        """生成唯一的测试文件路径，避免 UNIQUE 约束冲突"""
        import time as _time
        return f"/test/{name}_{_time.time():.0f}_{id(self)}.txt"

    def test_01_stats(self):
        """获取统计信息"""
        stats = self.db.get_stats()
        self.assertIn("documents_total", stats)
        self.assertIn("chunks_total", stats)
        self.assertIn("queries_total", stats)
        self.assertIsInstance(stats["documents_total"], int)

    def test_02_register_document(self):
        """注册文档"""
        path = self._unique_path("sample")
        doc_id = self.db.register_document(
            title="测试文档",
            file_path=path,
            doc_type="txt",
            file_size=1024,
        )
        self.assertIsNotNone(doc_id)
        self.assertGreater(doc_id, 0)

        doc = self.db.get_document(doc_id)
        self.assertEqual(doc["title"], "测试文档")
        self.assertEqual(doc["status"], "pending")

    def test_03_save_chunks(self):
        """保存分块"""
        path = self._unique_path("chunks")
        doc_id = self.db.register_document(
            title="测试文档",
            file_path=path,
            doc_type="txt",
            file_size=1024,
        )
        chunks = [
            {"index": 0, "content": "这是第一个测试分块", "metadata": {"page": 1}},
            {"index": 1, "content": "这是第二个测试分块", "metadata": {"page": 1}},
        ]
        self.db.save_chunks(doc_id, chunks)

        saved = self.db.get_chunks(doc_id)
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["chunk_index"], 0)

        self.db.update_document_status(doc_id, "completed", 2)
        doc = self.db.get_document(doc_id)
        self.assertEqual(doc["status"], "completed")
        self.assertEqual(doc["chunk_count"], 2)

    def test_04_log_query(self):
        """记录查询日志"""
        self.db.log_query("测试查询", "deepseek", 1234.5, 3)
        queries = self.db.get_recent_queries(limit=1)
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["query_text"], "测试查询")

    def test_05_delete_document(self):
        """删除文档"""
        path = self._unique_path("delete")
        doc_id = self.db.register_document(
            title="测试文档",
            file_path=path,
            doc_type="txt",
            file_size=1024,
        )
        chunks = [
            {"index": 0, "content": "临时分块", "metadata": {}},
        ]
        self.db.save_chunks(doc_id, chunks)
        self.db.update_document_status(doc_id, "completed", 1)

        self.db.delete_document(doc_id)
        doc = self.db.get_document(doc_id)
        self.assertIsNone(doc)

    def test_06_get_documents_by_status(self):
        """按状态过滤文档"""
        docs = self.db.get_documents(status="completed")
        self.assertIsInstance(docs, list)


class TestDocumentProcessor(unittest.TestCase):
    """文档处理器测试"""

    @classmethod
    def setUpClass(cls):
        cls.processor = DocumentProcessor()
        # 创建测试文件
        cls.test_dir = config.PROJECT_ROOT / "knowledge_base" / "documents" / "md"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.test_file = cls.test_dir / "test_sample.md"
        cls.test_file.write_text("""# 测试文档

## 第一章

这是第一章的内容，用于测试文档处理管道。

## 第二章

这是第二章的内容，包含更多测试文本。

### 2.1 小节

这是小节的内容。

## 第三章

这是最后一章的内容。""", encoding="utf-8")

    def test_10_extract_markdown(self):
        """提取 Markdown 文本"""
        text = self.processor.extract_text(str(self.test_file))
        self.assertIn("测试文档", text)
        self.assertIn("第一章", text)

    def test_11_chunk_text(self):
        """文本分块"""
        text = "这是一个测试段落。\n\n这是第二个测试段落。\n\n这是第三个测试段落。"
        chunks = self.processor.chunk_text(text, metadata={"source": "test"})
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertIn("content", chunk)
            self.assertIn("index", chunk)

    def test_12_scan_directory(self):
        """扫描目录"""
        files = self.processor.scan_directory(str(self.test_dir))
        self.assertGreater(len(files), 0)
        types = {f["doc_type"] for f in files}
        self.assertIn("md", types)

    def test_13_process_file(self):
        """处理单个文件"""
        text, chunks = self.processor.process_file(str(self.test_file))
        self.assertIsInstance(text, str)
        self.assertIsInstance(chunks, list)
        self.assertGreater(len(text), 0)

    @classmethod
    def tearDownClass(cls):
        if cls.test_file.exists():
            cls.test_file.unlink()


class TestConfig(unittest.TestCase):
    """配置测试"""

    def test_20_config_exists(self):
        """配置可访问"""
        self.assertIsNotNone(config.PROJECT_ROOT)
        self.assertTrue(config.PROJECT_ROOT.exists())

    def test_21_paths_exist(self):
        """关键路径存在"""
        self.assertTrue(config.DB_DIR.exists())
        self.assertTrue(config.KB_DIR.exists())
        self.assertTrue(config.DOCS_DIR.exists())

    def test_22_env_vars(self):
        """环境变量有默认值"""
        self.assertIsInstance(config.CHUNK_SIZE, int)
        self.assertIsInstance(config.CHUNK_OVERLAP, int)
        self.assertIsInstance(config.WEB_PORT, int)
        self.assertIn(config.AI_PROVIDER, ("deepseek", "ollama", ""))


class TestIntegration(unittest.TestCase):
    """集成测试"""

    @classmethod
    def setUpClass(cls):
        cls.db = DBManager()
        cls.processor = DocumentProcessor()

    def test_30_full_pipeline(self):
        """完整流程：注册 → 处理 → 分块 → 保存 → 查询"""
        test_file = config.DOCS_DIR / "md" / "test_sample.md"
        if not test_file.exists():
            self.skipTest("测试文件不存在")

        # 1. 注册文档
        doc_id = self.db.register_document(
            title=test_file.stem,
            file_path=str(test_file),
            doc_type="md",
            file_size=test_file.stat().st_size,
        )

        # 2. 处理文档
        text, chunks = self.processor.process_file(str(test_file))
        self.assertGreater(len(text), 0)
        self.assertGreater(len(chunks), 0)

        # 3. 保存分块
        self.db.save_chunks(doc_id, chunks)
        saved = self.db.get_chunks(doc_id)
        self.assertEqual(len(saved), len(chunks))

        # 4. 更新状态
        self.db.update_document_status(doc_id, "completed", len(chunks))
        doc = self.db.get_document(doc_id)
        self.assertEqual(doc["status"], "completed")

        # 5. 清理
        self.db.delete_document(doc_id)


if __name__ == "__main__":
    print("=" * 60)
    print("  szpeter2026 端到端测试套件")
    print("=" * 60)
    unittest.main(verbosity=2)
