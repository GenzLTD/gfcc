"""circle 端口 —— 围坐容器 stub。

对齐 contracts/circle.v1.json：
- 状态机：forming → active → (paused|dissolved)；dissolve 不删历史（Dual 记录保留）。
- 成员显式（sub + role + builder_tags + joined_at）；AI 不是投票成员。
- operations: create / join / leave / get / pause / dissolve。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import uuid

from ..envelope import PortOpResult


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def next_floor(members: List[Dict[str, Any]], current_sub: str) -> Optional[str]:
    """发言权下一位（施工单 §4.4）：按 members 入座顺序循环。

    - members 为空 → None（无人可持地板）
    - current_sub 仍在 members → members[(i + 1) % n]（两人圈 A→B→A）
    - current_sub 已不在（已 leave）→ members[0]（离开者不算当前位，
      从队首续轮；leave 触发 4.2 交接时即走到这里）
    """
    subs = [m["sub"] for m in members]
    n = len(subs)
    if n == 0:
        return None
    if current_sub in subs:
        i = subs.index(current_sub)
        return subs[(i + 1) % n]
    return subs[0]


class CircleAdapter:
    """围坐容器 stub。内存实现，空数据合法。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._circles: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # operations
    # ------------------------------------------------------------------ #

    def create(self, proposer_sub: str, name: str, parent_id: Optional[str] = None) -> PortOpResult:
        cid = str(uuid.uuid4())
        with self._lock:
            circle = {
                "id": cid,
                "name": name,
                "parent_id": parent_id,
                "members": [
                    {
                        "sub": proposer_sub,
                        "role": "organizer",
                        "builder_tags": [],
                        "joined_at": _now(),
                    }
                ],
                "status": "active",
                "created_by": proposer_sub,
                "created_at": _now(),
                "dissolved_at": None,
                "floor_sub": proposer_sub,  # 建圈者先持地板（§4.1）
            }
            self._circles[cid] = circle
        return PortOpResult(ok=True, id=cid, data={"circle_id": cid, "circle": circle})

    def join(self, circle_id: str, participant_sub: str, builder_tags: Optional[List[str]] = None) -> PortOpResult:
        with self._lock:
            circle = self._circles.get(circle_id)
            if circle is None:
                return PortOpResult(ok=False, error=f"circle not found: {circle_id}")
            if circle["status"] != "active":
                return PortOpResult(ok=False, error=f"circle not joinable: status={circle['status']}")
            if any(m["sub"] == participant_sub for m in circle["members"]):
                # 幂等：已入座则视为重新入座成功（配合 leave 释放席位后重进，
                # 也避免「退出未清后端」导致永远进不去）
                return PortOpResult(
                    ok=True,
                    id=circle_id,
                    data={"circle_id": circle_id, "members": circle["members"], "rejoined": True},
                )
            circle["members"].append(
                {
                    "sub": participant_sub,
                    "role": "participant",
                    "builder_tags": builder_tags or [],
                    "joined_at": _now(),
                }
            )
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "members": circle["members"]})

    def leave(self, circle_id: str, participant_sub: str) -> PortOpResult:
        with self._lock:
            circle = self._circles.get(circle_id)
            if circle is None:
                return PortOpResult(ok=False, error=f"circle not found: {circle_id}")
            before = len(circle["members"])
            circle["members"] = [m for m in circle["members"] if m["sub"] != participant_sub]
            if len(circle["members"]) == before:
                return PortOpResult(ok=False, error="not a member")
            if circle.get("floor_sub") == participant_sub:
                # §4.2 地板交接：当前持有者离场 → 交给剩余成员下一位
                circle["floor_sub"] = next_floor(circle["members"], participant_sub)
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "members": circle["members"]})

    def advance_floor(self, circle_id: str, current_sub: str) -> PortOpResult:
        """§4.3 达成一条后轮询交接：地板从 current_sub 交给下一位。

        仅当 current_sub 仍在座时按顺序轮换；调用方（circle_web.api_ack）
        先校验 floor_sub == 提议人 再调，避免「提议人已 leave、地板已在
        4.2 交接」时多跳一格。
        """
        with self._lock:
            circle = self._circles.get(circle_id)
            if circle is None:
                return PortOpResult(ok=False, error=f"circle not found: {circle_id}")
            circle["floor_sub"] = next_floor(circle["members"], current_sub)
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "floor_sub": circle["floor_sub"]})

    def get(self, circle_id: str) -> PortOpResult:
        with self._lock:
            circle = self._circles.get(circle_id)
            if circle is None:
                return PortOpResult(ok=False, error=f"circle not found: {circle_id}")
            return PortOpResult(ok=True, id=circle_id, data={"circle": dict(circle)})

    def pause(self, circle_id: str, organizer_sub: str) -> PortOpResult:
        with self._lock:
            circle = self._circles.get(circle_id)
            if circle is None:
                return PortOpResult(ok=False, error=f"circle not found: {circle_id}")
            if circle["status"] not in ("active", "forming"):
                return PortOpResult(ok=False, error=f"circle not pausable: status={circle['status']}")
            if organizer_sub != circle["created_by"]:
                return PortOpResult(ok=False, error="only creator/organizer may pause")
            circle["status"] = "paused"
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "status": "paused"})

    def dissolve(self, circle_id: str, organizer_sub: str) -> PortOpResult:
        """解散：状态置 dissolved；历史（Dual 记录）不删。"""
        with self._lock:
            circle = self._circles.get(circle_id)
            if circle is None:
                return PortOpResult(ok=False, error=f"circle not found: {circle_id}")
            if organizer_sub != circle["created_by"]:
                return PortOpResult(ok=False, error="only creator/organizer may dissolve")
            circle["status"] = "dissolved"
            circle["dissolved_at"] = _now()
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "status": "dissolved"})

    # ------------------------------------------------------------------ #
    # 查询辅助
    # ------------------------------------------------------------------ #

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(c) for c in self._circles.values()]
