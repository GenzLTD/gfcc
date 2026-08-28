"""consensus 端口 —— 共议 stub。

对齐 contracts/consensus.v1.json：
- 状态机：proposed → scored → below_threshold | consensus_passed → awaiting_ack → consensus_verified | expired | failed。
- 分数无证据无效（score_evidence 空则不能离开 proposed）。
- score < threshold → below_threshold；score >= threshold → consensus_passed 然后 awaiting_ack。
- 全部人类 party ack → consensus_verified，此时 can_complete 才为 true。
- AI 证据是辅助；AI 不能代替 party ack。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import uuid

from ..envelope import PortOpResult

DEFAULT_THRESHOLD = 85

VALID_STATUSES = {
    "proposed", "scored", "below_threshold", "consensus_passed",
    "awaiting_ack", "consensus_verified", "expired", "failed",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class ConsensusAdapter:
    """共议。内存为读缓存，变更同步写 circle_flow（G6）；无 flow 时纯内存。"""

    def __init__(self, threshold: int = DEFAULT_THRESHOLD, flow: Optional[CircleFlowStore] = None) -> None:
        self._lock = threading.Lock()
        self._threshold = max(0, min(100, threshold))
        self._proposals: Dict[str, Dict[str, Any]] = {}
        self._signal_evidence: List[Dict[str, Any]] = []
        self._flow = flow
        if flow is not None:
            self._hydrate()

    def _hydrate(self) -> None:
        """启动恢复：从库读回提案。verified_at 落库但内存不暴露该键（形状与今天一致）。"""
        for p in self._flow.list_proposals():
            p["acks"] = self._flow.list_acks(p["id"])
            p.pop("verified_at", None)
            self._proposals[p["id"]] = p

    # ------------------------------------------------------------------ #
    # operations
    # ------------------------------------------------------------------ #

    def propose(self, circle_id: str, subject: str, parties: List[str],
                proposer_sub: str, issue_id: Optional[str] = None) -> PortOpResult:
        if not subject or not subject.strip():
            return PortOpResult(ok=False, error="subject is required")
        if len(parties) < 2:
            return PortOpResult(ok=False, error="parties must have at least 2 human members")
        pid = str(uuid.uuid4())
        with self._lock:
            self._proposals[pid] = {
                "id": pid,
                "circle_id": circle_id,
                "subject": subject.strip(),
                "issue_id": issue_id,
                "parties": list(parties),
                "score": None,
                "score_evidence": [],
                "status": "proposed",
                "acks": [],
                "created_by": proposer_sub,
                "created_at": _now(),
            }
        if self._flow is not None:
            self._flow.insert_proposal(self._proposals[pid])
        return PortOpResult(ok=True, id=pid, data={"proposal_id": pid, "proposal": self._proposals[pid]})

    def score(self, proposal_id: str, score: float, evidence: List[Dict[str, Any]]) -> PortOpResult:
        """打分：必须带证据。分数决定状态推进方向。"""
        with self._lock:
            prop = self._proposals.get(proposal_id)
            if prop is None:
                return PortOpResult(ok=False, error=f"proposal not found: {proposal_id}")
            if prop["status"] != "proposed":
                return PortOpResult(ok=False, error=f"proposal not in proposed state: {prop['status']}")
            if not evidence or len(evidence) == 0:
                return PortOpResult(ok=False, error="score requires score_evidence")
            for ev in evidence:
                if not all(k in ev for k in ("by_sub", "basis", "at")):
                    return PortOpResult(ok=False, error="evidence item requires by_sub/basis/at")
            prop["score"] = score
            prop["score_evidence"] = list(evidence)
            if score < self._threshold:
                prop["status"] = "below_threshold"
            else:
                # 契约：passed 后仍需人工确认 → awaiting_ack
                prop["status"] = "awaiting_ack"
        if self._flow is not None:
            self._flow.update_proposal(
                proposal_id,
                status=prop["status"],
                score=prop["score"],
                score_evidence=prop["score_evidence"],
            )
        return PortOpResult(ok=True, id=proposal_id, data={"proposal": dict(prop), "threshold": self._threshold})

    def acknowledge(self, proposal_id: str, ack_sub: str, actor_is_ai: bool = False) -> PortOpResult:
        """人工 party 确认。AI 不能 ack。全部 party ack → consensus_verified。"""
        if actor_is_ai:
            return PortOpResult(ok=False, error="AI cannot acknowledge as a party")
        with self._lock:
            prop = self._proposals.get(proposal_id)
            if prop is None:
                return PortOpResult(ok=False, error=f"proposal not found: {proposal_id}")
            if prop["status"] not in ("awaiting_ack", "consensus_passed"):
                return PortOpResult(ok=False, error=f"proposal not awaiting ack: {prop['status']}")
            if ack_sub not in prop["parties"]:
                return PortOpResult(ok=False, error="acker is not a party")
            if any(a["sub"] == ack_sub for a in prop["acks"]):
                return PortOpResult(ok=False, error="already acked")
            prop["acks"].append({"sub": ack_sub, "at": _now()})
            if len(prop["acks"]) >= len(prop["parties"]):
                prop["status"] = "consensus_verified"
            else:
                prop["status"] = "awaiting_ack"
        # G6 落库：非 verified 直接写；verified 由 api_ack 的
        # verify_and_advance_floor 同事务写（含地板轮转，见 circle_web.api_ack）
        if self._flow is not None and prop["status"] != "consensus_verified":
            self._flow.append_ack(proposal_id, ack_sub, prop["acks"][-1]["at"], prop["status"])
        return PortOpResult(
            ok=True, id=proposal_id,
            data={"proposal": dict(prop), "can_complete": prop["status"] == "consensus_verified"},
        )

    def get_status(self, proposal_id: str) -> PortOpResult:
        with self._lock:
            prop = self._proposals.get(proposal_id)
            if prop is None:
                return PortOpResult(ok=False, error=f"proposal not found: {proposal_id}")
            return PortOpResult(
                ok=True, id=proposal_id,
                data={
                    "proposal": dict(prop),
                    "threshold": self._threshold,
                    "can_complete": prop["status"] == "consensus_verified",
                },
            )

    def expire(self, proposal_id: str) -> PortOpResult:
        """超时/作废：不提升到 verified。"""
        with self._lock:
            prop = self._proposals.get(proposal_id)
            if prop is None:
                return PortOpResult(ok=False, error=f"proposal not found: {proposal_id}")
            if prop["status"] == "consensus_verified":
                return PortOpResult(ok=False, error="verified proposal cannot be expired")
            prop["status"] = "expired"
        if self._flow is not None:
            self._flow.update_proposal(proposal_id, status=prop["status"])
        return PortOpResult(ok=True, id=proposal_id, data={"proposal": dict(prop)})

    # ------------------------------------------------------------------ #
    # 信号摄入（Step3 W3）：consensus_match → 共议证据
    # ------------------------------------------------------------------ #

    def ingest_signal(self, signal_id: str, user_id_hash: str, payload: Dict[str, Any]) -> PortOpResult:
        """接收 consensus_match 信号，作为 score 证据挂起。

        stub 阶段：只记录调用，不自动推进状态机（score 仍需显式触发）。
        返回的 evidence 可在后续 score() 中引用。
        """
        with self._lock:
            ev = {
                "signal_id": signal_id,
                "user_id_hash": user_id_hash,
                "payload": dict(payload),
                "received_at": _now(),
            }
            self._signal_evidence.append(ev)
        return PortOpResult(ok=True, id=signal_id, data={"evidence": dict(ev)})

    def list_signal_evidence(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._signal_evidence]

    # ------------------------------------------------------------------ #
    # 查询辅助
    # ------------------------------------------------------------------ #

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(p) for p in self._proposals.values()]
