"""五槽抽象与默认 stub 实现。

对齐 contracts/ask.envelope.v1.json 的 slots: [llm, tools, session, policy, store]。
- llm:     providers/default —— 默认 stub（不接厂商），可后续替换为 Ollama/OpenAI 适配器。
- tools:   registry —— 端口适配器集合（五端口）。
- session: community —— 按 session_id 的轻量上下文。
- policy:  ethos —— 接入 ethos 纯验证者（验签/鉴权/配额/审计）。
- store:   stub —— put/get/query/supersede，内存实现（重启即空，对齐"空数据合法"）。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

import uuid


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


def _now() -> str:
    # 本地时间 ISO8601，无毫秒时区后缀（契约只要求 date-time 字符串）
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
