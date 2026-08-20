"""
DScanner - D 盘文件扫描器

遍历预设的项目根目录，发现可索引的文本文件，
跳过二进制/大文件/构建产物，将内容切分为 chunk。
"""
import os
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterator
from datetime import datetime


# === 可索引的文件扩展名 ===
INDEXABLE_EXTENSIONS = {
    # Python
    ".py", ".pyw",
    # JavaScript / TypeScript
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    # Rust
    ".rs",
    # Go
    ".go",
    # PHP
    ".php", ".phtml",
    # Java
    ".java",
    # C / C++
    ".c", ".cpp", ".h", ".hpp",
    # Web
    ".html", ".htm", ".css", ".scss", ".less",
    # Config / Data
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".xml", ".env", ".properties",
    # Docs
    ".md", ".txt", ".rst", ".tex", ".adoc",
    # Shell
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    # Other text
    ".sql", ".graphql", ".proto", ".api",
    ".gitignore", ".dockerignore", ".editorconfig",
    # Lock files (small, useful for version info)
    ".lock",
}

# === 跳过的目录名 ===
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "target", "dist", "build", ".next", ".nuxt", "out",
    "data", "chroma_data", "chroma_docker", "db", "pgdata",
    "logs", ".cache", ".pytest_cache", ".mypy_cache", ".tox",
    "vendor", "bower_components", "coverage",
    "wp-content/uploads",  # WordPress uploads (images)
    "backup_*",  # Mac 备份压缩包
    # CMS 框架/库目录（WordPress / CodeIgniter 等）
    "rcsc",          # CodeIgniter system
    "bolent",        # szbolent CMS
    "woocms",        # WooCMS
    "woocommerce",   # WooCommerce
    "wp-includes",   # WordPress core
    "wp-admin",      # WordPress admin
}

# === 内容质量过滤：超长 Base64 字符串 ===
import re as _re
_BASE64_NOISE_PAT = _re.compile(r"[A-Za-z0-9+/]{300,}={0,2}")
# 对这些类型的文件额外检测 Base64 噪声
_BASE64_CHECK_TYPES = {".css", ".html", ".htm", ".lock"}

# === 最大文件大小 (字节) ===
MAX_FILE_SIZE = 50 * 1024  # 50KB

# === 分块参数 ===
CHUNK_SIZE = 1000   # 字符
CHUNK_OVERLAP = 200


@dataclass
class ScanConfig:
    """扫描配置"""
    project_roots: list[str] = field(default_factory=list)
    indexable_extensions: set[str] = field(default_factory=lambda: INDEXABLE_EXTENSIONS)
    skip_dirs: set[str] = field(default_factory=lambda: SKIP_DIRS)
    max_file_size: int = MAX_FILE_SIZE
    chunk_size: int = CHUNK_SIZE
    chunk_overlap: int = CHUNK_OVERLAP


@dataclass
class ScannedFile:
    """扫描到的文件"""
    file_path: str
    project_root: str
    file_type: str  # 扩展名，如 ".py"
    size_bytes: int
    last_modified: float  # timestamp
    fingerprint: str  # 内容 hash，用于去重
    content: str = ""  # 文件全文（读取后填充）


@dataclass
class Chunk:
    """文本分块"""
    chunk_id: str       # {fingerprint}_chunk_{i}
    file_path: str
    project_name: str   # 项目根目录名
    file_type: str
    content: str
    chunk_index: int
    total_chunks: int
    last_modified: float
    metadata: dict = field(default_factory=dict)


class DScanner:
    """D 盘文件扫描器"""

    def __init__(self, config: ScanConfig = None):
        self.config = config or ScanConfig()

    def scan(self) -> Iterator[ScannedFile]:
        """遍历所有项目目录，产出可索引的文件"""
        for root in self.config.project_roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            yield from self._scan_dir(root_path, root)

    def scan_with_resume(self, completed_dirs: set = None) -> Iterator[ScannedFile]:
        """
        断点续传式扫描 — 跳过已完成的目录。
        
        Args:
            completed_dirs: 已完整处理过的目录路径集合（来自 checkpoint）
        
        遍历逻辑与 scan() 相同，但跳过 completed_dirs 中的目录。
        注意：os.walk 中跳过 dirnames 可同时跳过子目录（性能优化）。
        """
        completed = completed_dirs or set()
        for root in self.config.project_roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            yield from self._scan_dir(root_path, root, skip_dirs_extra=completed)

    def scan_single_root(self, project_root: str,
                          completed_dirs: set = None) -> Iterator[ScannedFile]:
        """
        断点续传式扫描单个项目根目录。
        
        与 scan_with_resume 的区别：只扫描指定的一个根目录，
        不会误扫其他项目的文件。由 index_with_resume() 逐项目调用。
        
        Args:
            project_root: 单个项目根目录路径
            completed_dirs: 此项目已完成的目录集合
        """
        completed = completed_dirs or set()
        root_path = Path(project_root)
        if not root_path.exists():
            return
        yield from self._scan_dir(root_path, project_root, skip_dirs_extra=completed)

    def _scan_dir(self, root_path: Path, project_root: str,
                   skip_dirs_extra: set = None) -> Iterator[ScannedFile]:
        """递归扫描单个目录
        
        Args:
            skip_dirs_extra: 额外的目录路径集合（断点续传中已完成的目录）
            skip_dirs_extra 中的目录会阻止 os.walk 进入 + 阻止产出文件
        """
        extra = skip_dirs_extra or set()

        for dirpath, dirnames, filenames in os.walk(root_path):
            current_dir = str(Path(dirpath))

            # === 跳过黑名单目录 + 已完成目录 ===
            dirnames_copy = dirnames[:]
            for d in dirnames_copy:
                full_d = str(Path(dirpath) / d)
                if d in self.config.skip_dirs:
                    dirnames.remove(d)
                elif any(d.startswith(p.replace("*", "")) for p in self.config.skip_dirs if "*" in p):
                    dirnames.remove(d)
                elif full_d in extra:
                    # 已完成目录：阻止继续深入
                    dirnames.remove(d)

            # 如果当前目录本身在已完成集合中，跳过产出文件
            if current_dir in extra:
                continue

            current_dir_path = Path(dirpath)
            for fname in filenames:
                file_path = current_dir_path / fname
                ext = file_path.suffix.lower()

                if ext not in self.config.indexable_extensions:
                    continue

                try:
                    stat = file_path.stat()
                except OSError:
                    continue

                if stat.st_size > self.config.max_file_size:
                    continue

                if stat.st_size == 0:
                    continue

                file_type = ext[1:] if ext.startswith(".") else ext  # 去掉点

                yield ScannedFile(
                    file_path=str(file_path),
                    project_root=project_root,
                    file_type=file_type,
                    size_bytes=stat.st_size,
                    last_modified=stat.st_mtime,
                    fingerprint="",  # 读取后计算
                )

    def read_and_fingerprint(self, sf: ScannedFile) -> ScannedFile:
        """读取文件内容并计算指纹
        
        内容质量过滤：
        - CSS/HTML/lock 文件中若含超长 Base64 字符串（字体内嵌等），置空内容跳过
        """
        try:
            with open(sf.file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            content = ""

        # 内容质量过滤：检测超长 Base64（内嵌字体/图片数据）
        ext = Path(sf.file_path).suffix.lower()
        if ext in _BASE64_CHECK_TYPES and content and _BASE64_NOISE_PAT.search(content):
            content = ""  # 置空，indexer 会跳过该文件

        sf.content = content
        sf.fingerprint = hashlib.md5(content.encode("utf-8")).hexdigest()
        return sf

    def chunk_file(self, sf: ScannedFile) -> list[Chunk]:
        """将单个文件切分为多个 chunk

        chunk_id 策略（空间去重）：
        - 只用内容 hash + chunk 序号，去掉路径 hash
        - 同内容不同路径 → 相同 chunk_id → upsert 时合并路径，而非重复存储
        - 原始路径信息通过 metadata["source_paths"]（JSON 列表）保留
        """
        if not sf.content:
            return []

        content = sf.content
        project_name = Path(sf.project_root).name
        chunks = []

        # 短文本不需要切分
        if len(content) <= self.config.chunk_size:
            chunk = Chunk(
                chunk_id=f"{sf.fingerprint}_chunk_0",
                file_path=sf.file_path,
                project_name=project_name,
                file_type=sf.file_type,
                content=content,
                chunk_index=0,
                total_chunks=1,
                last_modified=sf.last_modified,
                metadata={
                    "size": sf.size_bytes,
                    "project_root": sf.project_root,
                },
            )
            chunks.append(chunk)
        else:
            # 滑动窗口切分
            step = self.config.chunk_size - self.config.chunk_overlap
            total = max(1, (len(content) - self.config.chunk_overlap + step - 1) // step)

            for i in range(total):
                start = i * step
                end = start + self.config.chunk_size
                chunk_text = content[start:end]

                chunk = Chunk(
                    chunk_id=f"{sf.fingerprint}_chunk_{i}",
                    file_path=sf.file_path,
                    project_name=project_name,
                    file_type=sf.file_type,
                    content=chunk_text,
                    chunk_index=i,
                    total_chunks=total,
                    last_modified=sf.last_modified,
                    metadata={
                        "size": sf.size_bytes,
                        "project_root": sf.project_root,
                    },
                )
                chunks.append(chunk)

        return chunks

    def get_stats(self) -> dict:
        """估算扫描范围统计"""
        total_files = 0
        total_size = 0
        projects_found = 0

        for root in self.config.project_roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            projects_found += 1
            for sf in self.scan_for_stats(root):
                total_files += 1
                total_size += sf.size_bytes

        return {
            "project_roots_configured": len(self.config.project_roots),
            "project_roots_accessible": projects_found,
            "indexable_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }

    def scan_for_stats(self, root: str) -> Iterator[ScannedFile]:
        """快速统计（不读内容）"""
        return self._scan_dir(Path(root), root)
