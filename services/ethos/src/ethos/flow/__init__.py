"""跨境流向门。配额档 free/basic/pro/admin 不在这里。

四种结论：allow、localize_only、redact_or_aggregate、deny_plaintext。
没有匹配规则、档位或地区无法识别时，返回 deny_plaintext。
"""

from __future__ import annotations

from .evaluate import evaluate, load_rules
from .types import DataRegion, FlowVerdict, PrivacyTier

__all__ = [
    "DataRegion",
    "FlowVerdict",
    "PrivacyTier",
    "evaluate",
    "load_rules",
]
