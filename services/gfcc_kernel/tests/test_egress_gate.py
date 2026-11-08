"""跨区明文出站：没配目的地区时本区照常下发；配了就先过 ethos 流向门。"""

import uuid

from fastapi.testclient import TestClient

from gfcc_kernel.app import app
from gfcc_kernel.signal import build_hmac_signature, email_to_user_id_hash

client = TestClient(app)
SECRET = "test-signal-secret"
HASH_A = email_to_user_id_hash("alice@example.com")
HASH_B = email_to_user_id_hash("bob@example.com")


def _post(monkeypatch):
    monkeypatch.setenv("SIGNAL_INGEST_SECRET", SECRET)
    body = {
        "signal_type": "consensus_match",
        "user_id_hash": HASH_A,
        "nonce": uuid.uuid4().hex,
        "payload": {
            "match_score": 0.92,
            "shared_tags": ["python"],
            "peer_id_hash": HASH_B,
            "source": "demoppi",
        },
    }
    raw = __import__("json").dumps(body).encode()
    return client.post(
        "/v1/signal-ingest",
        content=raw,
        headers={"X-Signature": build_hmac_signature(SECRET, raw)},
    )


def test_same_region_when_dest_unset_still_stores(monkeypatch):
    monkeypatch.delenv("GFCC_EGRESS_DEST_REGION", raising=False)
    called = {}
    monkeypatch.setattr(
        "gfcc_kernel.app._dispatch_signal",
        lambda *args, **kwargs: called.setdefault("n", 0) or called.__setitem__("n", 1),
    )
    response = _post(monkeypatch)
    assert response.status_code == 200
    assert response.json()["status"] == "stored"
    assert "egress" not in response.json()
    assert called["n"] == 1


def test_l0_cn_to_eu_blocks_plaintext_dispatch(monkeypatch):
    monkeypatch.setenv("GFCC_SOURCE_REGION", "CN")
    monkeypatch.setenv("GFCC_EGRESS_DEST_REGION", "EU")
    monkeypatch.setitem(
        __import__("gfcc_kernel.egress", fromlist=["SIGNAL_PRIVACY_TIER"]).SIGNAL_PRIVACY_TIER,
        "consensus_match",
        "L0_PII",
    )
    called = {"n": 0}
    monkeypatch.setattr(
        "gfcc_kernel.app._dispatch_signal",
        lambda *args, **kwargs: called.__setitem__("n", called["n"] + 1),
    )
    response = _post(monkeypatch)
    assert response.status_code == 200
    assert response.json()["status"] == "stored"
    assert response.json()["egress"] == "blocked"
    assert response.json()["verdict"] == "deny_plaintext"
    assert called["n"] == 0
