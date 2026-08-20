"""
d_indexer - D 盘自动扫描索引模块

定期扫描 D 盘项目目录，提取文本内容，向量化存入 Chroma，
支持语义搜索"那个做跨境电商的项目在哪"。

三层架构 + 断点续传：
- scanner: 文件扫描 + 文本提取（支持跳过已完成目录）
- indexer: Chroma 嵌入 + 存储（支持断点续传）
- scheduler: 每日定时触发（支持崩溃后自动续传）
- checkpoint: SQLite 断点管理器（持久化扫描状态）
"""
from .scanner import DScanner, ScanConfig
from .indexer import DIndexer, SearchResult
from .scheduler import DScheduler
from .checkpoint import ScanCheckpoint, ScanProgress

__all__ = [
    "DScanner", "ScanConfig",
    "DIndexer", "SearchResult",
    "DScheduler",
    "ScanCheckpoint", "ScanProgress",
]
