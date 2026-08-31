"""信封第一场 v2 槽测试：B2 consensus 打分/ack 全链路 + B3 attestor 解析/fulfill mint。

不依赖 LLM（llm=None，走关键词/port_hint 确定性路径）；同一 registry 共享圈数据。
"""

from gfcc_kernel.dispatcher import parse_then_dispatch
from gfcc_kernel.envelope import AskRequest
from gfcc_kernel.registry import PortRegistry


class _FakePolicy:
    def __init__(self, sub: str = "tester-a") -> None:
        self.sub = sub
        self.ctx = None


class _Base:
    def _ctx(self, reg, sub: str = "tester-a"):
        return reg.build_context(
            session_id="s-test", circle_id=None,
            dialog_mode="collaboration", policy=_FakePolicy(sub), llm=None,
        )

    def _create_and_seat(self, reg) -> str:
        """建圈 + b/c 入座，返回 circle_id。"""
        ctx = self._ctx(reg, "tester-a")
        r = parse_then_dispatch(
            AskRequest(message="创建围坐圈 第一场", context={"port_hint": "circle"}), ctx)
        assert r.status == "ok"
        circle_id = r.result.receipts[0].id
        for sub in ("tester-b", "tester-c"):
            ctx = self._ctx(reg, sub)
            rr = parse_then_dispatch(AskRequest(
                message="加入围坐圈",
                context={"port_hint": "circle", "circle_id": circle_id}), ctx)
            assert rr.status == "ok"
        return circle_id


# --------------------------------------------------------------------------- #
# B2 consensus：parties 来自圈内真人 + score → awaiting_ack → 全员 ack → verified
# --------------------------------------------------------------------------- #

class TestConsensusEnvelopeSlots(_Base):
    def test_propose_parties_from_circle_members(self):
        reg = PortRegistry()
        circle_id = self._create_and_seat(reg)
        ctx = self._ctx(reg, "tester-a")
        r = parse_then_dispatch(AskRequest(
            message="提议：本场结论为完成三判据验证",
            context={"port_hint": "consensus", "circle_id": circle_id}), ctx)
        assert r.status == "ok"
        props = reg.get("consensus").list_all()
        assert props and props[-1]["status"] == "proposed"
        assert props[-1]["parties"] == ["tester-a", "tester-b", "tester-c"]

    def test_propose_requires_two_seated(self):
        """未入座两人 → 拒绝（parties 不足），不再用假人兜底。"""
        reg = PortRegistry()
        ctx = self._ctx(reg, "tester-a")
        r = parse_then_dispatch(AskRequest(
            message="创建围坐圈 孤圈", context={"port_hint": "circle"}), ctx)
        circle_id = r.result.receipts[0].id
        r = parse_then_dispatch(AskRequest(
            message="提议：只有我一人的结论",
            context={"port_hint": "consensus", "circle_id": circle_id}), ctx)
        assert r.status == "error"
        assert "parties required" in r.suggestions[0]

    def test_score_then_ack_then_verified(self):
        reg = PortRegistry()
        circle_id = self._create_and_seat(reg)
        ctx = self._ctx(reg, "tester-a")
        r = parse_then_dispatch(AskRequest(
            message="提议：第一场完成三判据验证",
            context={"port_hint": "consensus", "circle_id": circle_id}), ctx)
        pid = reg.get("consensus").list_all()[-1]["id"]

        # 打分 90 → awaiting_ack（score_evidence 由主持人 sub 落）
        r = parse_then_dispatch(AskRequest(
            message=f"打分 {pid} 90 全员认可本场结论",
            context={"port_hint": "consensus", "circle_id": circle_id}), ctx)
        assert r.status == "ok"
        prop = reg.get("consensus").list_all()[-1]
        assert prop["status"] == "awaiting_ack"
        assert prop["score"] == 90.0
        assert prop["score_evidence"][0]["by_sub"] == "tester-a"

        # 3 人各自 ack → consensus_verified（契约：全部本人 ack）
        for sub in ("tester-a", "tester-b", "tester-c"):
            ctx = self._ctx(reg, sub)
            rr = parse_then_dispatch(AskRequest(
                message=f"确认 {pid}",
                context={"port_hint": "consensus", "circle_id": circle_id}), ctx)
            assert rr.status == "ok", rr.suggestions
        prop = reg.get("consensus").list_all()[-1]
        assert prop["status"] == "consensus_verified"
        assert {a["sub"] for a in prop["acks"]} == {"tester-a", "tester-b", "tester-c"}

    def test_score_below_threshold_no_ack_phase(self):
        reg = PortRegistry()
        circle_id = self._create_and_seat(reg)
        ctx = self._ctx(reg, "tester-a")
        parse_then_dispatch(AskRequest(
            message="提议：该结论待定",
            context={"port_hint": "consensus", "circle_id": circle_id}), ctx)
        pid = reg.get("consensus").list_all()[-1]["id"]
        r = parse_then_dispatch(AskRequest(
            message=f"打分 {pid} 50 分歧较大",
            context={"port_hint": "consensus", "circle_id": circle_id}), ctx)
        assert r.status == "ok"
        prop = reg.get("consensus").list_all()[-1]
        assert prop["status"] == "below_threshold"


# --------------------------------------------------------------------------- #
# B3 contribution：attestor=本人、subject=他人；fulfill mint capability_trace
# --------------------------------------------------------------------------- #

class TestContributionEnvelopeSlots(_Base):
    def test_attest_subject_other_attestor_self(self):
        reg = PortRegistry()
        circle_id = self._create_and_seat(reg)
        ctx = self._ctx(reg, "tester-b")
        r = parse_then_dispatch(AskRequest(
            message="认定 tester-a 完成了 整理会议纪要",
            context={"port_hint": "contribution", "circle_id": circle_id}), ctx)
        assert r.status == "ok"
        rec = reg.get("contribution").list_all()[-1]
        assert rec["subject_sub"] == "tester-a"
        assert rec["attestor_sub"] == "tester-b"
        assert rec["status"] == "attested"

    def test_attest_self_denied(self):
        """自我认定是唯一证据 → 拒绝（契约红线）。"""
        reg = PortRegistry()
        circle_id = self._create_and_seat(reg)
        ctx = self._ctx(reg, "tester-a")
        r = parse_then_dispatch(AskRequest(
            message="认定 tester-a 完成了 主持本场",
            context={"port_hint": "contribution", "circle_id": circle_id}), ctx)
        assert r.status == "error"
        assert "cannot attest" in r.suggestions[0]

    def test_attest_requires_subject(self):
        reg = PortRegistry()
        circle_id = self._create_and_seat(reg)
        ctx = self._ctx(reg, "tester-b")
        r = parse_then_dispatch(AskRequest(
            message="认定 完成了 某事",
            context={"port_hint": "contribution", "circle_id": circle_id}), ctx)
        assert r.status == "error"
        assert "subject sub" in r.suggestions[0]

    def test_fulfill_mints_capability_trace(self):
        reg = PortRegistry()
        circle_id = self._create_and_seat(reg)
        # b 认 a
        ctx = self._ctx(reg, "tester-b")
        r = parse_then_dispatch(AskRequest(
            message="认定 tester-a 完成了 整理会议纪要",
            context={"port_hint": "contribution", "circle_id": circle_id}), ctx)
        record_id = r.result.receipts[0].id
        # a（steward）兑现 → fulfilled + minted_trace_id
        ctx = self._ctx(reg, "tester-a")
        r = parse_then_dispatch(AskRequest(
            message=f"兑现 {record_id}",
            context={"port_hint": "contribution"}), ctx)
        assert r.status == "ok"
        rec = reg.get("contribution").list_all()[-1]
        assert rec["status"] == "fulfilled"
        assert rec.get("minted_trace_id")
        # identity capability_trace 增长（判据3 兑得现）
        prof = reg.get("identity").get_profile("tester-a")
        assert len(prof.data["profile"]["capability_trace"]) == 1
        tr = prof.data["profile"]["capability_trace"][0]
        assert tr["source_port"] == "contribution"
        assert tr["weight"] == "evidence"

    def test_fulfill_requires_record_id(self):
        reg = PortRegistry()
        ctx = self._ctx(reg, "tester-a")
        r = parse_then_dispatch(AskRequest(
            message="兑现",
            context={"port_hint": "contribution"}), ctx)
        assert r.status == "error"
        assert "record_id required" in r.suggestions[0]
