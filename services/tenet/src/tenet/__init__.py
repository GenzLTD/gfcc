"""Tenet —— 跨平台共享 AI 管道内核。

设计原则：
- 纯 Python 库（非服务体），被 Tatha / DemoPeter / agentmemory 等进程内 import。
- Protocol + Registry 可插拔：业务只依赖接口，实现按配置切换。
- 零盘符硬编码：所有路径经 resolver 解析，Windows / macOS / Linux 通用。
- 当前实现模块：security（认证/鉴权/审计）、resolver（服务发现/资源定位）。
"""

from __future__ import annotations

from . import security, resolver
from .registry import Registry, RegistryError

__version__ = "0.1.0"

__all__ = ["Registry", "RegistryError", "security", "resolver", "__version__"]
