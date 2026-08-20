"""identity 端口 —— 营造师画像（PPI）stub。

对齐 contracts/identity.v1.json：
- profile: sub / display_name / values / builder_tags / capability_trace / commitments / role。
- trace_sources 白名单：contribution|memory|consensus|circle → evidence；job_match|mbti|ai_observed → auxiliary；未列来源一律拒绝。
- 只能 system 通过 append_trace mint evidence；identity 不得自证能力（upsert_profile 不能加 evidence trace）。
- operations: get_profile / upsert_profile / append_trace。
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


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class IdentityAdapter:
    """营造师画像 stub。内存实现，空数据合法。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._profiles: Dict[str, Dict[str, Any]] = {}

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
            profile["capability_trace"].append(
                {
                    "label": label,
                    "source_port": source_port,
                    "weight": weight,
                    "observed_at": observed_at or _now(),
                    "superseded_at": None,
                }
            )
        return PortOpResult(ok=True, id=sub, data={"profile": dict(profile)})

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
