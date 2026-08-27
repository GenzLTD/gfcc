"""memory 端口 —— Dual 七库 stub。

对齐 contracts/memory.v1.json：
- 七库：issue/action/event/methodology_value/person/org/resource；method 是 methodology_value 的弃用别名。
- record: library/body/observed_at 必填；observed_by ∈ {human, ai}；ai 必填 ai_source。
- operations: remember / recall / observe / supersede。
- 不变量：AI 不得静默改写（observe 不改 body）；重写走人类 steward 的 supersede（旧记录保留 superseded_at）。
- store 槽可替换（stub → sqlite/mem0/zep/agentmemory_iii）。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import uuid

from ..envelope import PortOpResult
from ..slots import StubStore

LIBRARIES = {"issue", "action", "event", "methodology_value", "person", "org", "resource"}
DEPRECATED_ALIASES = {"method": "methodology_value"}
RECORD_TYPES = {"note", "method", "value"}


def _normalize_library(library: str) -> Optional[str]:
    lib = DEPRECATED_ALIASES.get(library, library)
    return lib if lib in LIBRARIES else None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class MemoryAdapter:
    """Dual 七库 stub。store 槽默认 stub（内存）。"""

    def __init__(self, store: Optional[StubStore] = None) -> None:
        self._lock = threading.Lock()
        self._store = store or StubStore()

    # ------------------------------------------------------------------ #
    # operations
    # ------------------------------------------------------------------ #

    def remember(self, library: str, body: str, observed_by: str = "human",
                 actor_sub: str = "", circle_id: Optional[str] = None,
                 refs: Optional[List[str]] = None,
                 record_type: Optional[str] = None,
                 ai_source: Optional[str] = None) -> PortOpResult:
        lib = _normalize_library(library)
        if lib is None:
            return PortOpResult(ok=False, error=f"unknown library: {library}")
        if not body or not body.strip():
            return PortOpResult(ok=False, error="body is required")
        if observed_by not in ("human", "ai"):
            return PortOpResult(ok=False, error=f"invalid observed_by: {observed_by}")
        if observed_by == "ai" and not ai_source:
            return PortOpResult(ok=False, error="ai observe requires ai_source")
        if record_type is not None and record_type not in RECORD_TYPES:
            return PortOpResult(ok=False, error=f"invalid record_type: {record_type}")

        record = {
            "library": lib,
            "body": body.strip(),
            "observed_at": _now(),
            "observed_by": observed_by,
            "actor_sub": actor_sub,
            "refs": refs or [],
            "superseded_at": None,
        }
        if circle_id:
            record["circle_id"] = circle_id
        if record_type:
            record["record_type"] = record_type
        if ai_source:
            record["ai_source"] = ai_source
        saved = self._store.put(record)
        return PortOpResult(ok=True, id=saved["id"], data={"record": saved})

    def recall(self, library: Optional[str] = None, keyword: Optional[str] = None,
               limit: int = 20, *, actor_sub: Optional[str] = None,
               circle_id: Optional[str] = None) -> PortOpResult:
        """召回：按库过滤 + 关键词模糊匹配 body。只返回未 superseded 的记录。

        可见性：无 circle_id 时必须 actor_sub（对齐「每人一个 sub」私有域）。
        """
        if actor_sub is None and circle_id is None:
            return PortOpResult(ok=False, error="recall requires actor_sub (private) or circle_id (circle)")

        def _match(rec: Dict[str, Any]) -> bool:
            if rec.get("superseded_at"):
                return False
            if library is not None:
                lib = _normalize_library(library)
                if lib is None or rec.get("library") != lib:
                    return False
            if keyword:
                return keyword.lower() in rec.get("body", "").lower() or keyword in " ".join(rec.get("refs", []))
            return True

        items = self._store.query(_match, limit=limit, actor_sub=actor_sub, circle_id=circle_id)
        return PortOpResult(ok=True, data={"records": items, "count": len(items)})

    def observe(self, record_id: str, actor_sub: str = "", observed_by: str = "human",
                ai_source: Optional[str] = None) -> PortOpResult:
        """标记 seen/used，不改 body。AI observe 需要 ai_source。

        可见性：观察者必须能读到记录（actor_sub 与记录 owner 一致，私有域内）。
        """
        if not actor_sub:
            return PortOpResult(ok=False, error="observe requires actor_sub (private)")
        rec = self._store.get(record_id, actor_sub=actor_sub)
        if rec is None:
            return PortOpResult(ok=False, error=f"record not found: {record_id}")
        if observed_by not in ("human", "ai"):
            return PortOpResult(ok=False, error=f"invalid observed_by: {observed_by}")
        if observed_by == "ai" and not ai_source:
            return PortOpResult(ok=False, error="ai observe requires ai_source")
        rec.setdefault("observations", []).append(
            {"by": actor_sub, "observed_by": observed_by, "ai_source": ai_source, "at": _now()}
        )
        self._store.put(rec)  # 更新观察记录（不触碰 body）
        return PortOpResult(ok=True, id=record_id, data={"record": rec})

    def supersede(self, record_id: str, new_body: str, actor_sub: str) -> PortOpResult:
        """人类 steward 重写：旧记录保留 superseded_at（历史不覆盖）。

        可见性：只有记录 owner 能重写（actor_sub 与记录 owner 一致）。
        """
        if not actor_sub:
            return PortOpResult(ok=False, error="supersede requires actor_sub (private)")
        rec = self._store.get(record_id, actor_sub=actor_sub)
        if rec is None:
            return PortOpResult(ok=False, error=f"record not found: {record_id}")
        if not new_body or not new_body.strip():
            return PortOpResult(ok=False, error="new body is required")
        new_rec = self._store.supersede(
            record_id,
            {"body": new_body.strip()},
            actor_sub=actor_sub,
            observed_by="human",
        )
        return PortOpResult(ok=True, id=new_rec["id"], data={"new_record": new_rec, "superseded": record_id})

    # ------------------------------------------------------------------ #
    # 查询辅助
    # ------------------------------------------------------------------ #

    def count(self) -> int:
        return self._store.count()

    def list_all(self) -> List[Dict[str, Any]]:
        """管理面：列出全部活跃记录（绕过可见性，仅供调试/运维）。"""
        return self._store.list_active(limit=500)
