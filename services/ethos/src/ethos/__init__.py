"""ethos：跨平台共享 AI 管道内核（tenet 的演进版）。

定位：
- security：纯验证者认证（不签发）+ 库内配额（可插拔远程）+ 本地审计（可选上报）。
- resolver：服务发现 + 资源定位（跨平台，消灭盘符硬编码）。

与 tenet 的差异：
- ethos 是"纯验证者"：不生成令牌，只验签解析身份。
- 配额、审计在库内原生实现（tenet 由各消费方自建）。
- 环境变量前缀统一为 ETHOS_。
"""

from __future__ import annotations

from . import registry, security, resolver
from .registry import Registry

__version__ = "0.1.0"

__all__ = ["registry", "security", "resolver", "Registry", "__version__"]
