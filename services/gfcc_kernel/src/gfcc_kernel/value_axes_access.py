"""价值轴读写门禁。

对齐 contracts/roles.v1.json service_scopes 与 identity.v1.json operations：
- identity.value_axes.write 只属于 planetx / system。
- job_match 只有 identity.value_axes.read。
- identity.write 不包含写价值轴。档位 admin、权限通配也不放行写口。
"""

from __future__ import annotations

from typing import Iterable

VALUE_AXIS_READ = "identity.value_axes.read"
VALUE_AXIS_WRITE = "identity.value_axes.write"

CALLER_SCOPES = {
    "planetx": frozenset({VALUE_AXIS_READ, VALUE_AXIS_WRITE}),
    "system": frozenset({VALUE_AXIS_READ, VALUE_AXIS_WRITE}),
    "job_match": frozenset({VALUE_AXIS_READ}),
}


def decide(caller: str, permissions: Iterable[str], scope: str) -> str:
    """返回 allow 或 deny。未知调用方、阶梯角色、通配权限都不能写价值轴。"""
    allowed = CALLER_SCOPES.get(caller or "")
    if allowed is None or scope not in allowed:
        return "deny"
    held = {str(item) for item in permissions}
    if scope not in held:
        return "deny"
    return "allow"
