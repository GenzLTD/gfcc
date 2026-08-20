"""
szpeter2026 知识库 - 统一配置中心
吸收自 Wukong 项目的配置管理模式，支持 .env + 默认值
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 加载 .env
load_dotenv(PROJECT_ROOT / ".env", override=False)


class Config:
    """全局配置"""

    # ===== 项目路径 =====
    PROJECT_ROOT: Path = PROJECT_ROOT
    DB_DIR: Path = PROJECT_ROOT / "db"
    KB_DIR: Path = PROJECT_ROOT / "knowledge_base"
    DOCS_DIR: Path = KB_DIR / "documents"
    CHUNKS_DIR: Path = KB_DIR / "chunks"
    UPLOAD_DIR: Path = PROJECT_ROOT / "data" / "uploads"
    TEMPLATES_DIR: Path = PROJECT_ROOT / "templates"
    STATIC_DIR: Path = PROJECT_ROOT / "static"
    SCRIPTS_DIR: Path = PROJECT_ROOT / "scripts"

    # ===== 元数据库 =====
    METADATA_DB: str = str(DB_DIR / "szpeter2026.db")

    # ===== AI 配置 =====
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "deepseek")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2:latest")

    # ===== 向量数据库 =====
    # 模式: "auto"(默认,优先远程→回退本地) / "persistent"(仅本地文件) / "remote"(仅Docker服务)
    CHROMA_MODE: str = os.getenv("CHROMA_MODE", "auto")
    CHROMA_HOST: str = os.getenv("CHROMA_HOST", "localhost")
    CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8001"))
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "szpeter2026_kb")
    # Chroma 持久化目录（可覆盖，支持代码和数据分离部署）
    CHROMA_PERSIST_DIR: str = os.getenv(
        "CHROMA_PERSIST_DIR",
        str(DB_DIR / "chroma_data"),
    )

    # ===== pgvector 向量数据库（可选） =====
    PGVECTOR_ENABLED: bool = os.getenv("PGVECTOR_ENABLED", "false").lower() == "true"
    PGVECTOR_HOST: str = os.getenv("PGVECTOR_HOST", "localhost")
    PGVECTOR_PORT: int = int(os.getenv("PGVECTOR_PORT", "5432"))
    PGVECTOR_USER: str = os.getenv("PGVECTOR_USER", "szpeter")
    PGVECTOR_PASSWORD: str = os.getenv("PGVECTOR_PASSWORD", "Szpeter2026!")
    PGVECTOR_DATABASE: str = os.getenv("PGVECTOR_DATABASE", "szpeter2026")
    PGVECTOR_EMBEDDING_DIM: int = int(os.getenv("PGVECTOR_EMBEDDING_DIM", "768"))

    # ===== Ollama Embedding 模型 =====
    OLLAMA_EMBEDDING_MODEL: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:latest")

    # ===== Web 配置 =====
    WEB_HOST: str = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT: int = int(os.getenv("WEB_PORT", "5220"))
    WEB_DEBUG: bool = os.getenv("WEB_DEBUG", "false").lower() == "true"

    # ===== 文档处理 =====
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))

    # ===== 检索模式 =====
    # hybrid: 向量 + FTS5 RRF 融合 | vector: 仅向量（降级链） | keyword: 仅关键词
    SEARCH_MODE: str = os.getenv("SEARCH_MODE", "hybrid")
    HYBRID_RRF_K: int = int(os.getenv("HYBRID_RRF_K", "60"))
    VECTOR_WEIGHT: float = float(os.getenv("VECTOR_WEIGHT", "0.7"))
    KEYWORD_WEIGHT: float = float(os.getenv("KEYWORD_WEIGHT", "0.3"))

    # ===== 融合测试语料（Projects 目录） =====
    CORPUS_CONFIG: Path = PROJECT_ROOT / "config" / "corpora.json"
    PROJECTS_ROOT: Path = Path(os.getenv("PROJECTS_ROOT", "/Users/jason/Projects"))
    CAREERINTL_DIR: Path = PROJECTS_ROOT / "300662科锐国际"
    PYTHON_BOOK_DIR: Path = PROJECTS_ROOT / "数据分析与python实战-代码"

    # 兼容旧配置：单目录语料（ImartOS 大规模语料）
    DEFAULT_CORPUS_DIR: Path = Path(
        os.getenv(
            "DEFAULT_CORPUS_DIR",
            str(PROJECTS_ROOT / "300662科锐国际"),
        )
    )
    USE_FUSED_CORPUS: bool = os.getenv("USE_FUSED_CORPUS", "true").lower() == "true"

    # ===== Notion 集成 =====
    NOTION_TOKEN: str = os.getenv("NOTION_TOKEN", "")
    NOTION_DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")

    # ===== Gitea Webhook =====
    GITEA_WEBHOOK_SECRET: str = os.getenv("GITEA_WEBHOOK_SECRET", "")
    GITEA_BASE_URL: str = os.getenv("GITEA_BASE_URL", "")

    # ===== Outlook / Microsoft Graph OAuth2 =====
    OUTLOOK_CLIENT_ID: str = os.getenv("OUTLOOK_CLIENT_ID", "")
    OUTLOOK_CLIENT_SECRET: str = os.getenv("OUTLOOK_CLIENT_SECRET", "")
    OUTLOOK_REDIRECT_URI: str = os.getenv("OUTLOOK_REDIRECT_URI", "http://localhost:5220/auth/outlook/callback")
    OUTLOOK_TOKEN_PATH: str = str(DB_DIR / "outlook_tokens.json")

    # ===== 外部数据库（可选） =====
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "")
    PG_HOST: str = os.getenv("PG_HOST", "")
    PG_PORT: int = int(os.getenv("PG_PORT", "5432"))
    PG_USER: str = os.getenv("PG_USER", "")
    PG_PASSWORD: str = os.getenv("PG_PASSWORD", "")
    PG_DATABASE: str = os.getenv("PG_DATABASE", "")

    # ===== Ollama 模型路径 =====
    # 官方 GUI 默认路径: ~/.ollama/models
    # 环境变量可覆盖: OLLAMA_MODELS
    OLLAMA_MODELS_DIR: str = os.getenv(
        "OLLAMA_MODELS",
        str(Path.home() / ".ollama" / "models"),
    )

    def __repr__(self) -> str:
        return f"<Config provider={self.AI_PROVIDER}, web={self.WEB_HOST}:{self.WEB_PORT}>"

    def health_check(self) -> dict:
        """启动时健康检查 — 验证关键路径和依赖是否存在

        Returns:
            {"ok": True/False, "warnings": [...], "errors": [...]}
        """
        import socket
        warnings = []
        errors = []

        # 1. Chroma 持久化目录
        chroma_dir = Path(self.CHROMA_PERSIST_DIR)
        if not chroma_dir.exists():
            errors.append(f"Chroma 目录不存在: {self.CHROMA_PERSIST_DIR}")
        else:
            sqlite_file = chroma_dir / "chroma.sqlite3"
            if not sqlite_file.exists():
                warnings.append(f"Chroma SQLite 不存在 ({sqlite_file})- 将自动创建")

        # 2. Ollama 模型目录
        ollama_models = Path(self.OLLAMA_MODELS_DIR)
        if not ollama_models.exists():
            warnings.append(
                f"Ollama 模型目录不存在: {self.OLLAMA_MODELS_DIR} — "
                "如使用 Chroma 默认嵌入则无影响"
            )

        # 3. Ollama 服务可达性
        try:
            host = self.OLLAMA_BASE_URL.replace("http://", "").replace("https://", "").split(":")[0]
            port = int(self.OLLAMA_BASE_URL.split(":")[-1])
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            if result != 0:
                warnings.append(
                    f"Ollama 服务不可达 ({self.OLLAMA_BASE_URL}) — "
                    "如使用 Chroma 默认嵌入或云端 LLM 则无影响"
                )
        except Exception:
            warnings.append(f"Ollama 地址格式异常: {self.OLLAMA_BASE_URL}")

        # 4. D 盘项目路径（仅检查 d_indexer 用到的）
        try:
            from d_indexer.projects import D_PROJECT_ROOTS
            missing = []
            for root in D_PROJECT_ROOTS:
                if not Path(root).exists():
                    missing.append(root)
            if missing:
                warnings.append(f"D 盘 {len(missing)} 个项目路径不存在: {missing[:3]}...")
        except ImportError:
            pass  # d_indexer 可能还没装

        # 5. 必要目录自动创建
        for d in [self.DB_DIR, self.KB_DIR, self.DOCS_DIR, self.CHUNKS_DIR,
                  self.UPLOAD_DIR, self.TEMPLATES_DIR, self.STATIC_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        # 6. AI 配置
        if self.AI_PROVIDER == "deepseek" and not self.DEEPSEEK_API_KEY:
            warnings.append("DeepSeek API Key 未设置 — 仅检索模式可用")

        return {
            "ok": len(errors) == 0,
            "warnings": warnings,
            "errors": errors,
            "checks": {
                "chroma_dir": str(self.CHROMA_PERSIST_DIR),
                "chroma_exists": Path(self.CHROMA_PERSIST_DIR).exists(),
                "ollama_url": self.OLLAMA_BASE_URL,
                "ollama_models_dir": self.OLLAMA_MODELS_DIR,
                "ollama_models_exist": Path(self.OLLAMA_MODELS_DIR).exists(),
            },
        }


# 单例
config = Config()
