"""按规则表给出流向结论。"""

from __future__ import annotations

from typing import Iterable, Mapping

from .rules import RULES
from .types import DataRegion, FlowVerdict, PrivacyTier


def load_rules() -> tuple[dict[str, str | bool], ...]:
    return RULES


def _matches(rule: Mapping[str, str | bool], tier: PrivacyTier, src: DataRegion, dst: DataRegion) -> bool:
    if rule.get("same_region") and src is not dst:
        return False
    if rule["privacy_tier"] != "*" and tier.value != rule["privacy_tier"]:
        return False
    if rule["source_region"] != "*" and src.value != rule["source_region"]:
        return False
    if rule["dest_region"] != "*" and dst.value != rule["dest_region"]:
        return False
    return True


def evaluate(
    privacy_tier: str,
    source_region: str,
    dest_region: str,
    rules: Iterable[Mapping[str, str | bool]] | None = None,
) -> str:
    """返回四种 verdict 之一。档位、地区或规则对不上时是 deny_plaintext。"""
    tier = next((item for item in PrivacyTier if item.value == privacy_tier), None)
    src = DataRegion.parse(source_region)
    dst = DataRegion.parse(dest_region)
    if tier is None or src is None or dst is None:
        return FlowVerdict.DENY_PLAINTEXT.value
    table = RULES if rules is None else tuple(rules)
    for rule in table:
        if _matches(rule, tier, src, dst):
            try:
                return FlowVerdict(str(rule["verdict"])).value
            except ValueError:
                return FlowVerdict.DENY_PLAINTEXT.value
    return FlowVerdict.DENY_PLAINTEXT.value
