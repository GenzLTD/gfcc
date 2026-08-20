"""信封模型测试 —— 对齐 contracts/ask.envelope.v1.json。

覆盖：additionalProperties=false 拒绝多余字段、message 非空、
context 允许扩展键、partial 状态与 receipts 结构、confidence 边界。
"""

import pytest
from pydantic import ValidationError

from gfcc_kernel.envelope import AskContext, AskRequest, AskResponse, AskResult, ReceiptItem


class TestAskRequest:
    def test_minimal_request(self):
        req = AskRequest(message="你好")
        assert req.message == "你好"
        assert req.context.session_id is None

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            AskRequest(message="")

    def test_extra_field_rejected(self):
        # 契约 additionalProperties=false：多余字段必须 422
        with pytest.raises(ValidationError):
            AskRequest(message="hi", backend="tatha")  # type: ignore[call-arg]

    def test_context_extra_keys_allowed(self):
        # 契约 context additionalProperties=true：允许扩展键
        req = AskRequest(message="hi", context={"session_id": "s1", "custom_key": "v"})
        assert req.context.session_id == "s1"
        assert req.context.custom_key == "v"  # type: ignore[attr-defined]

    def test_context_dialog_mode_validated(self):
        with pytest.raises(ValidationError):
            AskRequest(message="hi", context={"dialog_mode": "interview"})


class TestAskResponse:
    def test_partial_status_and_receipts(self):
        resp = AskResponse(
            port="memory",
            status="partial",
            result=AskResult(receipts=[
                ReceiptItem(port="memory", status="ok", id="r1"),
                ReceiptItem(port="consensus", status="pending"),
            ]),
        )
        assert resp.status == "partial"
        assert len(resp.result.receipts) == 2
        assert resp.result.receipts[0].port == "memory"
        assert resp.result.receipts[1].status == "pending"

    def test_receipt_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ReceiptItem(port="memory", status="ok", extra="x")  # type: ignore[call-arg]

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            AskResponse(port="memory", status="ok", confidence=1.5)
