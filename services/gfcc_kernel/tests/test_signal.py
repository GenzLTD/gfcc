"""Step3 W1-W3 信号摄入测试 —— POST /v1/signal-ingest。

验收标准（docs/Phase2_Step3_Windows_开工清单.md W1/W3）：
- 合法信封 → 200 stored（含 signal_id / port）
- 缺字段 / 多余字段 → 422 invalid_envelope
- 验签失败 → 401 invalid_signature
- SIGNAL_INGEST_SECRET 留空 = dev 免签 + WARNING
- 幂等：同 (signal_type, user_id_hash, nonce) 重放 → duplicate + 相同 signal_id
- W3：consensus_match→consensus；personality_beacon→identity（端口 stub 收到调用记录）
- W2：signal_log 经 store 槽落库，SQLite 重启不丢

与 test_app.py 同款同步 TestClient 写法（绕开 pytest-asyncio 配置）。
"""

import hashlib
import json
import logging
import uuid

# 装配隔离（stub store / stub llm）统一由 tests/conftest.py 在收集阶段完成
from fastapi.testclient import TestClient

from gfcc_kernel import app as app_module
from gfcc_kernel.app import app
from gfcc_kernel.signal import build_hmac_signature
from gfcc_kernel.slots import SQLiteStore, StubStore

client = TestClient(app)

SECRET = "test-signal-secret"
HASH_A = hashlib.sha256("alice@example.com".encode()).hexdigest()
HASH_B = hashlib.sha256("bob@example.com".encode()).hexdigest()


def _envelope(**over):
    body = {
        "signal_type": "consensus_match",
        "user_id_hash": HASH_A,
        "nonce": uuid.uuid4().hex,  # 每次随机，保证幂等测试可控、多次运行不撞
        "payload": {
            "match_score": 0.92,
            "shared_tags": ["python", "内核"],
            "peer_id_hash": HASH_B,
            "source": "demoppi",
        },
    }
    body.update(over)
    return body


def _post(body: dict, secret: str = SECRET):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"X-Signature": build_hmac_signature(secret, raw)} if secret else {}
    return client.post("/v1/signal-ingest", content=raw, headers=headers)


class TestV1SignalIngest:
    def test_valid_consensus_match_stored(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        r = _post(_envelope(nonce="s1" * 8))
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "stored"
        assert data["port"] == "consensus"
        assert len(data["signal_id"]) == 32  # uuid4 hex

    def test_personality_beacon_routes_identity(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        body = {
            "signal_type": "personality_beacon",
            "user_id_hash": HASH_A,
            "nonce": "s2" * 8,
            "payload": {"personality_type": "INTJ", "source": "planetx"},
        }
        r = _post(body)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "stored"
        assert data["port"] == "identity"

    def test_duplicate_nonce_same_signal_id(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        body = _envelope(nonce=uuid.uuid4().hex)  # 固定 nonce 重放同一信封
        r1 = _post(body)
        r2 = _post(body)
        assert r1.json()["status"] == "stored"
        assert r2.status_code == 200
        assert r2.json()["status"] == "duplicate"
        assert r2.json()["signal_id"] == r1.json()["signal_id"]

    def test_signature_mismatch_401(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        raw = json.dumps(_envelope(nonce="s4" * 8), ensure_ascii=False).encode("utf-8")
        r = client.post("/v1/signal-ingest", content=raw,
                        headers={"X-Signature": "0" * 64})
        assert r.status_code == 401
        assert r.json()["code"] == "invalid_signature"

    def test_missing_signature_401(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        r = _post(_envelope(nonce="s5" * 8), secret="")  # 不传 X-Signature
        assert r.status_code == 401
        assert r.json()["code"] == "invalid_signature"

    def test_dev_noauth_warning(self, monkeypatch, caplog):
        monkeypatch.delenv("SIGNAL_INGEST_SECRET", raising=False)
        with caplog.at_level(logging.WARNING, logger="gfcc_kernel"):
            r = _post(_envelope(nonce="s6" * 8), secret="")
        assert r.status_code == 200
        assert r.json()["status"] == "stored"
        assert any("SIGNAL_INGEST_SECRET unset" in m for m in caplog.messages)

    def test_missing_field_422(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        body = _envelope(nonce="s7" * 8)
        del body["nonce"]
        r = _post(body)
        assert r.status_code == 422
        assert r.json()["code"] == "invalid_envelope"

    def test_extra_field_422(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        r = _post(_envelope(nonce="s8" * 8, extra="x"))
        assert r.status_code == 422
        assert r.json()["code"] == "invalid_envelope"

    def test_bad_user_id_hash_422(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        r = _post(_envelope(nonce="s9" * 8, user_id_hash="not-a-hash"))
        assert r.status_code == 422

    def test_payload_contract_422(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        bad = dict(_envelope()["payload"], match_score=1.5)
        r = _post(_envelope(nonce="sA" * 8, payload=bad))
        assert r.status_code == 422
        assert r.json()["code"] == "invalid_envelope"

    def test_unknown_signal_type_422(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        r = _post(_envelope(nonce="sB" * 8, signal_type="hacked_signal"))
        assert r.status_code == 422

    def test_payload_unlisted_field_422(self, monkeypatch):
        """G1 冻结后严格化：payload 未列字段一律拒绝（Schema additionalProperties=false）。"""
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        bad = dict(_envelope()["payload"], hidden_backdoor="x")
        r = _post(_envelope(nonce="sE" * 8, payload=bad))
        assert r.status_code == 422
        assert r.json()["code"] == "invalid_envelope"

    def test_beacon_traits_strict_422(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        body = {
            "signal_type": "personality_beacon",
            "user_id_hash": HASH_A,
            "nonce": "sF" * 8,
            "payload": {
                "personality_type": "INTJ",
                "traits": [{"name": "creative", "score": 0.8, "extra": 1}],  # 元素多余字段
                "source": "planetx",
            },
        }
        r = _post(body)
        assert r.status_code == 422
        assert r.json()["code"] == "invalid_envelope"

    def test_beacon_assessment_score_type_422(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        body = {
            "signal_type": "personality_beacon",
            "user_id_hash": HASH_A,
            "nonce": "sG" * 8,
            "payload": {"personality_type": "INTJ", "assessment_score": "high", "source": "planetx"},
        }
        r = _post(body)
        assert r.status_code == 422

    # ------------------------------------------------------------------ #
    # W3：端口 stub 收到调用记录
    # ------------------------------------------------------------------ #

    def test_consensus_port_receives_evidence(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        consensus = app_module._registry.get("consensus")
        before = len(consensus.list_signal_evidence())
        r = _post(_envelope(nonce="sC" * 8))
        assert r.status_code == 200
        evidence = consensus.list_signal_evidence()
        assert len(evidence) == before + 1
        assert evidence[-1]["signal_id"] == r.json()["signal_id"]
        assert evidence[-1]["payload"]["match_score"] == 0.92

    def test_identity_port_receives_beacon_and_trace(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
        identity = app_module._registry.get("identity")
        before = len(identity.list_signal_beacons())
        body = {
            "signal_type": "personality_beacon",
            "user_id_hash": HASH_B,
            "nonce": "sD" * 8,
            "payload": {"personality_type": "ENTP", "source": "planetx"},
        }
        r = _post(body)
        assert r.status_code == 200
        beacons = identity.list_signal_beacons()
        assert len(beacons) == before + 1
        assert beacons[-1]["signal_id"] == r.json()["signal_id"]
        # 画像 mint 了 auxiliary trace（mbti 来源，非 evidence）
        profile = identity.get_profile(HASH_B).data["profile"]
        assert any(t["label"] == "personality_beacon:ENTP" for t in profile["capability_trace"])


class TestSignalLogStore:
    """W2：signal_log 经 store 槽，双实现语义一致 + SQLite 重启不丢。"""

    def test_stub_idempotent(self):
        s = StubStore()
        r1 = s.record_signal("personality_beacon", HASH_A, "w1" * 8, {"personality_type": "INTJ"})
        r2 = s.record_signal("personality_beacon", HASH_A, "w1" * 8, {"personality_type": "INTJ"})
        assert r1["duplicate"] is False
        assert r2["duplicate"] is True
        assert r2["signal_id"] == r1["signal_id"]
        assert len(s.query_signals()) == 1

    def test_sqlite_persist_across_reopen(self, tmp_path):
        db = tmp_path / "signals.db"
        s1 = SQLiteStore(db_path=str(db))
        rec = s1.record_signal("consensus_match", HASH_A, "w2" * 8,
                               {"match_score": 0.9, "shared_tags": ["x"],
                                "peer_id_hash": HASH_B, "source": "demoppi"})
        assert s1.get_signal(rec["signal_id"]) is not None
        s1.close()

        s2 = SQLiteStore(db_path=str(db))  # 重启
        got = s2.get_signal(rec["signal_id"])
        assert got is not None
        assert got["signal_type"] == "consensus_match"
        assert got["payload"]["match_score"] == 0.9
        assert len(s2.query_signals()) == 1
        s2.close()

    def test_sqlite_idempotent(self, tmp_path):
        s = SQLiteStore(db_path=str(tmp_path / "s.db"))
        r1 = s.record_signal("consensus_match", HASH_A, "w3" * 8, {"match_score": 0.8})
        r2 = s.record_signal("consensus_match", HASH_A, "w3" * 8, {"match_score": 0.8})
        assert r1["duplicate"] is False
        assert r2["duplicate"] is True
        assert r2["signal_id"] == r1["signal_id"]
        assert len(s.query_signals()) == 1
        s.close()
