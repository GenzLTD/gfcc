"""contribution 端口 —— CoCo 循环 stub。

对齐 contracts/contribution.v1.json：
- 循环：attest → fulfill → appeal。
- 不能只为自己 attest（作为唯一证据）。
- fulfill 在申诉窗口未打开时可向 identity.append_trace 提供 evidence 权重轨迹。
- 申诉存在前，声誉写回不 final；治理权利不可购买。
- operations: attest / fulfill / appeal / resolve_appeal。
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import uuid

from ..envelope import PortOpResult

if TYPE_CHECKING:
    from .identity import IdentityAdapter

VALID_STATUSES = {"attested", "fulfilled", "appealed", "overturned", "withdrawn"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class ContributionAdapter:
    """CoCo 循环 stub。内存实现，空数据合法。"""

    def __init__(self, identity: Optional["IdentityAdapter"] = None) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, Dict[str, Any]] = {}
        # G6 兑现入口：fulfill 成功且申诉未打开时，向 identity.append_trace mint
        # contribution evidence 轨迹（contribution 在 EVIDENCE_SOURCES 白名单内）。
        self._identity = identity

    # ------------------------------------------------------------------ #
    # operations
    # ------------------------------------------------------------------ #

    def attest(self, circle_id: str, subject_sub: str, attestor_sub: str, claim: str,
               action_id: Optional[str] = None) -> PortOpResult:
        """认定贡献。不能只为自己 attest 作为唯一证据（stub 仅做记录级校验）。"""
        if not claim or not claim.strip():
            return PortOpResult(ok=False, error="claim is required")
        if subject_sub == attestor_sub:
            return PortOpResult(ok=False, error="cannot attest solely for oneself as the only evidence")
        rid = str(uuid.uuid4())
        with self._lock:
            self._records[rid] = {
                "id": rid,
                "circle_id": circle_id,
                "subject_sub": subject_sub,
                "attestor_sub": attestor_sub,
                "claim": claim.strip(),
                "action_id": action_id,
                "status": "attested",
                "fulfilled_at": None,
                "appeal": None,
                "created_at": _now(),
            }
        return PortOpResult(ok=True, id=rid, data={"record": self._records[rid]})

    def fulfill(self, record_id: str, steward_sub: str) -> PortOpResult:
        """兑现：attested → fulfilled。申诉未打开时可为 identity 提供 evidence 轨迹。"""
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                return PortOpResult(ok=False, error=f"record not found: {record_id}")
            if rec["status"] != "attested":
                return PortOpResult(ok=False, error=f"record not attested: {rec['status']}")
            rec["status"] = "fulfilled"
            rec["fulfilled_at"] = _now()
            rec["fulfilled_by"] = steward_sub
            # G6 兑现入口：申诉未打开 → contribution 端口向 identity mint evidence 轨迹
            # （identity 不自证能力，兑现轨迹由 contribution 侧写入，兑现人才有资格）
            minted_trace_id: Optional[str] = None
            if self._identity is not None and rec.get("appeal") is None:
                tr = self._identity.append_trace(
                    sub=rec["subject_sub"],
                    label=f"contribution:{rec['claim'][:50]}",
                    source_port="contribution",
                    weight="evidence",
                )
                if tr.ok:
                    minted_trace_id = tr.id
                    rec["minted_trace_id"] = minted_trace_id
            return PortOpResult(
                ok=True, id=record_id,
                data={
                    "record": dict(rec),
                    "may_mint_trace": True,
                    "minted_trace_id": minted_trace_id,
                    "source_port": "contribution",
                    "weight": "evidence",
                },
            )

    def appeal(self, record_id: str, by_sub: str, reason: str) -> PortOpResult:
        """申诉：fulfilled → appealed（或 attested → appealed）。"""
        if not reason or not reason.strip():
            return PortOpResult(ok=False, error="appeal reason is required")
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                return PortOpResult(ok=False, error=f"record not found: {record_id}")
            if rec["status"] not in ("attested", "fulfilled"):
                return PortOpResult(ok=False, error=f"record not appealable: {rec['status']}")
            rec["status"] = "appealed"
            rec["appeal"] = {
                "by_sub": by_sub,
                "reason": reason.strip(),
                "opened_at": _now(),
                "resolved_at": None,
                "resolution": None,
            }
            # 申诉打开 → 声誉写回不 final
            rec["write_back_final"] = False
        return PortOpResult(ok=True, id=record_id, data={"record": dict(rec)})

    def resolve_appeal(self, record_id: str, organizer_sub: str, resolution: str) -> PortOpResult:
        """裁定申诉：upheld → 回到 fulfilled（写回 final）；overturned → overturned。"""
        if resolution not in ("upheld", "overturned"):
            return PortOpResult(ok=False, error=f"invalid resolution: {resolution}")
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                return PortOpResult(ok=False, error=f"record not found: {record_id}")
            if rec.get("appeal") is None:
                return PortOpResult(ok=False, error="no open appeal")
            rec["appeal"]["resolved_at"] = _now()
            rec["appeal"]["resolution"] = resolution
            if resolution == "upheld":
                rec["status"] = "fulfilled"
                rec["write_back_final"] = True
            else:
                rec["status"] = "overturned"
                rec["write_back_final"] = False
        return PortOpResult(ok=True, id=record_id, data={"record": dict(rec)})

    def withdraw(self, record_id: str, by_sub: str) -> PortOpResult:
        """撤回：attested → withdrawn。"""
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                return PortOpResult(ok=False, error=f"record not found: {record_id}")
            if rec["status"] not in ("attested", "fulfilled"):
                return PortOpResult(ok=False, error=f"record not withdrawable: {rec['status']}")
            rec["status"] = "withdrawn"
        return PortOpResult(ok=True, id=record_id, data={"record": dict(rec)})

    # ------------------------------------------------------------------ #
    # 查询辅助
    # ------------------------------------------------------------------ #

    def get(self, record_id: str) -> PortOpResult:
        """按 id 取记录（供 web 层校验记录归属圈）。"""
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                return PortOpResult(ok=False, error=f"record not found: {record_id}")
            return PortOpResult(ok=True, id=record_id, data={"record": dict(rec)})

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._records.values()]
