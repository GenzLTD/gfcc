"""信号摄入 —— signal.envelope.v1（机机事件入口，与 ask.envelope.v1 并列）。

对齐 docs/Phase2_Step3_信号契约与协调方案.md 附录 A（草案 v1.0.0，G1 冻结后
以 contracts/signal.envelope.v1.json 为真源）：

- 入口：POST /v1/signal-ingest（本文件只含纯逻辑，FastAPI 端点见 app.py）。
- 签名：HMAC-SHA256(SIGNAL_INGEST_SECRET, raw_body)，header `X-Signature`，hex 小写。
- 幂等键：(signal_type, user_id_hash, nonce)，数据库 UNIQUE。
- 信封严格：additionalProperties=false；缺/多余字段一律 422。
- 路由：consensus_match → consensus；personality_beacon → identity；
  value_axis_choice → identity。

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

SIGNAL_TYPE = Literal["consensus_match", "personality_beacon", "value_axis_choice"]

MBTI_TYPES = {
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
}

HASH_RE = re.compile(r"^[a-f0-9]{64}$")


def email_to_user_id_hash(email: str) -> str:
    """生态号：sha256(utf-8(email.lower().strip())) 的 64 位小写 hex。

    与 contracts/signal.envelope.v1.json 的 user_id_hash 同一算法（Bolent 入驻
    预埋 §3 钉死）：大小写折叠 + 首尾空白剥离后再哈希。明文邮箱不进 JWT、
    不进 signal_log、不进 --out JSON——任何地方只允许出现 64 位 hex。

    标准向量（docs/experiments/Bolent入驻预埋_Windows行动方案.md §3）：
      alice@example.com / Alice@Example.COM / ' alice@example.com '
      → ff8d9819fc0e12bf0d24892e45987e249a28dce836a85cad60e28eaaa8c6d976

    非法输入（非字符串或剥离后为空）抛 ValueError。
    """
    if not isinstance(email, str) or not email.strip():
        raise ValueError("email must be a non-empty string")
    return hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()

# 信号类型 → 端口（W3 路由，确定性，不经 llm 槽）
SIGNAL_ROUTE = {
    "consensus_match": "consensus",
    "personality_beacon": "identity",
    "value_axis_choice": "identity",
}

# 各信号 payload 的 source 固定值（用于追溯产生方）
SIGNAL_SOURCE = {
    "consensus_match": "demoppi",
    "personality_beacon": "planetx",
    "value_axis_choice": "planetx",
}

VALUE_AXES = {"survival", "freedom", "belonging"}
NAVIGATOR_DOMAINS = {"职业域", "身份域", "诗域", "信任域", "自我域", "迷雾域"}


class SignalEnvelope(BaseModel):
    """signal.envelope.v1 请求体：additionalProperties=false（契约强制拒绝多余字段）。

    字段（见方案 §2.2）：
    - signal_type: consensus_match | personality_beacon | value_axis_choice（enum）
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


# contracts/signals/*.v1.json 允许的 payload 键。信号线 1.1.0。
_PAYLOAD_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "consensus_match": {
        "allowed": {"match_score", "shared_tags", "peer_id_hash", "source", "generated_at"},
        "required": {"match_score", "shared_tags", "peer_id_hash", "source"},
    },
    "personality_beacon": {
        "allowed": {"personality_type", "traits", "assessment_score", "source", "generated_at"},
        "required": {"personality_type", "source"},
    },
    "value_axis_choice": {
        "allowed": {"axis", "imprint_name", "domain", "points", "source", "generated_at"},
        "required": {"axis", "imprint_name", "domain", "points", "source"},
    },
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_payload(signal_type: str, payload: Dict[str, Any]) -> None:
    """按冻结 Schema 校验 payload：required + additionalProperties=false + 字段约束。

    与 contracts/signals/*.v1.json（G1 冻结 v1.0.0）逐项对齐：
    - 顶层只允许契约列出的键，未列字段一律 PayloadError（→ 422 invalid_envelope）
    - required 缺一即报错
    - consensus_match：match_score∈[0,1]、shared_tags 1..10 非空串、peer_id_hash 64 hex、source=demoppi
    - personality_beacon：personality_type∈MBTI 16、traits[{name,score}] 严格、assessment_score number、source=planetx
    - value_axis_choice：axis∈三轴、domain∈导航六域、points∈1..5 整数、imprint_name 非空、source=planetx
    """
    schema = _PAYLOAD_SCHEMAS[signal_type]
    extra = set(payload) - schema["allowed"]
    if extra:
        raise PayloadError(f"{signal_type} payload has unlisted fields: {sorted(extra)}")
    missing = schema["required"] - set(payload)
    if missing:
        raise PayloadError(f"{signal_type} payload missing required: {sorted(missing)}")

    if signal_type == "consensus_match":
        score = payload["match_score"]
        if not _is_number(score) or not 0.0 <= float(score) <= 1.0:
            raise PayloadError("match_score must be number within 0..1")
        tags = payload["shared_tags"]
        if not isinstance(tags, list) or not 1 <= len(tags) <= 10:
            raise PayloadError("shared_tags required: string[] 1..10 items")
        if not all(isinstance(t, str) and t.strip() for t in tags):
            raise PayloadError("shared_tags items must be non-empty strings")
        peer = payload["peer_id_hash"]
        if not isinstance(peer, str) or not HASH_RE.fullmatch(peer):
            raise PayloadError("peer_id_hash required: 64 hex")
        if payload["source"] != "demoppi":
            raise PayloadError("source must be 'demoppi'")
    elif signal_type == "personality_beacon":
        ptype = payload["personality_type"]
        if not isinstance(ptype, str) or ptype.upper() not in MBTI_TYPES:
            raise PayloadError("personality_type required: MBTI 16 types")
        if payload["source"] != "planetx":
            raise PayloadError("source must be 'planetx'")
        traits = payload.get("traits")
        if traits is not None:
            if not isinstance(traits, list):
                raise PayloadError("traits must be array of {name, score}")
            for item in traits:
                if not isinstance(item, dict) or set(item) != {"name", "score"}:
                    raise PayloadError("traits item must be exactly {name, score}")
                if not isinstance(item["name"], str) or not item["name"].strip():
                    raise PayloadError("traits.name must be non-empty string")
                if not _is_number(item["score"]):
                    raise PayloadError("traits.score must be number")
        assessment = payload.get("assessment_score")
        if assessment is not None and not _is_number(assessment):
            raise PayloadError("assessment_score must be number")
    elif signal_type == "value_axis_choice":
        axis = payload["axis"]
        if axis not in VALUE_AXES:
            raise PayloadError("axis must be survival, freedom, or belonging")
        name = payload["imprint_name"]
        if not isinstance(name, str) or not name.strip():
            raise PayloadError("imprint_name must be a non-empty string")
        if payload["domain"] not in NAVIGATOR_DOMAINS:
            raise PayloadError("domain must be one of the navigator six")
        points = payload["points"]
        if isinstance(points, bool) or not isinstance(points, int) or not 1 <= points <= 5:
            raise PayloadError("points must be an integer within 1..5")
        if payload["source"] != "planetx":
            raise PayloadError("source must be 'planetx'")
        generated = payload.get("generated_at")
        if generated is not None and not isinstance(generated, str):
            raise PayloadError("generated_at must be a string")
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
