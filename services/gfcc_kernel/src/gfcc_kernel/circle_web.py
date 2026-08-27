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
- 拍板句只允许建圈的 organizer（A）写；旁观 C 不入座（只轮询 status，用自己的
  令牌即可看），未进 parties 时 ack 会被端口拒绝（not a party）。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# 延迟到函数体内访问 app 单例（避免与 app.py 循环 import）
from . import app as _app

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
    """B（或 C）入座。重复入座 / 已解散圈子 → 400。"""
    sub = _sub(request)
    res = _app._registry.get("circle").join(body.circle_id, sub)
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error)
    return {"circle_id": res.id, "members": res.data["members"]}


class ProposeBody(BaseModel):
    circle_id: str
    subject: str
    basis: str = ""


@router.post("/api/propose")
async def api_propose(request: Request, body: ProposeBody) -> Dict[str, Any]:
    """A（建圈的 organizer）写拍板句：propose + score 一步到位。

    - 只有 organizer 能写，避免多成员各交一条互相覆盖。
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
    if roles[sub] != "organizer":
        raise HTTPException(status_code=403, detail="only the organizer (A) may propose")
    member_subs = list(roles)
    if len(member_subs) < 2:
        raise HTTPException(status_code=400, detail="need at least 2 seated members before proposing")

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
    return {
        "circle_id": body.circle_id,
        "proposal_id": body.proposal_id,
        "proposal": res.data["proposal"],
        "can_complete": res.data["can_complete"],
    }


@router.get("/api/status")
async def api_status(request: Request, circle_id: str) -> Dict[str, Any]:
    """圈状态：成员 + 拍板句 + 确认进度。

    需 Bearer：旁观 C 也要自己的令牌才能看（安全），但不必入座。
    """
    _sub(request)
    circle = _circle(circle_id)
    proposals = _proposals_in(circle_id)
    return {"circle": circle, "proposals": proposals}


@router.get("/api/me")
async def api_me(request: Request) -> Dict[str, Any]:
    """当前令牌是谁。页面入场时调用。"""
    return {"sub": _sub(request)}
