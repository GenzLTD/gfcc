"""内核调度 —— parse_then_dispatch。

对齐 contracts/ask.envelope.v1.json 的 dispatch 语义：
- parse: message + context → { port, confidence, slots, dialog_mode }。
  port_hint 优先；否则基于关键词规则解析；默认 unknown。
- dispatch: port → tools registry adapter，执行后返回 { port, status, result, suggestions }。
- intent 是 port 的弃用别名；响应 port 必须是第一类端口名或 unknown，绝不是 JobFirst intent 名。
- 加能力 = 注册适配器 + 模式清单，不增长 JobFirst intent 表。
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .envelope import AskRequest, AskResponse, AskResult, ReceiptItem
from .registry import KernelContext, PortRegistry, FIRST_CLASS_PORTS

# --------------------------------------------------------------------------- #
# 端口关键词规则（仅作 stub 解析；生产可由 llm 槽接管）
# --------------------------------------------------------------------------- #

PORT_KEYWORDS: Dict[str, List[str]] = {
    "circle": ["围坐", "圈子", "建圈", "加入", "解散", "围桌", "create circle", "join", "dissolve", "circle"],
    "identity": ["画像", "身份", "价值观", "承诺", "能力", "标签", "我是谁", "profile", "identity", "values", "commitment"],
    "memory": ["记住", "记录", "记下", "回忆", "查找", "查询", "笔记", "七库", "议题", "行动", "事件", "remember", "recall", "memory", "note"],
    "consensus": ["共议", "共识", "提议", "表决", "确认", "同意", "打分", "consensus", "propose", "vote", "ack"],
    "contribution": ["贡献", "认定", "兑现", "申诉", "认可", "contribution", "attest", "fulfill", "appeal"],
}


def parse_port(message: str, ctx: Optional[KernelContext] = None,
               port_hint: Optional[str] = None) -> Tuple[str, float]:
    """解析 message → (port, confidence)。

    优先级：port_hint → llm 槽（语义分类）→ 关键词规则兜底。
    llm 槽不可用或调用失败时，一律 fallback 到关键词规则（不删，是 CI 基准）。
    """
    if port_hint and port_hint in FIRST_CLASS_PORTS:
        return port_hint, 1.0
    if port_hint == "unknown":
        return "unknown", 0.0

    llm = getattr(ctx, "llm", None) if ctx is not None else None
    if llm is not None and llm.is_available():
        try:
            result = llm.complete([{"role": "user", "content": message}])
            port = str(result.get("port", "unknown")).strip().lower()
            try:
                confidence = float(result.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if port in FIRST_CLASS_PORTS or port == "unknown":
                return port, min(1.0, max(0.0, confidence))
        except Exception:  # noqa: BLE001
            pass  # fallback to keywords

    return _parse_port_keywords(message)


def _parse_port_keywords(message: str) -> Tuple[str, float]:
    """关键词规则解析（stub 兜底，也是 CI 测试基准）。"""
    text = message.lower()
    best_port, best_score = "unknown", 0.0
    for port, keywords in PORT_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            if kw in text:
                score += 1.0
        # 短消息命中即高置信
        if score > 0:
            score = min(1.0, score * 0.6)
            if score > best_score:
                best_port, best_score = port, score
    return best_port, best_score


# --------------------------------------------------------------------------- #
# 端口执行
# --------------------------------------------------------------------------- #

def _execute_port(port: str, ctx: KernelContext, request: AskRequest) -> Dict[str, Any]:
    """执行单端口操作。返回 {status, id?, data?, error?}。

    stub 语义：message 里若带明确操作意图则调用对应方法，否则返回端口能力清单。
    空数据合法。
    """
    adapter = ctx.tools.get(port)
    if adapter is None:
        return {"status": "error", "error": f"port not registered: {port}"}

    msg = request.message.strip()
    m = msg.lower()
    circle_id = request.context.circle_id
    session_id = request.context.session_id

    if port == "circle":
        if re.search(r"建圈|创建|create|新建|发起", m):
            name = request.context.circle_id or "default-circle"
            r = adapter.create(ctx.policy.sub if ctx.policy else "system", name)
            return _wrap(r, "circle")
        if "join" in m or "加入" in m:
            if not circle_id:
                return {"status": "error", "error": "circle_id required to join"}
            r = adapter.join(circle_id, ctx.policy.sub if ctx.policy else "system")
            return _wrap(r, "circle")
        if "dissolve" in m or "解散" in m:
            if not circle_id:
                return {"status": "error", "error": "circle_id required to dissolve"}
            r = adapter.dissolve(circle_id, ctx.policy.sub if ctx.policy else "system")
            return _wrap(r, "circle")
        if "pause" in m or "暂停" in m:
            if not circle_id:
                return {"status": "error", "error": "circle_id required to pause"}
            r = adapter.pause(circle_id, ctx.policy.sub if ctx.policy else "system")
            return _wrap(r, "circle")
        return {
            "status": "ok",
            "data": {"circles": adapter.list_all(), "hint": "circle: create/join/leave/pause/dissolve"},
        }

    if port == "identity":
        sub = ctx.policy.sub if ctx.policy else None
        r = adapter.get_profile(sub) if sub else PortOpResultStub(ok=False, error="principal sub missing")
        return _wrap(r, "identity")

    if port == "memory":
        sub = ctx.policy.sub if ctx.policy else None
        if not sub:
            # 红线：没有 sub 不落到 "system"（Step1 按人隔离）
            return {"status": "error", "error": "principal sub missing"}
        if re.search(r"记住|记下|remember|写入|记录", m):
            # 提取正文（去掉操作词）
            body = _strip_action_prefix(msg, ["记住", "记下", "记录", "remember", "write"])
            if not body:
                return {"status": "error", "error": "body required for remember"}
            r = adapter.remember(
                library=_infer_library(m, request.context),
                body=body,
                actor_sub=sub,
                circle_id=circle_id,
            )
            return _wrap(r, "memory")
        r = adapter.recall(keyword=_infer_keyword(msg), actor_sub=sub, circle_id=circle_id)
        return _wrap(r, "memory")

    if port == "consensus":
        sub = ctx.policy.sub if ctx.policy else "system"
        # 提议：parties 来自圈内已入座真人（B2 修复，不再硬编码 ["member-a","member-b"]）
        if re.search(r"提议|propose|发起", m):
            if not circle_id:
                return {"status": "error", "error": "circle_id required to propose"}
            parties = _circle_parties(ctx, circle_id)
            if not parties or len(parties) < 2:
                return {"status": "error", "error": "circle parties required (>=2 seated members)"}
            subject = _strip_action_prefix(msg, ["提议", "propose", "发起"])
            r = adapter.propose(circle_id, subject, parties, sub)
            return _wrap(r, "consensus")
        # 打分：主持人显式 score → awaiting_ack（契约：分数无证据无效）
        if re.search(r"打分|score", m):
            pid = _extract_uuid(m)
            if not pid:
                return {"status": "error", "error": "proposal_id required for score (e.g. 打分 <id> 90 理由)"}
            score = _extract_score(m)
            if score is None:
                return {"status": "error", "error": "score value required (e.g. 打分 <id> 90 理由)"}
            evidence = [{
                "by_sub": sub,
                "basis": _strip_action_prefix(msg, ["打分", "score"]),
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }]
            r = adapter.score(pid, score, evidence)
            return _wrap(r, "consensus")
        # 确认：真人 party ack（AI 不能 ack，端口层已校验）
        if re.search(r"确认|同意|acknowledge", m):
            pid = _extract_uuid(m) or _latest_proposal_id(adapter, circle_id)
            if not pid:
                return {"status": "error", "error": "proposal_id required for ack (e.g. 确认 <id>)"}
            r = adapter.acknowledge(pid, sub)
            return _wrap(r, "consensus")
        # 状态回看：契约 can_complete 判定
        if re.search(r"查看|状态|status", m):
            pid = _extract_uuid(m) or _latest_proposal_id(adapter, circle_id)
            if not pid:
                return {"status": "error", "error": "proposal_id required for status (e.g. 查看 <id>)"}
            r = adapter.get_status(pid)
            return _wrap(r, "consensus")
        return {
            "status": "ok",
            "data": {"proposals": adapter.list_all(), "hint": "consensus: propose/score/ack/get_status"},
        }

    if port == "contribution":
        sub = ctx.policy.sub if ctx.policy else None
        # 兑现：attested → fulfilled，端口层 mint capability_trace（B3 修复）
        if re.search(r"兑现|fulfill", m):
            if not sub:
                return {"status": "error", "error": "principal sub missing"}
            rid = _extract_uuid(m)
            if not rid:
                return {"status": "error", "error": "record_id required for fulfill (e.g. 兑现 <id>)"}
            r = adapter.fulfill(rid, sub)
            return _wrap(r, "contribution")
        # 认定：attestor=本人（说话人），subject=消息里的他人（B3 修复，去掉写死 peer-sub）
        if re.search(r"认定|attest|完成了", m):
            if not circle_id:
                return {"status": "error", "error": "circle_id required to attest"}
            if not sub:
                return {"status": "error", "error": "principal sub missing"}
            mm = re.search(r"([a-zA-Z][\w.\-]*)\s*(?:完成了|完成|done)", m)
            if not mm:
                return {"status": "error", "error": "attest requires subject sub: 认定 <subject> 完成了 <claim>"}
            subject_sub = mm.group(1)
            if subject_sub == sub:
                return {"status": "error", "error": "cannot attest solely for oneself as the only evidence"}
            claim = _strip_attest_prefix(msg)
            r = adapter.attest(circle_id, subject_sub, sub, claim)
            return _wrap(r, "contribution")
        return {
            "status": "ok",
            "data": {"records": adapter.list_all(), "hint": "contribution: attest/fulfill/appeal"},
        }

    return {"status": "error", "error": f"unsupported port: {port}"}


def _wrap(r: Any, port: str) -> Dict[str, Any]:
    """把 PortOpResult 转为 dispatch 结果。"""
    if r is None:
        return {"status": "error", "error": "adapter returned None"}
    if getattr(r, "ok", False):
        return {"status": "ok", "id": getattr(r, "id", None), "data": getattr(r, "data", {})}
    return {"status": "error", "error": getattr(r, "error", "unknown error")}


class PortOpResultStub:
    def __init__(self, ok: bool, error: str):
        self.ok = ok
        self.error = error
        self.id = None
        self.data = {}


def _strip_action_prefix(msg: str, prefixes: List[str]) -> str:
    for p in prefixes:
        idx = msg.lower().find(p.lower())
        if idx >= 0:
            return msg[idx + len(p):].strip(" ：:，,。")
    return msg


# --------------------------------------------------------------------------- #
# B2/B3 解析辅助（信封层，stub 语义：正则为主，llm 槽可接管）
# --------------------------------------------------------------------------- #

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _extract_uuid(text: str) -> Optional[str]:
    m = _UUID_RE.search(text.lower())
    return m.group(0) if m else None


def _extract_score(text: str) -> Optional[float]:
    """提取 0-100 分数。uuid 段带连字符，不会被空白边界误命中。"""
    m = re.search(r"(?:^|\s)([0-9]{1,3})(?:\s|$|。)", text)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    return value if 0 <= value <= 100 else None


def _strip_attest_prefix(msg: str) -> str:
    text = re.sub(r"(认定|attest)", "", msg, flags=re.I)
    return text.strip(" ：:，,。")


def _circle_parties(ctx: KernelContext, circle_id: Optional[str]) -> Optional[List[str]]:
    """从圈内已入座真人取 parties（B2：不再硬编码假人）。"""
    if not circle_id:
        return None
    circ = ctx.tools.get("circle") if ctx.tools else None
    if circ is None:
        return None
    r = circ.get(circle_id)
    if not getattr(r, "ok", False):
        return None
    members = r.data.get("circle", {}).get("members", [])
    return [m["sub"] for m in members]


def _latest_proposal_id(adapter: Any, circle_id: Optional[str]) -> Optional[str]:
    """ack/status 未带 id 时，取该圈最近一条非终态提案兜底。"""
    for p in reversed(adapter.list_all()):
        if circle_id and p.get("circle_id") != circle_id:
            continue
        if p.get("status") in ("proposed", "scored", "consensus_passed", "awaiting_ack"):
            return p.get("id")
    return None


def _infer_library(msg: str, ctx: AskRequest) -> str:
    m = msg.lower()
    for lib in ("议题", "行动", "事件", "方法论", "人", "组织", "资源"):
        if lib in m:
            return {"议题": "issue", "行动": "action", "事件": "event",
                    "方法论": "methodology_value", "人": "person",
                    "组织": "org", "资源": "resource"}[lib]
    # 默认议题
    return "issue"


def _infer_keyword(msg: str) -> Optional[str]:
    """从消息里提取查询关键词（去除常见动词）。"""
    cleaned = re.sub(r"(查找|查询|回忆|搜索|找一下|看看|search|recall|find)", "", msg, flags=re.I)
    cleaned = cleaned.strip(" ：:，,。？?")
    return cleaned or None


# --------------------------------------------------------------------------- #
# 主调度
# --------------------------------------------------------------------------- #

def parse_then_dispatch(request: AskRequest, ctx: KernelContext) -> AskResponse:
    """解析 → 分发 → 组装信封响应。"""
    port, confidence = parse_port(request.message, ctx, request.context.port_hint)

    if port == "unknown" or confidence == 0.0:
        return AskResponse(
            port="unknown",
            status="unknown",
            result=AskResult(receipts=[]),
            suggestions=_suggestions_for_unknown(request.message),
            confidence=0.0,
        )

    exec_result = _execute_port(port, ctx, request)

    receipts = [
        ReceiptItem(
            port=port,
            status="ok" if exec_result.get("status") == "ok" else exec_result.get("status", "error"),
            id=exec_result.get("id"),
        )
    ]
    status = "ok" if exec_result.get("status") == "ok" else "error"

    suggestions: List[str] = []
    if status == "error":
        suggestions.append(f"{port} port error: {exec_result.get('error')}")

    data = exec_result.get("data", {})
    # 轻量结果统一塞进 receipts 可读字段以外的 suggestions（不侵入信封）
    if status == "ok":
        summary = _summarize(port, data)
        if summary:
            suggestions.append(summary)

    return AskResponse(
        port=port,
        status=status,
        result=AskResult(receipts=receipts),
        suggestions=suggestions,
        confidence=round(confidence, 2),
    )


def _summarize(port: str, data: Dict[str, Any]) -> str:
    if port == "identity":
        p = data.get("profile", {})
        return f"profile: {p.get('display_name') or p.get('sub')} | values={len(p.get('values', []))} tags={len(p.get('builder_tags', []))} trace={len(p.get('capability_trace', []))}"
    if port == "memory":
        if "record" in data and data.get("record"):
            return f"memory: record written ({data['record'].get('library')})"
        recs = data.get("records", [])
        if not recs:
            return "memory: no records yet (empty data is legal)"
        return f"memory: {data.get('count', len(recs))} record(s) found"
    if port == "consensus":
        if "proposal" in data:
            p = data["proposal"]
            score = p.get("score")
            return (
                f"consensus: {p.get('status')}"
                + (f" score={score}" if score is not None else "")
                + f" acks={len(p.get('acks', []))}/{len(p.get('parties', []))}"
            )
        props = data.get("proposals", [])
        return f"consensus: {len(props)} proposal(s)"
    if port == "contribution":
        recs = data.get("records", [])
        return f"contribution: {len(recs)} record(s)"
    if port == "circle":
        circles = data.get("circles", [])
        return f"circle: {len(circles)} circle(s)"
    return ""


def _suggestions_for_unknown(message: str) -> List[str]:
    return [
        "未识别到第一类端口意图。",
        "可尝试：围坐（circle）、画像（identity）、记忆（memory）、共议（consensus）、贡献（contribution）。",
        f"消息原文: {message[:80]}",
    ]
