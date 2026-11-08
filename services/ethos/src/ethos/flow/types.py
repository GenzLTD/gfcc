"""流向门的类型。与 ethos.models.Tier（配额档）分开。"""

from __future__ import annotations

from enum import Enum


class PrivacyTier(str, Enum):
    L0_PII = "L0_PII"
    L1 = "L1"
    L2 = "L2"
    PUBLIC = "public"


class DataRegion(str, Enum):
    CN = "CN"
    EU = "EU"
    SG = "SG"
    OTHER = "OTHER"

    @classmethod
    def parse(cls, value: str | None) -> "DataRegion | None":
        if value is None:
            return None
        token = value.strip().upper()
        if token in ("CN", "CN-CN"):
            return cls.CN
        if token in ("EU", "EU-EU", "GDPR"):
            return cls.EU
        if token in ("SG", "SG-SG"):
            return cls.SG
        if token in ("OTHER", "*"):
            return cls.OTHER
        return None


class FlowVerdict(str, Enum):
    ALLOW = "allow"
    LOCALIZE_ONLY = "localize_only"
    REDACT_OR_AGGREGATE = "redact_or_aggregate"
    DENY_PLAINTEXT = "deny_plaintext"
