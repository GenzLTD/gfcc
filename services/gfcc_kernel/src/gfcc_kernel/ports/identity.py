"""identity 端口 —— 营造师画像（PPI）stub。

对齐 contracts/identity.v1.json：
- profile: sub / display_name / values / builder_tags / capability_trace / commitments / role。
- trace_sources 白名单：contribution|memory|consensus|circle → evidence；job_match|mbti|ai_observed → auxiliary；未列来源一律拒绝。
- 只能 system 通过 append_trace mint evidence；identity 不得自证能力（upsert_profile 不能加 evidence trace）。
- operations: get_profile / upsert_profile / append_trace / apply_value_axis。
- value_axes 只由 value_axis_choice 累加；职位分不得写入。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import uuid

from ..envelope import PortOpResult

EVIDENCE_SOURCES = {"contribution", "memory", "consensus", "circle"}
AUXILIARY_SOURCES = {"job_match", "mbti", "ai_observed"}
TRACE_SOURCE_WHITELIST = EVIDENCE_SOURCES | AUXILIARY_SOURCES

COMMITMENT_STATUS = {"offered", "accepted", "fulfilled", "withdrawn"}

# contracts/signals/value_axis_choice.v1.json 的字段白名单。未列出的字段一律拒绝。
VALUE_AXIS_FIELDS = {
    "axis",
    "points",
    "domain",
    "imprint_name",
    "source",
    "generated_at",
}

# contracts/roles.v1.json role_enum —— 八角梯，index 越大级别越高
ROLE_ENUM = [
    "observer",
    "participant",
    "experimenter",
    "proposer",
    "steward",
    "organizer",
    "actor",
    "petitioner",
]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class IdentityAdapter:
    """营造师画像 stub。内存实现，空数据合法。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._profiles: Dict[str, Dict[str, Any]] = {}
        self._signal_beacons: List[Dict[str, Any]] = []
        self._value_axis_choices: List[Dict[str, Any]] = []

    def _ensure(self, sub: str) -> Dict[str, Any]:
        if sub not in self._profiles:
            self._profiles[sub] = {
                "sub": sub,
                "display_name": None,
                "values": [],
                "builder_tags": [],
                "capability_trace": [],
                "commitments": [],
                "role": "observer",
                "role_evidence_ids": [],
            }
        return self._profiles[sub]

    # ------------------------------------------------------------------ #
    # operations
    # ------------------------------------------------------------------ #

    def get_profile(self, sub: str) -> PortOpResult:
        with self._lock:
            profile = self._profiles.get(sub)
            if profile is None:
                # 空数据合法：返回空画像而非错误
                return PortOpResult(ok=True, id=sub, data={"profile": self._empty_profile(sub)})
            return PortOpResult(ok=True, id=sub, data={"profile": dict(profile)})

    def upsert_profile(self, sub: str, values: Optional[List[str]] = None,
                       builder_tags: Optional[List[str]] = None,
                       display_name: Optional[str] = None,
                       commitments: Optional[List[Dict[str, Any]]] = None) -> PortOpResult:
        """更新基础画像字段。不能通过本操作写入 capability_trace（防自证）。"""
        with self._lock:
            profile = self._ensure(sub)
            if display_name is not None:
                profile["display_name"] = display_name
            if values is not None:
                profile["values"] = list(values)
            if builder_tags is not None:
                profile["builder_tags"] = list(builder_tags)
            if commitments is not None:
                now = _now()
                for cm in commitments:
                    status = cm.get("status", "offered")
                    if status not in COMMITMENT_STATUS:
                        return PortOpResult(ok=False, error=f"invalid commitment status: {status}")
                    if "id" not in cm:
                        cm["id"] = str(uuid.uuid4())
                    if "offered_at" not in cm:
                        cm["offered_at"] = now
                profile["commitments"] = list(commitments)
        return PortOpResult(ok=True, id=sub, data={"profile": dict(profile)})

    def append_trace(self, sub: str, label: str, source_port: str,
                     weight: str = "auxiliary", observed_at: Optional[str] = None) -> PortOpResult:
        """system 专用：mint 能力轨迹。来源必须在白名单；evidence 仅限 EVIDENCE_SOURCES。"""
        if source_port not in TRACE_SOURCE_WHITELIST:
            return PortOpResult(ok=False, error=f"trace source not whitelisted: {source_port}")
        if weight == "evidence" and source_port not in EVIDENCE_SOURCES:
            return PortOpResult(ok=False, error=f"source {source_port} cannot mint evidence weight")
        with self._lock:
            profile = self._ensure(sub)
            trace_id = str(uuid.uuid4())
            profile["capability_trace"].append(
                {
                    "id": trace_id,
                    "label": label,
                    "source_port": source_port,
                    "weight": weight,
                    "observed_at": observed_at or _now(),
                    "superseded_at": None,
                }
            )
        return PortOpResult(ok=True, id=trace_id, data={"profile": dict(profile)})

    def promote_role(self, sub: str, new_role: str, evidence_ids: List[str],
                     changed_by: str, note: Optional[str] = None) -> PortOpResult:
        """带证据的角色升级（G6 兑现入口 + 升级路径）。

        对齐 contracts/roles.v1.json transitions：
        - driven_by: memory records / contribution fulfillments / consensus_verified /
          ai_observed（辅助证据，单独不足以上升）。
        - not_driven_by_long_term: admin toggle only —— 升级必须有证据，禁止只拨 admin。
        - ops_exception: admin/system may set roles for repair; must audit as admin.role.set。

        new_role 必须在八角梯（ROLE_ENUM）内；evidence_ids 必须非空且引用真实记录。
        """
        if new_role not in ROLE_ENUM:
            return PortOpResult(ok=False, error=f"invalid role: {new_role}")
        if not evidence_ids:
            return PortOpResult(ok=False, error="promotion requires evidence_ids (no admin toggle)")
        with self._lock:
            profile = self._ensure(sub)
            old_role = profile.get("role", "observer")
            if new_role == old_role:
                return PortOpResult(ok=False, error=f"already role {new_role}")
            profile["role"] = new_role
            profile["role_evidence_ids"] = list(dict.fromkeys(profile.get("role_evidence_ids", []) + evidence_ids))
            profile["role_changed_at"] = _now()
            profile["role_changed_by"] = changed_by
            if note:
                profile["role_change_note"] = note
        return PortOpResult(ok=True, id=sub, data={"profile": dict(profile), "old_role": old_role})

    # ------------------------------------------------------------------ #
    # 信号摄入（Step3 W3）：personality_beacon → 画像 auxiliary trace
    # ------------------------------------------------------------------ #

    def ingest_signal(
        self,
        signal_id: str,
        user_id_hash: str,
        payload: Dict[str, Any],
        signal_type: Optional[str] = None,
    ) -> PortOpResult:
        """接收发往 identity 的信号。

        personality_beacon：mint MBTI auxiliary trace。
        value_axis_choice：只累加 value_axes，不写 capability_trace，也不改 values。
        轴取 payload.axis，不按域名默认轴改写。
        """
        if signal_type == "value_axis_choice":
            return self._ingest_value_axis(signal_id, user_id_hash, payload)
        ptype = (payload.get("personality_type") or "").upper()
        trace = self.append_trace(
            sub=user_id_hash,
            label=f"personality_beacon:{ptype}",
            source_port="mbti",
            weight="auxiliary",
        )
        with self._lock:
            beacon = {
                "signal_id": signal_id,
                "user_id_hash": user_id_hash,
                "payload": dict(payload),
                "trace_id": trace.id,
                "received_at": _now(),
            }
            self._signal_beacons.append(beacon)
        return PortOpResult(ok=True, id=signal_id, data={"beacon": dict(beacon)})

    def list_signal_beacons(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(b) for b in self._signal_beacons]

    def read_value_axes(self, sub: str) -> Optional[Dict[str, int]]:
        """返回原值快照。没有选择过则是 None。不创建画像，也不改累加值。"""
        with self._lock:
            profile = self._profiles.get(sub)
            axes = profile.get("value_axes") if profile else None
            if not isinstance(axes, dict):
                return None
            return {key: int(axes.get(key, 0)) for key in ("survival", "freedom", "belonging")}

    def _ingest_value_axis(self, signal_id: str, user_id_hash: str, payload: Dict[str, Any]) -> PortOpResult:
        """把人选的 1–5 点加到指定轴。只接受契约列出的字段。"""
        extra = set(payload) - VALUE_AXIS_FIELDS
        if extra:
            return PortOpResult(
                ok=False,
                error=f"value_axis_choice payload has unlisted fields: {sorted(extra)}",
            )
        axis = payload.get("axis")
        points = payload.get("points")
        if axis not in ("survival", "freedom", "belonging"):
            return PortOpResult(ok=False, error="axis must be survival, freedom, or belonging")
        if isinstance(points, bool) or not isinstance(points, int) or not 1 <= points <= 5:
            return PortOpResult(ok=False, error="points must be an integer within 1..5")
        if payload.get("source") != "planetx":
            return PortOpResult(ok=False, error="source must be planetx")
        with self._lock:
            profile = self._ensure(user_id_hash)
            axes = profile.get("value_axes")
            if not isinstance(axes, dict):
                axes = {"survival": 0, "freedom": 0, "belonging": 0}
                profile["value_axes"] = axes
            axes[axis] = int(axes.get(axis, 0)) + points
            receipt = {
                "signal_id": signal_id,
                "user_id_hash": user_id_hash,
                "axis": axis,
                "points": points,
                "domain": payload.get("domain"),
                "imprint_name": payload.get("imprint_name"),
                "received_at": _now(),
            }
            self._value_axis_choices.append(receipt)
            snapshot = dict(axes)
        return PortOpResult(ok=True, id=signal_id, data={"value_axes": snapshot})

    def list_value_axis_choices(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(c) for c in self._value_axis_choices]

    # ------------------------------------------------------------------ #
    # 查询辅助
    # ------------------------------------------------------------------ #

    def _empty_profile(self, sub: str) -> Dict[str, Any]:
        return {
            "sub": sub,
            "display_name": None,
            "values": [],
            "builder_tags": [],
            "capability_trace": [],
            "commitments": [],
            "role": "observer",
            "role_evidence_ids": [],
        }
