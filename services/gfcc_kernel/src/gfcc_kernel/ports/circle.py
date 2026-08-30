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
    """围坐容器。内存为读缓存，变更同步写 circle_flow（G6）；无 flow 时纯内存。"""

    def __init__(self, flow: Optional[CircleFlowStore] = None) -> None:
        self._lock = threading.Lock()
        self._circles: Dict[str, Dict[str, Any]] = {}
        # 旁观在册（left_at IS NULL）：{circle_id: [{"sub","observed_at"}]}
        self._watchers: Dict[str, List[Dict[str, Any]]] = {}
        self._flow = flow
        if flow is not None:
            self._hydrate()

    def _hydrate(self) -> None:
        """启动恢复：从库读回圈与成员（含 dissolved 历史，dissolve 不删行）与旁观。"""
        for c in self._flow.list_circles():
            c["members"] = self._flow.list_members(c["id"])
            self._circles[c["id"]] = c
        self._watchers = self._flow.list_all_watchers()

    def _drop_watcher_locked(self, circle_id: str, sub: str) -> None:
        """内存侧摘掉某 sub 的旁观标记（join/决策⑤ 与 leave 幂等兜底）。"""
        lst = self._watchers.get(circle_id)
        if lst:
            self._watchers[circle_id] = [w for w in lst if w["sub"] != sub]

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
        if self._flow is not None:
            # G6：圈 + 首成员（organizer）同事务落库
            self._flow.create_circle(circle, circle["members"][0])
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
                self._drop_watcher_locked(circle_id, participant_sub)  # 防御：不应同时存在
                return PortOpResult(
                    ok=True,
                    id=circle_id,
                    data={"circle_id": circle_id, "members": circle["members"], "rejoined": True},
                )
            member = {
                "sub": participant_sub,
                "role": "participant",
                "builder_tags": builder_tags or [],
                "joined_at": _now(),
            }
            circle["members"].append(member)
            # 决策⑤：旁观后再入座 → 从旁观名单摘掉（不留幽灵旁观）
            self._drop_watcher_locked(circle_id, participant_sub)
        if self._flow is not None:
            self._flow.upsert_member(circle_id, member)
            self._flow.leave_watcher(circle_id, participant_sub)
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
            new_floor: Optional[str] = None
            if circle.get("floor_sub") == participant_sub:
                # §4.2 地板交接：当前持有者离场 → 交给剩余成员下一位
                circle["floor_sub"] = next_floor(circle["members"], participant_sub)
                new_floor = circle["floor_sub"]
        if self._flow is not None:
            # G6：删成员 + 地板交接同事务（不出现「成员已删、地板仍指离开者」半态）
            self._flow.remove_member_and_floor(circle_id, participant_sub, new_floor)
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "members": circle["members"]})

    def advance_floor(self, circle_id: str, current_sub: str, *, persist: bool = True) -> PortOpResult:
        """§4.3 达成一条后轮询交接：地板从 current_sub 交给下一位。

        仅当 current_sub 仍在座时按顺序轮换；调用方（circle_web.api_ack）
        先校验 floor_sub == 提议人 再调，避免「提议人已 leave、地板已在
        4.2 交接」时多跳一格。

        persist=False：只改内存，库写交给调用方的事务（G6 决策②，
        api_ack 用 verify_and_advance_floor 同事务写 verified + 地板）。
        """
        with self._lock:
            circle = self._circles.get(circle_id)
            if circle is None:
                return PortOpResult(ok=False, error=f"circle not found: {circle_id}")
            circle["floor_sub"] = next_floor(circle["members"], current_sub)
            floor_sub = circle["floor_sub"]
        if self._flow is not None and persist:
            self._flow.set_floor(circle_id, floor_sub)
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "floor_sub": floor_sub})

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
        if self._flow is not None:
            self._flow.update_circle_status(circle_id, "paused")
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "status": "paused"})

    def observe(self, circle_id: str, observer_sub: str) -> PortOpResult:
        """登记旁观（决策②⑧）：不入座、不进 parties；重复旁观幂等刷新时间。

        已入座再旁观 → 400（决策④：避免一人同时在两套名单）。
        """
        now = _now()
        with self._lock:
            circle = self._circles.get(circle_id)
            if circle is None:
                return PortOpResult(ok=False, error=f"circle not found: {circle_id}")
            if circle["status"] != "active":
                return PortOpResult(ok=False, error=f"circle not observable: status={circle['status']}")
            if any(m["sub"] == observer_sub for m in circle["members"]):
                return PortOpResult(ok=False, error="already seated; leave first then observe")
            lst = self._watchers.setdefault(circle_id, [])
            existed = False
            for w in lst:
                if w["sub"] == observer_sub:
                    w["observed_at"] = now  # 幂等：刷新登记时间
                    existed = True
                    break
            if not existed:
                lst.append({"sub": observer_sub, "observed_at": now})
        if self._flow is not None:
            self._flow.upsert_watcher(circle_id, observer_sub, now)
        return PortOpResult(
            ok=True,
            id=circle_id,
            data={"circle_id": circle_id, "watchers": list(self._watchers.get(circle_id, []))},
        )

    def unobserve(self, circle_id: str, observer_sub: str) -> PortOpResult:
        """离开旁观（决策⑥）：v1 保留历史（库写 left_at），当前在册名单移除。"""
        with self._lock:
            lst = self._watchers.get(circle_id)
            if not lst or not any(w["sub"] == observer_sub for w in lst):
                return PortOpResult(ok=False, error="not an observer")
            self._watchers[circle_id] = [w for w in lst if w["sub"] != observer_sub]
        if self._flow is not None:
            self._flow.leave_watcher(circle_id, observer_sub)
        return PortOpResult(
            ok=True,
            id=circle_id,
            data={"circle_id": circle_id, "watchers": list(self._watchers.get(circle_id, []))},
        )

    def list_watchers(self, circle_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(w) for w in self._watchers.get(circle_id, [])]

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
            dissolved_at = circle["dissolved_at"]
        if self._flow is not None:
            # G6：dissolve 不删行（历史保留），只写 status + dissolved_at
            self._flow.update_circle_status(circle_id, "dissolved", dissolved_at)
        return PortOpResult(ok=True, id=circle_id, data={"circle_id": circle_id, "status": "dissolved"})

    # ------------------------------------------------------------------ #
    # 查询辅助
    # ------------------------------------------------------------------ #

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(c) for c in self._circles.values()]
