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
        if re.search(r"建圈|create|新建|发起", m):
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
        if re.search(r"提议|propose|发起", m):
            if not circle_id:
                return {"status": "error", "error": "circle_id required to propose"}
            r = adapter.propose(circle_id, msg, ["member-a", "member-b"], ctx.policy.sub if ctx.policy else "system")
            return _wrap(r, "consensus")
        return {
            "status": "ok",
            "data": {"proposals": adapter.list_all(), "hint": "consensus: propose/score/acknowledge/get_status"},
        }

    if port == "contribution":
        if re.search(r"认定|attest|贡献", m):
            r = adapter.attest(circle_id or "default", ctx.policy.sub if ctx.policy else "system",
                               "peer-sub", msg)
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
