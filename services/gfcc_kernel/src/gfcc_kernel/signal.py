"""信号摄入 —— signal.envelope.v1（机机事件入口，与 ask.envelope.v1 并列）。

对齐 docs/Phase2_Step3_信号契约与协调方案.md 附录 A（草案 v1.0.0，G1 冻结后
以 contracts/signal.envelope.v1.json 为真源）：

- 入口：POST /v1/signal-ingest（本文件只含纯逻辑，FastAPI 端点见 app.py）。
- 签名：HMAC-SHA256(SIGNAL_INGEST_SECRET, raw_body)，header `X-Signature`，hex 小写。
- 幂等键：(signal_type, user_id_hash, nonce)，数据库 UNIQUE。
- 信封严格：additionalProperties=false；缺/多余字段一律 422。
- 路由：consensus_match → consensus；personality_beacon → identity。

红线：信号必须源自用户真实动作（确认匹配、完成测评），payload 只传 hash 与
类型化结果，不传明文 email / 原始答题 / 对端身份信息。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SIGNAL_TYPE = Literal["consensus_match", "personality_beacon"]

MBTI_TYPES = {
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
}

HASH_RE = re.compile(r"^[a-f0-9]{64}$")

# 信号类型 → 端口（W3 路由，确定性，不经 llm 槽）
SIGNAL_ROUTE = {
    "consensus_match": "consensus",
    "personality_beacon": "identity",
}

# 各信号 payload 的 source 固定值（用于追溯产生方）
SIGNAL_SOURCE = {
    "consensus_match": "demoppi",
    "personality_beacon": "planetx",
}


class SignalEnvelope(BaseModel):
    """signal.envelope.v1 请求体：additionalProperties=false（契约强制拒绝多余字段）。

    字段（见方案 §2.2）：
    - signal_type: consensus_match | personality_beacon（enum）
    - user_id_hash: sha256(email.lower().trim())，64 位小写 hex
    - nonce: 幂等键成分，uuid4 hex（min 8）
    - timestamp: 可选，仅审计用途
    - payload: 由各自 signal 契约严格定义（必填 object）
    """

    model_config = ConfigDict(extra="forbid")

    signal_type: SIGNAL_TYPE
    user_id_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    nonce: str = Field(min_length=8)
    timestamp: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class PayloadError(ValueError):
    """payload 不符合对应 signal 契约。"""


def verify_signature(secret: str, raw_body: bytes, header_signature: str) -> bool:
    """HMAC-SHA256(secret, raw_body) 与 X-Signature 恒定时间比较。"""
    if not header_signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_signature.strip().lower())


def validate_payload(signal_type: str, payload: Dict[str, Any]) -> None:
    """按草案 §3.1/§3.2 校验 payload 必填字段与约束。

    三份 signal JSON Schema 由 Mac 侧在 G1 冻结后入库 contracts/；本函数为
    种子期轻量校验（不拒绝 payload 内未列字段，等 Schema 入库后严格化）。
    """
    if signal_type == "consensus_match":
        score = payload.get("match_score")
        if score is None or not isinstance(score, (int, float)) or isinstance(score, bool):
            raise PayloadError("consensus_match requires match_score (number 0..1)")
        if not 0.0 <= float(score) <= 1.0:
            raise PayloadError("match_score must be within 0..1")
        tags = payload.get("shared_tags")
        if not isinstance(tags, list) or not 1 <= len(tags) <= 10:
            raise PayloadError("shared_tags required: string[] 1..10 items")
        if not all(isinstance(t, str) and t.strip() for t in tags):
            raise PayloadError("shared_tags items must be non-empty strings")
        peer = payload.get("peer_id_hash")
        if not isinstance(peer, str) or not HASH_RE.fullmatch(peer):
            raise PayloadError("peer_id_hash required: 64 hex")
        if payload.get("source") != "demoppi":
            raise PayloadError("source must be 'demoppi'")
    elif signal_type == "personality_beacon":
        ptype = payload.get("personality_type")
        if not isinstance(ptype, str) or ptype.upper() not in MBTI_TYPES:
            raise PayloadError("personality_type required: MBTI 16 types")
        if payload.get("source") != "planetx":
            raise PayloadError("source must be 'planetx'")
    else:  # 不可达（信封 enum 已挡），防御性兜底
        raise PayloadError(f"unsupported signal_type: {signal_type}")


def route_signal(signal_type: str) -> str:
    """确定性路由：信号类型 → 端口名。"""
    return SIGNAL_ROUTE[signal_type]


def new_signal_id() -> str:
    """signal_id：uuid4 hex（与信封 nonce 不同，服务端生成）。"""
    return uuid.uuid4().hex


def build_hmac_signature(secret: str, raw_body: bytes) -> str:
    """发送端辅助：构造 X-Signature（mock 发送器 / 测试复用）。"""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
