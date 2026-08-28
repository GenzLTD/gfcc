"""围坐会场 web 面（Circle Lounge）。

公网会场入口：`GET /circle/` 单页 + `/circle/api/*` 轻量端点。

对应 testers 须知流程：
    1. A 建圈（create）→ 得到圈号（circle_id）
    2. B 入座（join）→ 圈内成员 2 人
    3. A 写拍板句（propose + score，parties=圈内成员）→ awaiting_ack
    4. A、B 各自点确认（acknowledge）→ 全部 party ack → consensus_verified

- 认证：复用 ethos Bearer（HS256 严格模式；stub 模式空 token 仅本地联调）。
- 复用 circle / consensus 端口适配器（进程内，单 worker 语义，一场围坐足够）。
- 围坐 API 刻意挂在 /circle 前缀，不占 /v1/：天翼 nginx 的 /v1/ 已反代 Looma。
- 发言权轮询（施工单「围坐会场_发言权轮询实施.md」）：建圈者先持地板，
  只有当前 floor_sub 能 propose；一条 consensus_verified 后按入座顺序交给
  下一位（两人圈 A→B→A）；一次一条（pending 时后端拒绝再提）；提议人中途
  leave 后地板已在 leave 时交接，达成后不再多跳一格。旁观 C 不入座（只轮询
  status，用自己的令牌即可看），未进 parties 时 ack 会被端口拒绝（not a party）。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# 延迟到函数体内访问 app 单例（避免与 app.py 循环 import）
from . import app as _app
from . import circle_flow as _flow_mod
from . import invites as _invites
from . import tokens as _tokens
from .ports.circle import next_floor

logger = logging.getLogger("gfcc_kernel.circle_web")

router = APIRouter(prefix="/circle", tags=["circle-web"])

_PAGE_FILE = Path(__file__).resolve().parent / "static" / "circle.html"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _sub(request: Request) -> str:
    """ethos 验签 + 取 actor sub。复用 app._verify_request（未认证 401）。"""
    _app._verify_request(request)  # noqa: SLF001 同仓库复用
    return _app._policy.sub or "stub-anon"


def _circle(circle_id: str) -> Dict[str, Any]:
    res = _app._registry.get("circle").get(circle_id)
    if not res.ok:
        raise HTTPException(status_code=404, detail=res.error)
    return res.data["circle"]


def _proposals_in(circle_id: str) -> List[Dict[str, Any]]:
    consensus = _app._registry.get("consensus")
    return [dict(p) for p in consensus.list_all() if p.get("circle_id") == circle_id]


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #


@router.get("/", response_class=HTMLResponse)
async def circle_page() -> str:
    return _PAGE_FILE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

# redeem 失败限流：进程内计数（单 worker 语义），同 IP 10 分钟内失败 20 次 → 429。
# 成功兑换不计数（防误伤正常 tester）；重启即清零（已知边界，见部署手册 §9）。
_RATE_WINDOW_SEC = 600
_RATE_FAIL_LIMIT = 20
_rate_fails: Dict[str, Deque[float]] = {}


def _rate_blocked(ip: str) -> bool:
    now = time.time()
    q = _rate_fails.get(ip)
    if not q:
        return False
    while q and now - q[0] > _RATE_WINDOW_SEC:
        q.popleft()
    return len(q) >= _RATE_FAIL_LIMIT


def _rate_note_fail(ip: str) -> None:
    _rate_fails.setdefault(ip, deque()).append(time.time())


class RedeemBody(BaseModel):
    code: str = ""


@router.post("/api/redeem")
async def api_redeem(request: Request, body: RedeemBody) -> Dict[str, Any]:
    """邀请深链兑换：16 位码 → sub + 会话 JWT（无 Bearer）。

    - 码只走 POST body，不进 URL query（天翼 nginx 访问日志不记录 query，
      但也别把码放 URL 自找风险）。
    - 失败（未知/过期/已兑换）按 IP 计数，10 分钟 20 次封禁。
    - 成功即签 JWT（与 issue_persona_tokens.py 同实现/同密钥），
      随后前端拿 token 走 /api/me 入场。
    """
    ip = request.client.host if request.client else "unknown"
    code = (body.code or "").strip().upper()
    if not _invites.is_valid_code(code):
        raise HTTPException(status_code=400, detail="invalid code")
    if _rate_blocked(ip):
        raise HTTPException(status_code=429, detail="too many failed attempts, please try again later")
    status, sub, _exp = _invites.get_store().redeem(code)
    if status == "missing":
        _rate_note_fail(ip)
        raise HTTPException(status_code=404, detail="invite not found")
    if status == "used":
        _rate_note_fail(ip)
        raise HTTPException(status_code=410, detail="invite already used — 请向主持人再要一条，或粘贴备用令牌")
    token = _tokens.issue_token(sub, _tokens.load_secret(), days=30)
    return {"sub": sub, "token": token}


class CreateBody(BaseModel):
    name: str = "围坐"


@router.post("/api/create")
async def api_create(request: Request, body: CreateBody) -> Dict[str, Any]:
    """A 建圈。返回圈号，由 A 分享给其他 tester。"""
    sub = _sub(request)
    res = _app._registry.get("circle").create(sub, body.name.strip() or "围坐")
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    return {"circle_id": res.id, "circle": res.data["circle"]}


class JoinBody(BaseModel):
    circle_id: str


@router.post("/api/join")
async def api_join(request: Request, body: JoinBody) -> Dict[str, Any]:
    """B（或 C）入座。重复入座视为重新入座（幂等）；已解散圈子 → 400。"""
    sub = _sub(request)
    res = _app._registry.get("circle").join(body.circle_id, sub)
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    return {"circle_id": res.id, "members": res.data["members"]}


class LeaveBody(BaseModel):
    circle_id: str


@router.post("/api/leave")
async def api_leave(request: Request, body: LeaveBody) -> Dict[str, Any]:
    """本人退场：把自己从圈成员中移除、释放席位。

    退出只是本地清 token 的话后端席位还在，重新入座会撞
    "already a member"；因此前端「退出」按钮必须先调这里。
    退场后同一令牌可随时重新入座（join 幂等）。
    """
    sub = _sub(request)
    res = _app._registry.get("circle").leave(body.circle_id, sub)
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    return {"circle_id": res.id, "members": res.data["members"]}


class ProposeBody(BaseModel):
    circle_id: str
    subject: str
    basis: str = ""


@router.post("/api/propose")
async def api_propose(request: Request, body: ProposeBody) -> Dict[str, Any]:
    """发言权持有者写拍板句：propose + score 一步到位（施工单 §5）。

    - 只有当前 floor_sub（发言权持有者）能写；建圈者先持地板，一条
      consensus_verified 后按入座顺序交给下一位（两人圈 A→B→A）。
    - 一次一条：圈内已有未达成提案（pending）时后端同样拒绝再提议，
      不只靠前端藏按钮。
    - parties = 当前圈内全部已入座成员；提交后直接进入 awaiting_ack，
      之后每位 party 各自点确认（/api/ack）。
    - score 仅用于跨过阈值进入 awaiting_ack；evidence 是 proposer 本人的依据
      （kind=proposer_basis），不是「跨组共识分」——做引用/兑现时不要把 90 当共识质量分。
    """
    sub = _sub(request)
    circle = _circle(body.circle_id)
    roles = {m["sub"]: m.get("role", "participant") for m in circle["members"]}
    if sub not in roles:
        raise HTTPException(status_code=403, detail="only seated members may propose")
    if circle.get("floor_sub") != sub:
        raise HTTPException(status_code=403, detail="not your floor")
    member_subs = list(roles)
    if len(member_subs) < 2:
        raise HTTPException(status_code=400, detail="need at least 2 seated members before proposing")
    pending = [p for p in _proposals_in(body.circle_id) if p["status"] != "consensus_verified"]
    if pending:
        raise HTTPException(status_code=400, detail="pending proposal exists")

    consensus = _app._registry.get("consensus")
    res = consensus.propose(body.circle_id, body.subject, parties=member_subs, proposer_sub=sub)
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    pid = res.id

    basis = body.basis.strip() or body.subject.strip()
    score_res = consensus.score(
        pid,
        90.0,
        evidence=[{"by_sub": sub, "basis": basis, "at": _now(), "kind": "proposer_basis"}],
    )
    if not score_res.ok:
        raise HTTPException(status_code=400, detail=score_res.error)
    return {
        "circle_id": body.circle_id,
        "proposal_id": pid,
        "proposal": score_res.data["proposal"],
        "threshold": score_res.data["threshold"],
    }


class AckBody(BaseModel):
    circle_id: str
    proposal_id: str


@router.post("/api/ack")
async def api_ack(request: Request, body: AckBody) -> Dict[str, Any]:
    """本人点确认。只有 proposal 的 party 能 ack；AI/旁观者被端口拒绝。"""
    sub = _sub(request)
    consensus = _app._registry.get("consensus")
    st = consensus.get_status(body.proposal_id)
    if not st.ok:
        raise HTTPException(status_code=404, detail=st.error)
    if st.data["proposal"]["circle_id"] != body.circle_id:
        raise HTTPException(status_code=400, detail="proposal not in this circle")
    res = consensus.acknowledge(body.proposal_id, sub)
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    floor_sub = None
    if res.data["can_complete"]:
        # §4.3 达成一条 → 轮询交接：地板从提议人交给下一位。
        # 仅当地板还在提议人身上时 advance（提议人中途 leave 的话，
        # 地板已在 leave 时交接，这里不再多跳一格）。
        proposer = res.data["proposal"].get("created_by")
        circle = _circle(body.circle_id)
        if circle.get("floor_sub") == proposer:
            # persist=False：不单独写库，库写交给下方 verify_and_advance_floor 同事务
            adv = _app._registry.get("circle").advance_floor(body.circle_id, proposer, persist=False)
            if adv.ok:
                floor_sub = adv.data["floor_sub"]
        # G6 决策②：ack 达成 + 地板轮转同事务落库（库中不会出现
        # 「已 verified 而地板未转」的半态）
        flow = _flow_mod.get_store()
        if flow is not None:
            flow.verify_and_advance_floor(
                body.proposal_id,
                body.circle_id,
                status=res.data["proposal"]["status"],
                verified_at=res.data["proposal"]["acks"][-1]["at"],
                acks=res.data["proposal"]["acks"],
                floor_sub=floor_sub,
            )
    return {
        "circle_id": body.circle_id,
        "proposal_id": body.proposal_id,
        "proposal": res.data["proposal"],
        "can_complete": res.data["can_complete"],
        "floor_sub": floor_sub,
    }


@router.get("/api/status")
async def api_status(request: Request, circle_id: str) -> Dict[str, Any]:
    """圈状态：成员 + 拍板句 + 确认进度 + 当前发言权（floor）。

    需 Bearer：旁观 C 也要自己的令牌才能看（安全），但不必入座。
    floor_sub = 当前发言权持有者；floor_next_sub = 本条达成后交给谁（4.4 预览）。
    """
    _sub(request)
    circle = _circle(circle_id)
    proposals = _proposals_in(circle_id)
    floor_sub = circle.get("floor_sub")
    floor_next_sub = next_floor(circle.get("members", []), floor_sub) if floor_sub else None
    return {
        "circle": circle,
        "proposals": proposals,
        "floor_sub": floor_sub,
        "floor_next_sub": floor_next_sub,
    }


@router.get("/api/me")
async def api_me(request: Request) -> Dict[str, Any]:
    """当前令牌是谁。页面入场时调用。"""
    return {"sub": _sub(request)}


# --------------------------------------------------------------------------- #
# G6 兑现与升级（CoCo 循环 + 八角梯）：
#   - /api/attest   A 认定 B 的贡献（contribution.attest，participant+）
#   - /api/fulfill  兑现承诺（contribution.fulfill，steward+，兑现入口 → identity trace）
#   - /api/promote  C 升级（identity.promote_role，organizer 执行，须带证据）
# --------------------------------------------------------------------------- #

# contracts/roles.v1.json role_enum（八角梯），index 越大级别越高
_ROLE_LADDER = ["observer", "participant", "experimenter", "proposer", "steward", "organizer", "actor", "petitioner"]


def _member_role(circle: Dict[str, Any], sub: str) -> Optional[str]:
    for m in circle.get("members", []):
        if m["sub"] == sub:
            return m.get("role", "participant")
    return None


def _role_at_least(role: Optional[str], required: str) -> bool:
    if role is None:
        return False
    return _ROLE_LADDER.index(role) >= _ROLE_LADDER.index(required)


class AttestBody(BaseModel):
    circle_id: str
    subject_sub: str
    claim: str


@router.post("/api/attest")
async def api_attest(request: Request, body: AttestBody) -> Dict[str, Any]:
    """A 认定 B 的贡献：contribution.attest（CoCo 循环第一步）。

    - 需要圈内成员（participant+，roles.v1 participant 含 contribution.attest）。
    - 不能只为自己 attest 作为唯一证据（端口拒绝 subject == attestor）。
    - 返回 record_id，随后可走 /api/fulfill 兑现。
    """
    sub = _sub(request)
    circle = _circle(body.circle_id)
    if sub not in [m["sub"] for m in circle.get("members", [])]:
        raise HTTPException(status_code=403, detail="only seated members may attest")
    res = _app._registry.get("contribution").attest(body.circle_id, body.subject_sub, sub, body.claim)
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    return {"circle_id": body.circle_id, "record_id": res.id, "record": res.data["record"]}


class FulfillBody(BaseModel):
    circle_id: str
    record_id: str


@router.post("/api/fulfill")
async def api_fulfill(request: Request, body: FulfillBody) -> Dict[str, Any]:
    """兑现承诺：contribution.fulfill（CoCo 循环第二步，G6 兑现入口）。

    - 需要 steward+（roles.v1 steward 含 contribution.fulfill）。
    - 兑现成功且申诉未打开 → contribution 端口向 identity mint evidence 轨迹
      （返回 minted_trace_id；identity 不自证能力）。
    """
    sub = _sub(request)
    circle = _circle(body.circle_id)
    role = _member_role(circle, sub)
    if not _role_at_least(role, "steward"):
        raise HTTPException(status_code=403, detail="only steward or above may fulfill")
    contribution = _app._registry.get("contribution")
    rec = contribution.get(body.record_id)
    if not rec.ok:
        raise HTTPException(status_code=404, detail=rec.error)
    if rec.data["record"].get("circle_id") != body.circle_id:
        raise HTTPException(status_code=400, detail="record not in this circle")
    res = contribution.fulfill(body.record_id, sub)
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    return {
        "circle_id": body.circle_id,
        "record_id": res.id,
        "record": res.data["record"],
        "minted_trace_id": res.data["minted_trace_id"],
    }


class PromoteBody(BaseModel):
    circle_id: str
    sub: str
    new_role: str
    evidence_ids: List[str] = []


@router.post("/api/promote")
async def api_promote(request: Request, body: PromoteBody) -> Dict[str, Any]:
    """C 升级：identity.promote_role（带证据，禁止只拨 admin）。

    - 需要 organizer（roles.v1 transitions：升级 driven_by 证据记录；
      admin toggle 是 ops_exception，需 audit 为 admin.role.set）。
    - new_role 必须在八角梯；evidence_ids 必须非空且引用真实记录
      （memory records / contribution fulfillments / consensus_verified）。
    - C 旁观不入座：升级的是 identity 画像 role，升级后即可 join 入座。
    """
    sub = _sub(request)
    circle = _circle(body.circle_id)
    role = _member_role(circle, sub)
    if not _role_at_least(role, "organizer"):
        raise HTTPException(status_code=403, detail="only organizer or above may promote")
    res = _app._registry.get("identity").promote_role(
        body.sub, body.new_role, body.evidence_ids, changed_by=sub,
        note=f"promoted by organizer in circle {body.circle_id}",
    )
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    return {"sub": body.sub, "profile": res.data["profile"], "old_role": res.data["old_role"]}
