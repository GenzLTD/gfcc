r"""
Cursor JSONL 对话解析器

解析 C:\Users\HUAWEI\.cursor\projects\ 下的 .jsonl 对话文件，
提取 user/assistant 轮次，按主题分块，生成适合 RAG 入库的结构化数据。

使用方式:
    from scripts.cursor_parser import CursorParser

    parser = CursorParser()
    sessions = parser.scan_all_projects()
    for session in sessions:
        chunks = parser.session_to_chunks(session)
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Iterator, Optional
from dataclasses import dataclass, field

# Cursor projects 根目录
CURSOR_PROJECTS_DIR = Path(r"C:\Users\HUAWEI\.cursor\projects")

# 项目路径 → 友好名称 + D 盘项目映射
PROJECT_MAPPING = {
    # === Zervi 核心 ===
    "d-ServBay-www-zervi-rust": {
        "name": "Zervi-Rust 中央大脑",
        "d_project": "D:/surface-zervi",
        "tags": ["微服务", "Rust", "API Gateway", "Consul", "架构"],
    },
    "d-ServBay-www-zervi-rust-jobfirst-claw": {
        "name": "JobFirstClaw 求职AI",
        "d_project": "D:/jobfirst-claw",
        "tags": ["求职", "AI", "Rust", "ZeroClaw"],
    },
    "d-ServBay-www-zervi-test": {
        "name": "Zervi-Test 测试环境",
        "tags": ["测试", "调试"],
    },

    # === 微服务 ===
    "e-Nezha": {
        "name": "Nezha Spring AI",
        "d_project": "D:/Nezha",
        "tags": ["Spring Boot", "Spring AI", "DeepSeek", "Chroma", "架构"],
    },
    "e-SmartJobs": {
        "name": "SmartJobs 智能招聘",
        "d_project": "D:/SmartJobs",
        "tags": ["招聘", "微服务", "Consul", "双云部署"],
    },
    "e-SmartJobs-smart-job": {
        "name": "SmartJobs Smart-Job 子模块",
        "d_project": "D:/SmartJobs/smart-job",
        "tags": ["招聘", "微服务"],
    },

    # === 社区/平台 ===
    "e-Iamgeek": {
        "name": "Iamgeek 匿名社区",
        "d_project": "D:/Iamgeek",
        "tags": ["Web3", "匿名社区", "Admin", "Refine", "Ant Design"],
    },
    "e-StudyDaily-TimesSquare-main": {
        "name": "TimesSquare 知识库",
        "d_project": "D:/TimesSquare",
        "tags": ["知识库", "Brahman", "双知识库", "Tatha"],
    },
    "e-StudyDaily-looma-main-looma-main": {
        "name": "Looma 主项目",
        "d_project": "D:/looma",
        "tags": ["管理看板", "Brahman", "Console", "Claw"],
    },

    # === IoT / 小程序 ===
    "e-Yesall": {
        "name": "Yesall 智慧办公",
        "tags": ["IoT", "微信小程序", "openvela", "楼宇"],
    },
    "e-YeDall": {
        "name": "YeDall IoT",
        "d_project": "D:/YeDall",
        "tags": ["IoT", "智能家居"],
    },
    "e-YeDall2-0": {
        "name": "YeDall 2.0",
        "d_project": "D:/YeDall2.0",
        "tags": ["IoT", "智能家居"],
    },
    "e-FiveBlessings": {
        "name": "五福项目集",
        "d_project": "D:/FiveBlessings",
        "tags": ["创业", "多项目"],
    },
    "e-FiveBlessings-JobFirst": {
        "name": "五福-JobFirst",
        "d_project": "D:/FiveBlessings/JobFirst",
        "tags": ["招聘", "小程序"],
    },

    # === 数据库/工具 ===
    "c-Users-HUAWEI-DataGripProjects-Qiankun": {
        "name": "Qiankun 数据库优化",
        "tags": ["MySQL", "PostgreSQL", "数据库优化", "索引", "安全"],
    },
    "c-Users-HUAWEI-DemoPeter": {
        "name": "DemoPeter 知识库",
        "tags": ["RAG", "知识库", "Chroma", "Python"],
    },
    "c-Users-HUAWEI-yedall-monitor": {
        "name": "YeDall 监控",
        "tags": ["监控", "运维"],
    },
    "c-Users-HUAWEI": {
        "name": "系统运维",
        "tags": ["运维", "磁盘", "Docker"],
    },

    # === 其他 ===
    "e-Jobfirst": {
        "name": "Jobfirst 原型",
        "d_project": "D:/Jobfirst",
        "tags": ["招聘", "小程序", "原型"],
    },
    "e-JobfirstClaw": {
        "name": "JobfirstClaw 变体",
        "d_project": "D:/JobfirstClaw",
        "tags": ["求职", "Rust"],
    },
    "e-Ctrl4U": {
        "name": "Ctrl4U 鸿蒙应用",
        "d_project": "D:/Ctrl4U",
        "tags": ["HarmonyOS", "IoT"],
    },
    "e-StudyDaily": {
        "name": "StudyDaily 学习",
        "d_project": "D:/StudyDaily",
        "tags": ["学习", "笔记"],
    },
    "e-zervi": {
        "name": "Zervi 项目集",
        "d_project": "D:/zervi",
        "tags": ["WordPress", "PHP"],
    },
    "e-looma": {
        "name": "Looma 工作区",
        "d_project": "D:/looma",
        "tags": ["工作区"],
    },
    "empty-window": {
        "name": "空窗口对话",
        "tags": ["讨论", "架构"],
    },
}

# 对话轮次角色
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

# 对话分块参数
CONVERSATION_CHUNK_SIZE = 2000      # 每块最大字符数
CONVERSATION_CHUNK_OVERLAP = 300    # 块间重叠字符数

# 敏感信息脱敏规则
SENSITIVE_PATTERNS = [
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?\b', '[IP]'),      # IP 地址
    (r'sk-[a-zA-Z0-9]{20,}', '[API_KEY]'),                              # OpenAI/DeepSeek Key
    (r'DEEPSEEK_API_KEY\s*=\s*\S+', 'DEEPSEEK_API_KEY=[REDACTED]'),     # .env key
    (r'password\s*[:=]\s*\S+', 'password=[REDACTED]', re.IGNORECASE),   # 密码
    (r'secret\s*[:=]\s*\S+', 'secret=[REDACTED]', re.IGNORECASE),       # secret
]


@dataclass
class CursorSession:
    """一个 Cursor 对话会话"""
    session_id: str
    project_dir: str          # Cursor 项目目录名
    project_name: str         # 友好名称
    d_project: str            # 对应 D 盘项目路径
    tags: list[str]
    file_path: str            # JSONL 文件路径
    turns: list[dict] = field(default_factory=list)    # 对话轮次
    total_chars: int = 0
    turn_count: int = 0
    first_timestamp: str = ""
    last_timestamp: str = ""


@dataclass
class ConversationChunk:
    """一个对话分块"""
    chunk_id: str
    session_id: str
    project_name: str
    d_project: str
    tags: list[str]
    content: str
    turn_range: tuple[int, int]  # (起始轮次, 结束轮次)
    metadata: dict = field(default_factory=dict)


class CursorParser:
    """Cursor 对话解析器"""

    def __init__(self, projects_dir: Path | str | None = None):
        self.projects_dir = Path(projects_dir or CURSOR_PROJECTS_DIR)
        self.chunk_size = CONVERSATION_CHUNK_SIZE
        self.chunk_overlap = CONVERSATION_CHUNK_OVERLAP

    # ===== 扫描 =====

    def scan_all_projects(self, skip_temp: bool = True) -> list[CursorSession]:
        """扫描所有 Cursor 项目目录，返回会话列表"""
        sessions = []
        for project_dir in sorted(self.projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue

            dir_name = project_dir.name

            # 跳过临时目录
            if skip_temp and dir_name.startswith("C-Users-HUAWEI-AppData-Local-Temp-"):
                continue

            # 获取项目元信息
            meta = PROJECT_MAPPING.get(dir_name, {})
            project_name = meta.get("name", self._infer_project_name(dir_name))
            d_project = meta.get("d_project", "")
            tags = meta.get("tags", [])

            # 查找 agent-transcripts
            transcripts_dir = project_dir / "agent-transcripts"
            if not transcripts_dir.exists():
                continue

            for session_dir in transcripts_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                for jsonl_file in session_dir.glob("*.jsonl"):
                    try:
                        session = self.parse_session(
                            jsonl_file,
                            session_id=session_dir.name,
                            project_dir=dir_name,
                            project_name=project_name,
                            d_project=d_project,
                            tags=tags,
                        )
                        if session and session.turns:
                            sessions.append(session)
                    except Exception as e:
                        print(f"  ⚠ 解析失败 {jsonl_file.name}: {e}")

        return sessions

    def parse_session(
        self,
        jsonl_path: Path,
        session_id: str = "",
        project_dir: str = "",
        project_name: str = "",
        d_project: str = "",
        tags: list[str] | None = None,
    ) -> Optional[CursorSession]:
        """解析单个 JSONL 文件为 CursorSession"""
        turns = []
        total_chars = 0

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = record.get("role", "")
                if role not in (ROLE_USER, ROLE_ASSISTANT):
                    continue

                # 提取文本内容
                text = self._extract_text(record)
                if not text:
                    continue

                # 脱敏
                text = self._sanitize(text)

                turns.append({
                    "role": role,
                    "text": text,
                    "char_count": len(text),
                })
                total_chars += len(text)

        if not turns:
            return None

        return CursorSession(
            session_id=session_id or jsonl_path.stem,
            project_dir=project_dir,
            project_name=project_name,
            d_project=d_project,
            tags=tags or [],
            file_path=str(jsonl_path),
            turns=turns,
            total_chars=total_chars,
            turn_count=len(turns),
        )

    def _extract_text(self, record: dict) -> str:
        """从 Cursor JSONL 记录中提取文本"""
        message = record.get("message", {})
        content = message.get("content", [])

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "")
                    if item_type == "text":
                        text = item.get("text", "")
                        if text:
                            # 去掉 <user_query> 等 XML 标签
                            text = re.sub(r'</?user_query>', '', text)
                            parts.append(text.strip())
                    elif item_type == "tool_use":
                        # 工具调用记录：提取工具名和简要参数
                        tool_name = item.get("name", "unknown_tool")
                        tool_input = item.get("input", {})
                        # 只保留关键参数摘要
                        summary = self._summarize_tool_input(tool_name, tool_input)
                        if summary:
                            parts.append(f"[工具调用: {tool_name}] {summary}")
            return "\n".join(p for p in parts if p).strip()

        return ""

    def _summarize_tool_input(self, tool_name: str, tool_input: dict) -> str:
        """摘要化工具调用参数（避免入库过长的文件内容）"""
        if tool_name in ("Read", "read_file"):
            fp = tool_input.get("filePath", "")
            return f"读取文件: {Path(fp).name}" if fp else ""
        if tool_name in ("Grep", "search_content"):
            return f"搜索: {tool_input.get('pattern', '')[:80]}"
        if tool_name in ("Glob", "search_file"):
            return f"查找: {tool_input.get('pattern', '')}"
        if tool_name in ("Bash", "Shell", "execute_command"):
            cmd = tool_input.get("command", "")
            return f"执行: {cmd[:120]}"
        if tool_name in ("Write", "write_to_file", "Edit", "replace_in_file"):
            fp = tool_input.get("filePath", "")
            return f"编辑: {Path(fp).name}" if fp else ""
        return ""

    # ===== 分块 =====

    def session_to_chunks(self, session: CursorSession) -> list[ConversationChunk]:
        """将会话按对话轮次边界智能分块"""
        chunks = []
        current_lines = []
        current_chars = 0
        start_turn = 0
        turn_idx = 0

        for i, turn in enumerate(session.turns):
            line = f"[{turn['role'].upper()}] {turn['text']}"
            line_len = len(line)

            if current_chars + line_len > self.chunk_size and current_lines:
                # 保存当前块
                chunk_text = "\n\n".join(current_lines)
                chunks.append(self._make_chunk(
                    session, chunk_text, start_turn, i - 1
                ))

                # 重叠：保留最后一段作为上下文
                overlap_text = chunk_text[-self.chunk_overlap:] if self.chunk_overlap else ""
                if overlap_text:
                    current_lines = [f"[上下文延续]\n{overlap_text}"]
                    current_chars = len(overlap_text)
                else:
                    current_lines = []
                    current_chars = 0
                start_turn = i

            current_lines.append(line)
            current_chars += line_len
            turn_idx = i

        # 最后一个块
        if current_lines:
            chunk_text = "\n\n".join(current_lines)
            chunks.append(self._make_chunk(
                session, chunk_text, start_turn, turn_idx
            ))

        return chunks

    def _make_chunk(
        self,
        session: CursorSession,
        text: str,
        start: int,
        end: int,
    ) -> ConversationChunk:
        chunk_id = f"cursor_{session.session_id}_{start}_{end}"
        return ConversationChunk(
            chunk_id=chunk_id,
            session_id=session.session_id,
            project_name=session.project_name,
            d_project=session.d_project,
            tags=session.tags,
            content=text,
            turn_range=(start, end),
            metadata={
                "source": "cursor_transcript",
                "session_id": session.session_id,
                "project_dir": session.project_dir,
                "project_name": session.project_name,
                "d_project": session.d_project,
                "tags": ",".join(session.tags),
                "turn_start": start,
                "turn_end": end,
                "total_turns": session.turn_count,
                "file_path": session.file_path,
            },
        )

    # ===== 辅助 =====

    @staticmethod
    def _sanitize(text: str) -> str:
        """脱敏处理"""
        for pattern, replacement, *flags in SENSITIVE_PATTERNS:
            flag = flags[0] if flags else 0
            text = re.sub(pattern, replacement, text, flags=flag)
        return text

    @staticmethod
    def _infer_project_name(dir_name: str) -> str:
        """从目录名推断项目名"""
        # 去掉前缀 (d-, e-, f-, c-)
        name = dir_name
        for prefix in ("d-ServBay-www-", "e-", "f-", "c-Users-HUAWEI-", "d-e-", "d-"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        # 连字符转空格
        name = name.replace("-", " ")
        # 首字母大写
        return " ".join(w.capitalize() if w.islower() else w for w in name.split())

    # ===== Chronicle 事件提取 =====

    def extract_chronicle_events(self, session: CursorSession) -> list[dict]:
        """从会话中提取 Chronicle 事件种子

        分析 assistant 轮次中的 tool_use，自动分类为：
        - 决策 (DECISION): 包含"为什么/因为/建议/方案"等关键词的讨论
        - 操作 (ACTION): Write/Edit/Bash 等实际操作
        - 发现 (DISCOVERY): 包含"发现/问题/错误"等关键词
        - 配置 (CONFIG): 修改配置/env/docker 等
        - 对话 (CONVERSATION): 其他值得记录的讨论
        """
        events = []
        for i, turn in enumerate(session.turns):
            if turn["role"] != ROLE_ASSISTANT:
                continue

            text = turn["text"]

            # 判断事件类型
            event_type = self._classify_event(text)

            # 提取摘要（前 100 字符）
            summary = text[:200].replace("\n", " ").strip()
            if len(text) > 200:
                summary += "..."

            # 提取标签
            extracted_tags = self._extract_tags(text, session.tags)

            events.append({
                "title": f"[{session.project_name}] {summary[:80]}",
                "event_type": event_type,
                "full_text": text[:3000],  # 限制长度
                "project": session.project_name,
                "summary": summary,
                "tags": extracted_tags[:5],
                "participants": ["Cursor AI", "Peter"],
                "source": "cursor_transcript",
                "metadata": {
                    "session_id": session.session_id,
                    "d_project": session.d_project,
                    "turn_index": i,
                },
            })

        return events

    def _classify_event(self, text: str) -> str:
        """根据文本内容分类事件类型"""
        text_lower = text.lower()

        # 决策信号
        decision_keywords = ["为什么", "因为", "建议", "方案", "选择", "决定", "优先",
                             "why", "because", "recommend", "decision", "prefer"]
        # 操作信号
        action_keywords = ["执行", "写入", "修改", "创建", "删除", "部署", "安装",
                           "write", "edit", "create", "delete", "deploy", "install"]
        # 发现信号
        discovery_keywords = ["发现", "问题", "错误", "bug", "异常", "需要注意",
                              "found", "issue", "error", "problem", "warning"]
        # 配置信号
        config_keywords = ["配置", "env", "docker", "nginx", "端口", "环境变量",
                           "config", "setting", "port"]

        scores = {
            "决策": sum(1 for kw in decision_keywords if kw in text_lower),
            "操作": sum(1 for kw in action_keywords if kw in text_lower),
            "发现": sum(1 for kw in discovery_keywords if kw in text_lower),
            "配置": sum(1 for kw in config_keywords if kw in text_lower),
        }

        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return "对话"
        return best

    def _extract_tags(self, text: str, default_tags: list[str]) -> list[str]:
        """从文本中提取技术标签"""
        tech_keywords = {
            "python": "Python", "flask": "Flask", "django": "Django",
            "rust": "Rust", "go": "Go", "java": "Java",
            "spring": "Spring Boot", "spring ai": "Spring AI",
            "react": "React", "vue": "Vue", "next.js": "Next.js",
            "typescript": "TypeScript", "javascript": "JavaScript",
            "mysql": "MySQL", "postgresql": "PostgreSQL", "sqlite": "SQLite",
            "redis": "Redis", "mongodb": "MongoDB",
            "docker": "Docker", "kubernetes": "K8s",
            "chroma": "ChromaDB", "pgvector": "pgvector",
            "deepseek": "DeepSeek", "ollama": "Ollama",
            "consul": "Consul", "nginx": "Nginx",
            "微服务": "微服务", "api": "API", "rag": "RAG",
            "harmonyos": "HarmonyOS", "iot": "IoT",
            "微信小程序": "微信小程序", "miniprogram": "小程序",
        }

        text_lower = text.lower()
        found = []
        for kw, tag in tech_keywords.items():
            if kw in text_lower and tag not in found:
                found.append(tag)

        # 合并默认标签
        for tag in default_tags:
            if tag not in found:
                found.append(tag)

        return found[:8]
