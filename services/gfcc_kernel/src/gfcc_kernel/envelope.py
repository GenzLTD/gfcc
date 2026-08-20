"""格契信封模型 —— 严格对齐 contracts/ask.envelope.v1.json。

信封不可变；内部实现可替换。additionalProperties=false 的请求体与
response required 字段按契约逐一落实。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PORT = Literal["circle", "identity", "memory", "consensus", "contribution", "unknown"]
DIALOG_MODE = Literal["collaboration", "coach"]


class AskContext(BaseModel):
    """context 契约：additionalProperties=true（允许扩展键）。"""

    model_config = ConfigDict(extra="allow")

    session_id: Optional[str] = None
    circle_id: Optional[str] = None
    dialog_mode: Optional[DIALOG_MODE] = None
    port_hint: Optional[PORT] = None


class AskRequest(BaseModel):
    """请求体：additionalProperties=false（契约强制拒绝多余字段）。"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, description="What the member wants. Caller does not pick a backend path.")
    context: AskContext = Field(default_factory=AskContext)


class ReceiptItem(BaseModel):
    """多端口运行时的分端口状态。"""

    model_config = ConfigDict(extra="forbid")

    port: str
    status: Literal["ok", "pending", "denied", "error"]
    id: Optional[str] = None


class AskResult(BaseModel):
    """result 契约：receipts 数组。"""

    model_config = ConfigDict(extra="forbid")

    receipts: List[ReceiptItem] = Field(default_factory=list)


class AskResponse(BaseModel):
    """响应：required = [port, status, result]。"""

    model_config = ConfigDict(extra="forbid")

    port: str = Field(description="Resolved first-class port or unknown. Not a JobFirst intent name.")
    status: Literal["ok", "pending", "partial", "denied", "error", "unknown"]
    result: AskResult = Field(default_factory=AskResult)
    suggestions: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# --------------------------------------------------------------------------- #
# 端口操作通用返回
# --------------------------------------------------------------------------- #

class PortOpResult(BaseModel):
    """端口操作统一返回：ok + 数据 + 可选操作 id（写操作）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    error: Optional[str] = None
    id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
