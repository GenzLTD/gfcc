"""价值轴门禁：匹配侧写不了，读两次无副作用，未列字段在端口即拒绝。"""

import base64
import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from gfcc_kernel.app import app
from gfcc_kernel.ports.identity import IdentityAdapter
from gfcc_kernel.signal import email_to_user_id_hash

client = TestClient(app)
ETHOS = "test-ethos-secret"
USER = email_to_user_id_hash("axes-gate@example.com")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _token(caller: str, permissions: list[str]) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({
        "sub": caller,
        "caller": caller,
        "permissions": permissions,
        "exp": int(time.time()) + 600,
    }).encode())
    sig = hmac.new(ETHOS.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(sig)}"


def _call(op: str, token: str, payload: dict | None = None):
    body = {"op": op, "user_id_hash": USER}
    if payload is not None:
        body["payload"] = payload
    return client.post(
        "/v1/identity/value-axes",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_stub_auth_does_not_count_as_read_only(monkeypatch):
    monkeypatch.setenv("ETHOS_AUTH_SECRET", "")
    response = _call("apply", "anything", {"axis": "freedom", "points": 1})
    assert response.status_code == 503
    assert response.json()["code"] == "auth_unconfigured"


def test_job_match_cannot_write_and_read_is_stable(monkeypatch):
    monkeypatch.setenv("ETHOS_AUTH_SECRET", ETHOS)
    from gfcc_kernel import app as app_module
    adapter = app_module._registry.get("identity")
    adapter.ingest_signal(
        "seed-axis",
        USER,
        {
            "axis": "freedom",
            "imprint_name": "尊严",
            "domain": "职业域",
            "points": 3,
            "source": "planetx",
        },
        signal_type="value_axis_choice",
    )
    reader = _token("job_match", ["identity.value_axes.read"])
    first = _call("read", reader)
    second = _call("read", reader)
    assert first.status_code == 200
    assert first.json()["value_axes"] == {"survival": 0, "freedom": 3, "belonging": 0}
    assert second.json() == first.json()

    denied = _call(
        "apply",
        reader,
        {"axis": "freedom", "points": 1, "imprint_name": "尊严", "domain": "职业域", "source": "planetx"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "identity.value_axes.write"
    assert _call("read", reader).json()["value_axes"]["freedom"] == 3

    forged = _token("job_match", ["identity.value_axes.write", "*"])
    still = _call("apply", forged, {"axis": "freedom", "points": 1, "source": "planetx"})
    assert still.status_code == 403

    ladder = _token("participant", ["identity.write"])
    assert _call("apply", ladder, {"axis": "freedom", "points": 1, "source": "planetx"}).status_code == 403

    writer = _token("planetx", ["identity.value_axes.read", "identity.value_axes.write"])
    applied = _call(
        "apply",
        writer,
        {
            "axis": "freedom",
            "imprint_name": "尊严",
            "domain": "职业域",
            "points": 1,
            "source": "planetx",
        },
    )
    assert applied.status_code == 200
    assert applied.json()["value_axes"]["freedom"] == 4


def test_port_rejects_renamed_score_field():
    adapter = IdentityAdapter()
    result = adapter.ingest_signal(
        "renamed",
        USER,
        {
            "axis": "survival",
            "imprint_name": "务实",
            "domain": "职业域",
            "points": 2,
            "source": "planetx",
            "bonus_match": 9,
        },
        signal_type="value_axis_choice",
    )
    assert result.ok is False
    assert "bonus_match" in result.error
    assert adapter.read_value_axes(USER) is None
