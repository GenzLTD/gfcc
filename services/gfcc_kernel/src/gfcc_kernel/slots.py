"""五槽抽象与默认 stub 实现。

对齐 contracts/ask.envelope.v1.json 的 slots: [llm, tools, session, policy, store]。
- llm:     providers/default —— 默认 stub（不接厂商）；LLM_PROVIDER=ollama 时切换 OllamaLLM。
- tools:   registry —— 端口适配器集合（五端口）。
- session: community —— 按 session_id 的轻量上下文。
- policy:  ethos —— 接入 ethos 纯验证者（验签/鉴权/配额/审计）。
- store:   stub —— put/get/query/supersede，内存实现（重启即空，对齐"空数据合法"）。
           STORE_PROVIDER=sqlite 时切换 SQLiteStore（重启不丢）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional


# --------------------------------------------------------------------------- #
# llm 槽
# --------------------------------------------------------------------------- #

class LLMProvider:
    """llm 槽接口。默认 stub：直接返回解析所需提示，不做外部调用。"""

    def __init__(self, model: str = "providers/default", endpoint: Optional[str] = None):
        self.model = model
        self.endpoint = endpoint

    def is_available(self) -> bool:
        return False

    def complete(self, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
        """stub 实现：返回一个表明未接入模型的占位响应。"""
        return {
            "role": "assistant",
            "content": "[stub:llm] no model configured; dispatch used rule-based parser.",
            "model": self.model,
        }


class OllamaLLM(LLMProvider):
    """Ollama 本地模型适配器。

    对齐 docs/Phase2_Step1-2_实施建议.md Step 1：
    - POST {base}/api/chat，`format=json` 强制合法 JSON，`stream=false`。
    - `is_available()` 探测 /api/tags（带 5s TTL 缓存，避免每次请求都打网络）。
    - `complete(messages)` 内部注入意图分类 system prompt，返回 {port, confidence, reason}。
    """

    # 意图分类系统提示（Ollama 只负责分类，不产合同执行）
    INTENT_SYSTEM_PROMPT = (
        "你是格契内核的意图分类器，根据用户消息判断属于哪个端口。\n"
        "端口定义：\n"
        "- circle 围坐：安排/确认围坐会议，下次围坐时间、参加人。\n"
        "- identity 身份画像：询问/设置角色、边界、权限，我是谁、我能做什么。\n"
        "- memory 记忆：记录/保存/查询/回忆信息、待办、材料清单、备忘。\n"
        "- consensus 共议：表决、投票、达成一致、异议、反对、共识确认。普通询问或讨论不是 consensus。\n"
        "- contribution 贡献：归档产出、提交成果、工作总结、贡献记录。注意「归档产出/记录贡献」归 contribution，不归 memory。\n"
        "- unknown：问候、闲聊、纯情绪或无法判断。\n"
        "判定规则：\n"
        "1. 优先匹配最具体的动作语义。\n"
        "2. 无表决/决策/一致化动作的对话不是 consensus。\n"
        "3. 「记录信息」归 memory，「归档产出/贡献」归 contribution。\n"
        "4. 问候与闲聊必须输出 unknown。\n"
        "只输出JSON：{\"port\": \"circle|identity|memory|consensus|contribution|unknown\", "
        "\"confidence\": 0.0-1.0, \"reason\": \"一句话理由\"}。\n"
    )

    def __init__(self, model: str = "qwen2.5:7b", endpoint: str = "http://localhost:11434",
                 timeout: float = 30.0):
        super().__init__(model=model, endpoint=endpoint)
        self._base = endpoint.rstrip("/")
        self._timeout = timeout
        self._available: Optional[bool] = None
        self._checked_at: float = 0.0
        self._ttl = 5.0

    # ------------------------------------------------------------------ #
    # 探测
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        now = time.monotonic()
        if self._available is not None and (now - self._checked_at) < self._ttl:
            return self._available
        ok = self._probe()
        self._available = ok
        self._checked_at = now
        return ok

    def _probe(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"{self._base}/api/tags", timeout=1.5
            ) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------ #
    # 完成调用
    # ------------------------------------------------------------------ #

    def complete(self, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
        """调用 Ollama chat。messages 为用户消息序列；system 提示内部注入。

        返回结构化 dict：{port, confidence, reason}。调用失败抛异常，
        由 dispatcher 捕获后 fallback 到关键词规则。
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.INTENT_SYSTEM_PROMPT},
                *messages,
            ],
            "format": "json",
            "stream": False,
            # 意图分类要求确定性：固定 temperature=0 + seed，避免小模型随机漂移
            "temperature": 0.0,
            "seed": 42,
        }
        req = urllib.request.Request(
            f"{self._base}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        content = (raw.get("message") or {}).get("content", "{}")
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("ollama intent result is not an object")
        parsed.setdefault("port", "unknown")
        parsed.setdefault("confidence", 0.0)
        parsed.setdefault("reason", "")
        return parsed


def build_llm() -> LLMProvider:
    """按 LLM_PROVIDER 装配 llm 槽。留空/不配 = stub（is_available() 为 False）。"""
    provider = os.getenv("LLM_PROVIDER", "stub").strip().lower()
    if provider == "ollama":
        return OllamaLLM(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b").strip() or "qwen2.5:7b",
            endpoint=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
            or "http://localhost:11434",
        )
    return LLMProvider(
        model=os.getenv("LLM_MODEL", "providers/default"),
        endpoint=os.getenv("LLM_ENDPOINT") or None,
    )


# --------------------------------------------------------------------------- #
# session 槽
# --------------------------------------------------------------------------- #

class SessionStore:
    """session 槽。community：按 session_id 保存轻量上下文。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def get(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._sessions.get(session_id, {}))

    def put(self, session_id: str, key: str, value: Any) -> None:
        with self._lock:
            self._sessions.setdefault(session_id, {})[key] = value

    def append(self, session_id: str, key: str, value: Any, maxlen: int = 20) -> None:
        with self._lock:
            bucket = self._sessions.setdefault(session_id, {}).setdefault(key, [])
            bucket.append(value)
            if len(bucket) > maxlen:
                del bucket[: len(bucket) - maxlen]


# --------------------------------------------------------------------------- #
# store 槽（stub）
# --------------------------------------------------------------------------- #

class StubStore:
    """store 槽默认实现。put/get/query/supersede，内存存储。

    对齐 memory.v1.json 的 store_slot 接口：put / get / query / supersede。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, Dict[str, Any]] = {}

    def put(self, record: Dict[str, Any]) -> Dict[str, Any]:
        rid = record.get("id") or str(uuid.uuid4())
        record["id"] = rid
        with self._lock:
            self._records[rid] = record
        return record

    def get(self, rid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._records.get(rid)
            return dict(rec) if rec else None

    def query(self, filter_fn: Optional[Callable[[Dict[str, Any]], bool]] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._records.values())
        if filter_fn:
            items = [dict(r) for r in items if filter_fn(r)]
        return items[:limit]

    def supersede(self, rid: str, new_body: Dict[str, Any], actor_sub: str, observed_by: str = "human") -> Optional[Dict[str, Any]]:
        """旧记录保留 superseded_at；AI 不可静默改写（observed_by=ai 需显式观察而非改写）。"""
        with self._lock:
            old = self._records.get(rid)
            if old is None:
                return None
            old["superseded_at"] = _now()
            old["superseded_by"] = actor_sub
            new_record = dict(old)
            new_record.pop("superseded_at", None)
            new_record.pop("superseded_by", None)
            new_record["id"] = str(uuid.uuid4())
            new_record.update({k: v for k, v in new_body.items() if k not in ("id", "superseded_at")})
            self._records[new_record["id"]] = new_record
            return new_record

    def count(self) -> int:
        with self._lock:
            return len(self._records)


# --------------------------------------------------------------------------- #
# store 槽（sqlite）
# --------------------------------------------------------------------------- #

class SQLiteStore:
    """store 槽持久化实现（重启不丢）。对齐 memory.v1.json store_slot 接口。

    一张表 + library 列区分七库；body 列存完整 record 的 JSON 字符串，
    因此 put/get 对任意嵌套结构（refs/observations 等）与 StubStore 完全兼容。
    query 默认只返回未 superseded 的活跃记录。
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS memory_records (
        id          TEXT PRIMARY KEY,
        library     TEXT NOT NULL,
        body        TEXT NOT NULL,
        actor_sub   TEXT,
        circle_id   TEXT,
        created_at  TEXT NOT NULL,
        superseded_at TEXT,
        superseded_by TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_library ON memory_records(library);
    CREATE INDEX IF NOT EXISTS idx_circle ON memory_records(circle_id);
    CREATE INDEX IF NOT EXISTS idx_active ON memory_records(superseded_at)
        WHERE superseded_at IS NULL;
    """

    def __init__(self, db_path: str = "data/memory.db") -> None:
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # 接口
    # ------------------------------------------------------------------ #

    def put(self, record: Dict[str, Any]) -> Dict[str, Any]:
        rid = record.get("id") or str(uuid.uuid4())
        rec = dict(record)
        rec["id"] = rid
        row = (
            rid,
            rec.get("library", ""),
            json.dumps(rec, ensure_ascii=False),
            rec.get("actor_sub"),
            rec.get("circle_id"),
            rec.get("observed_at") or _now(),
            rec.get("superseded_at"),
            rec.get("superseded_by"),
        )
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO memory_records "
                "(id, library, body, actor_sub, circle_id, created_at, superseded_at, superseded_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            self._conn.commit()
        return rec

    def get(self, rid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT body FROM memory_records WHERE id = ?", (rid,)
            )
            row = cur.fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def query(self, filter_fn: Optional[Callable[[Dict[str, Any]], bool]] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT body FROM memory_records WHERE superseded_at IS NULL"
            ).fetchall()
        items = [json.loads(r[0]) for r in rows]
        if filter_fn:
            items = [r for r in items if filter_fn(r)]
        return items[:limit]

    def supersede(self, rid: str, new_body: Dict[str, Any], actor_sub: str, observed_by: str = "human") -> Optional[Dict[str, Any]]:
        """事务内：旧记录标记 superseded_at/by，INSERT 新记录。

        契约红线：observed_by=ai 不得静默改写（AI 只能 observe，不能改 body）。
        """
        if observed_by == "ai":
            raise ValueError("ai must not silently supersede; use observe instead")
        with self._lock:
            cur = self._conn.execute(
                "SELECT body FROM memory_records WHERE id = ?", (rid,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            old = json.loads(row[0])
            old["superseded_at"] = now = _now()
            old["superseded_by"] = actor_sub
            new_record = dict(old)
            new_record.pop("superseded_at", None)
            new_record.pop("superseded_by", None)
            new_record["id"] = str(uuid.uuid4())
            new_record.update(
                {k: v for k, v in new_body.items() if k not in ("id", "superseded_at")}
            )
            with self._conn:  # 事务：自动提交 / 回滚
                self._conn.execute(
                    "UPDATE memory_records SET superseded_at=?, superseded_by=?, body=? WHERE id=?",
                    (now, actor_sub, json.dumps(old, ensure_ascii=False), rid),
                )
                self._conn.execute(
                    "INSERT INTO memory_records "
                    "(id, library, body, actor_sub, circle_id, created_at, superseded_at, superseded_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_record["id"],
                        new_record.get("library", ""),
                        json.dumps(new_record, ensure_ascii=False),
                        new_record.get("actor_sub"),
                        new_record.get("circle_id"),
                        new_record.get("observed_at") or now,
                        new_record.get("superseded_at"),
                        new_record.get("superseded_by"),
                    ),
                )
        return new_record

    def count(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM memory_records WHERE superseded_at IS NULL"
            )
            return int(cur.fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def build_store() -> Any:
    """按 STORE_PROVIDER 装配 store 槽。留空/不配 = stub（内存）。"""
    provider = os.getenv("STORE_PROVIDER", "stub").strip().lower()
    if provider == "sqlite":
        return SQLiteStore(db_path=os.getenv("STORE_DB_PATH", "data/memory.db").strip() or "data/memory.db")
    return StubStore()


def _now() -> str:
    # 本地时间 ISO8601，无毫秒时区后缀（契约只要求 date-time 字符串）
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
