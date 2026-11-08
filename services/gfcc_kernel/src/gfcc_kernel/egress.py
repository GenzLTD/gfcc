"""明文跨区出站门。没装流向模块、地区没配全、或结论不是 allow，都不发出明文。"""

from __future__ import annotations


class EgressDenied(Exception):
    def __init__(self, verdict: str, reason: str) -> None:
        self.verdict = verdict
        self.reason = reason
        super().__init__(reason)


SIGNAL_PRIVACY_TIER = {
    "consensus_match": "L2",
    "personality_beacon": "L2",
}


def guard_plaintext_egress(privacy_tier: str, source_region: str, dest_region: str) -> str:
    try:
        from ethos.flow import evaluate
    except Exception as exc:  # noqa: BLE001
        raise EgressDenied("deny_plaintext", "flow module unavailable") from exc
    verdict = evaluate(privacy_tier, source_region, dest_region)
    if verdict != "allow":
        raise EgressDenied(verdict, f"plaintext egress blocked: {verdict}")
    return verdict
