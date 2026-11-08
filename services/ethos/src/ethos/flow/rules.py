"""随库发布的流向规则，语义对齐 lab-genz-brain-m2 config/policy_rules.yaml 1.1。

按序首个匹配生效。最后一条是显式兜底 allow。evaluate 在一张规则都没
匹配到时返回 deny_plaintext，不把「没写进规则」当成放行。
"""

from __future__ import annotations

RULES: tuple[dict[str, str | bool], ...] = (
    {"privacy_tier": "*", "source_region": "*", "dest_region": "*", "same_region": True, "verdict": "allow"},
    {"privacy_tier": "*", "source_region": "*", "dest_region": "OTHER", "verdict": "allow"},
    {"privacy_tier": "L0_PII", "source_region": "OTHER", "dest_region": "*", "verdict": "redact_or_aggregate"},
    {"privacy_tier": "L0_PII", "source_region": "CN", "dest_region": "EU", "verdict": "deny_plaintext"},
    {"privacy_tier": "L0_PII", "source_region": "EU", "dest_region": "CN", "verdict": "deny_plaintext"},
    {"privacy_tier": "L0_PII", "source_region": "CN", "dest_region": "SG", "verdict": "deny_plaintext"},
    {"privacy_tier": "L0_PII", "source_region": "SG", "dest_region": "CN", "verdict": "deny_plaintext"},
    {"privacy_tier": "L0_PII", "source_region": "EU", "dest_region": "SG", "verdict": "deny_plaintext"},
    {"privacy_tier": "L0_PII", "source_region": "SG", "dest_region": "EU", "verdict": "deny_plaintext"},
    {"privacy_tier": "L1", "source_region": "CN", "dest_region": "EU", "verdict": "redact_or_aggregate"},
    {"privacy_tier": "L1", "source_region": "EU", "dest_region": "CN", "verdict": "redact_or_aggregate"},
    {"privacy_tier": "L2", "source_region": "CN", "dest_region": "EU", "verdict": "redact_or_aggregate"},
    {"privacy_tier": "L2", "source_region": "EU", "dest_region": "CN", "verdict": "redact_or_aggregate"},
    {"privacy_tier": "*", "source_region": "*", "dest_region": "*", "verdict": "allow"},
)
