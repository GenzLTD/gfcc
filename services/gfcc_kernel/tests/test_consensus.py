"""consensus 状态机测试 —— 对齐 contracts/consensus.v1.json。

覆盖：proposed → (score 带证据) → below_threshold | awaiting_ack → consensus_verified。
红线：无证据不得打分；AI 不能作为 party ack；verified 不可 expire。
"""

import pytest

from gfcc_kernel.ports.consensus import ConsensusAdapter, TERMINAL


def _evidence(by="scorer-1"):
    return [{"by_sub": by, "basis": "社区讨论记录 #42", "at": "2026-08-20T21:00:00"}]


@pytest.fixture()
def adapter():
    return ConsensusAdapter(threshold=85)


@pytest.fixture()
def proposal(adapter):
    r = adapter.propose("circle-1", "下周二晚围坐", ["alice", "bob"], proposer_sub="alice")
    assert r.ok
    return r.id


class TestPropose:
    def test_propose_ok(self, adapter, proposal):
        st = adapter.get_status(proposal)
        assert st.ok
        assert st.data["proposal"]["status"] == "proposed"
        assert st.data["can_complete"] is False

    def test_single_party_rejected(self, adapter):
        r = adapter.propose("circle-1", "议题", ["alice"], proposer_sub="alice")
        assert not r.ok
        assert "at least 2" in r.error

    def test_empty_subject_rejected(self, adapter):
        r = adapter.propose("circle-1", "  ", ["a", "b"], proposer_sub="a")
        assert not r.ok


class TestScore:
    def test_score_without_evidence_rejected(self, adapter, proposal):
        r = adapter.score(proposal, 90.0, evidence=[])
        assert not r.ok
        assert "score_evidence" in r.error

    def test_evidence_missing_fields_rejected(self, adapter, proposal):
        r = adapter.score(proposal, 90.0, evidence=[{"by_sub": "x"}])  # 缺 basis/at
        assert not r.ok

    def test_below_threshold(self, adapter, proposal):
        r = adapter.score(proposal, 50.0, evidence=_evidence())
        assert r.ok
        assert r.data["proposal"]["status"] == "below_threshold"

    def test_pass_threshold_goes_awaiting_ack(self, adapter, proposal):
        r = adapter.score(proposal, 92.0, evidence=_evidence())
        assert r.ok
        assert r.data["proposal"]["status"] == "awaiting_ack"

    def test_score_twice_rejected(self, adapter, proposal):
        assert adapter.score(proposal, 92.0, evidence=_evidence()).ok
        r = adapter.score(proposal, 95.0, evidence=_evidence())
        assert not r.ok  # 已离开 proposed 状态


class TestAcknowledge:
    def test_ai_cannot_ack(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        r = adapter.acknowledge(proposal, "ai-agent", actor_is_ai=True)
        assert not r.ok
        assert "AI cannot" in r.error

    def test_non_party_cannot_ack(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        r = adapter.acknowledge(proposal, "charlie")
        assert not r.ok
        assert "not a party" in r.error

    def test_all_parties_ack_verifies(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        r1 = adapter.acknowledge(proposal, "alice")
        assert r1.ok
        assert r1.data["proposal"]["status"] == "awaiting_ack"  # 部分 ack 仍是 awaiting
        assert r1.data["can_complete"] is False
        r2 = adapter.acknowledge(proposal, "bob")
        assert r2.ok
        assert r2.data["proposal"]["status"] == "consensus_verified"
        assert r2.data["can_complete"] is True

    def test_double_ack_rejected(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        adapter.acknowledge(proposal, "alice")
        r = adapter.acknowledge(proposal, "alice")
        assert not r.ok
        assert "already acked" in r.error

    def test_ack_before_score_rejected(self, adapter, proposal):
        r = adapter.acknowledge(proposal, "alice")
        assert not r.ok  # 未打分不在 awaiting_ack 状态


class TestExpire:
    def test_expire_ok(self, adapter, proposal):
        r = adapter.expire(proposal)
        assert r.ok
        assert r.data["proposal"]["status"] == "expired"

    def test_verified_cannot_expire(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        adapter.acknowledge(proposal, "alice")
        adapter.acknowledge(proposal, "bob")
        r = adapter.expire(proposal)
        assert not r.ok


class TestReject:
    def test_reject_requires_reason(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        r = adapter.reject(proposal, "bob", "")
        assert not r.ok
        assert "reason is required" in r.error

    def test_reject_by_non_party_rejected(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        r = adapter.reject(proposal, "charlie", "旁观不能驳")
        assert not r.ok

    def test_reject_sets_status_and_releases_pending(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        r = adapter.reject(proposal, "bob", "不同意这个表述")
        assert r.ok
        assert r.data["proposal"]["status"] == "rejected"
        pending = [p for p in adapter.list_all() if p["status"] not in TERMINAL]
        assert pending == []
        r2 = adapter.propose("circle-1", "改提一句", ["alice", "bob"], proposer_sub="alice")
        assert r2.ok

    def test_reject_terminal_state_rejected(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        adapter.acknowledge(proposal, "alice")
        adapter.acknowledge(proposal, "bob")
        r = adapter.reject(proposal, "alice", "太晚了")
        assert not r.ok

        p2 = adapter.propose("circle-1", "第二句", ["alice", "bob"], proposer_sub="alice").id
        adapter.score(p2, 92.0, evidence=_evidence())
        assert adapter.expire(p2).ok
        assert not adapter.reject(p2, "alice", "已过期").ok

        p3 = adapter.propose("circle-1", "第三句", ["alice", "bob"], proposer_sub="alice").id
        adapter.score(p3, 92.0, evidence=_evidence())
        assert adapter.withdraw(p3, "alice").ok
        assert not adapter.reject(p3, "bob", "已撤回").ok


class TestWithdraw:
    def test_withdraw_only_proposer(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        r = adapter.withdraw(proposal, "bob")
        assert not r.ok

    def test_withdraw_sets_status_and_releases_pending(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        r = adapter.withdraw(proposal, "alice")
        assert r.ok
        assert r.data["proposal"]["status"] == "withdrawn"
        pending = [p for p in adapter.list_all() if p["status"] not in TERMINAL]
        assert pending == []
        assert adapter.propose("circle-1", "改提一句", ["alice", "bob"], proposer_sub="alice").ok

    def test_withdraw_terminal_state_rejected(self, adapter, proposal):
        adapter.score(proposal, 92.0, evidence=_evidence())
        adapter.acknowledge(proposal, "alice")
        adapter.acknowledge(proposal, "bob")
        r = adapter.withdraw(proposal, "alice")
        assert not r.ok
