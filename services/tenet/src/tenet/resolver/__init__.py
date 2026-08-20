"""Tenet Resolver —— 服务发现 + 资源动态定位（跨平台路径层）。

一键装配：
    from tenet.resolver import init_resolver

    ctx = init_resolver(services={"knowledge-api": "http://127.0.0.1:8000"},
                        resources={"vault.json": {"win32": "E:/Data/vault.json",
                                                  "darwin": "/Users/me/Data/vault.json"}})
    ctx["service_locator"].locate("knowledge-api")   # → "http://127.0.0.1:8000"
    ctx["resource_locator"].resolve("vault.json")    # → 当前平台实际路径

路径配置建议放到独立文件（config/resources.json），代码只传逻辑键：
    init_resolver(resources_path=PROJECT_ROOT / "config" / "resources.json")
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Registry
from . import config as config
from .resource_locator import (
    ChainedResourceLocator,
    EnvResourceLocator,
    ResourceLocator,
    StaticResourceLocator,
)
from .service_locator import (
    ConsulServiceLocator,
    ServiceLocator,
    StaticServiceLocator,
    TtlCachedLocator,
)

__all__ = [
    "ServiceLocator",
    "StaticServiceLocator",
    "ConsulServiceLocator",
    "TtlCachedLocator",
    "ResourceLocator",
    "StaticResourceLocator",
    "EnvResourceLocator",
    "ChainedResourceLocator",
    "init_resolver",
]

# 可插拔注册表：发现/定位组件按名切换实现
registry = Registry("tenet.resolver")
registry.register("static", StaticServiceLocator)
registry.register("consul", ConsulServiceLocator)
registry.register("resource", StaticResourceLocator)
registry.register("env", EnvResourceLocator)


def init_resolver(
    *,
    services: dict[str, str] | None = None,
    resources: dict[str, object] | None = None,
    resources_path: str | Path | None = None,
    consul: bool = False,
    ttl_seconds: float = 30.0,
) -> dict:
    """一键装配 resolver。

    consul=True 时服务发现走 Consul（需 httpx）；默认静态表 + 环境变量。
    资源定位为「配置文件 + 代码内联 + 环境变量」逐级合并（内联覆盖文件）。

    resources_path：资源映射配置文件（JSON/TOML），路径配置从代码剥离后
    收敛到独立文件，换平台只改配置、不动代码。
    """
    if consul:
        service_locator: ServiceLocator = TtlCachedLocator(
            ConsulServiceLocator(), ttl_seconds=ttl_seconds
        )
    else:
        service_locator = StaticServiceLocator(services)

    merged_resources = _merge_resources(resources, resources_path)
    resource_locator: ResourceLocator = ChainedResourceLocator(
        StaticResourceLocator(merged_resources), EnvResourceLocator()
    )
    return {"service_locator": service_locator, "resource_locator": resource_locator}


def _merge_resources(
    inline: dict[str, object] | None,
    path: str | Path | None,
) -> dict[str, object]:
    """合并资源映射：配置文件为基底，代码内联覆盖（内联优先级最高）。"""
    merged: dict[str, object] = {}
    if path is not None:
        from .config import load_resource_config

        merged.update(load_resource_config(path))
    if inline:
        merged.update(inline)
    return merged
