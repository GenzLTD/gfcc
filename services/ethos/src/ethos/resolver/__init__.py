"""ethos.resolver：服务发现 + 资源定位（跨平台，消灭盘符硬编码）。

装配入口：init_resolver(...) → ResolverProvider（组合 locator + service locator）。

用法（与 tenet.init_resolver 对齐，前缀换 ETHOS_）:

    from ethos.resolver import init_resolver
    rsl = init_resolver("config/resources.json")
    rsl.path("poetry_corpus")            # → 绝对路径，跨平台
    rsl.service("knowledge_api")         # → http://127.0.0.1:8000
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from .. import registry as _registry
from .config import ResourceConfig
from .resource_locator import ResourceLocator
from .service_locator import (
    ConsulServiceLocator,
    ServiceLocator,
    StaticServiceLocator,
    TtlCachedLocator,
)

__all__ = [
    "init_resolver",
    "ResolverProvider",
    "ResourceConfig",
    "ResourceLocator",
    "StaticServiceLocator",
    "ConsulServiceLocator",
    "TtlCachedLocator",
]


class ResolverProvider:
    """组合门面：资源路径定位 + 服务 URL 定位。"""

    def __init__(self, resources: ResourceLocator, services: ServiceLocator) -> None:
        self._resources = resources
        self._services = services

    # -- 资源 ------------------------------------------------------------- #

    def path(self, name: str, default: str = "") -> str:
        return self._resources.locate(name, default)

    def resource_paths(self) -> dict[str, str]:
        return self._resources.paths()

    def override(self, name: str, value: str) -> None:
        self._resources.override(name, value)

    # -- 服务 ------------------------------------------------------------- #

    def service(self, name: str) -> Optional[str]:
        return self._services.locate(name)

    @property
    def services(self) -> ServiceLocator:
        return self._services


def init_resolver(
    config_path: Optional[str] = None,
    config_data: Optional[Mapping[str, Any]] = None,
    services: Optional[Mapping[str, str]] = None,
    use_consul: bool = False,
    consul_url: Optional[str] = None,
    ttl_seconds: float = 30.0,
) -> ResolverProvider:
    """装配 ethos.resolver。

    参数：
    - config_path: resources.json 路径（None → 环境变量 ETHOS_RESOURCES 或 ./resources.json）。
    - config_data: 直接传配置 dict（与 config_path 二选一）。
    - services: 静态服务表 {"name": "http://..."}。
    - use_consul: True → 用 Consul 服务发现（需 httpx）。
    - consul_url: Consul 地址（默认 CONSUL_URL 环境变量）。
    - ttl_seconds: 服务发现结果缓存秒数。

    返回：ResolverProvider。
    """
    # 1) 资源定位
    if config_data is not None:
        rconfig = ResourceConfig.from_dict(config_data)
    else:
        path = config_path or os.getenv("ETHOS_RESOURCES") or "resources.json"
        rconfig = ResourceConfig.load(path)
    resources = ResourceLocator(rconfig)

    # 2) 服务发现（services 未显式传入时，从配置的 services 段加载）
    if services is None:
        services = rconfig.services()
    if use_consul:
        inner: ServiceLocator = ConsulServiceLocator(consul_url)
    else:
        inner = StaticServiceLocator(services)
    service_locator: ServiceLocator = TtlCachedLocator(inner, ttl_seconds=ttl_seconds)

    provider = ResolverProvider(resources, service_locator)

    _registry.get_registry("resolver").register("default", provider)
    return provider
