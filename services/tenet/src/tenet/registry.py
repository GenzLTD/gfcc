"""可插拔注册表：Protocol + 按名注册实现，全库统一"接口即插拔"。

用法：
    registry = Registry("tenet.security")
    registry.register("hmac", HmacAuthenticator)   # 类本身是工厂
    registry.register("custom", lambda **kw: MyAuth(**kw))
    auth = registry.create("hmac", secret="...")   # 每次新建
    auth = registry.get("hmac")                    # 单例（缓存）
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Generic, TypeVar

T = TypeVar("T")


class RegistryError(LookupError):
    """注册 / 查找实现时出错。"""


class Registry(Generic[T]):
    """按名称注册实现工厂，按名称创建或获取实例。线程安全。"""

    def __init__(self, label: str = "component") -> None:
        self._label = label
        self._factories: Dict[str, Callable[..., T]] = {}
        self._singletons: Dict[str, T] = {}
        self._lock = threading.RLock()

    def register(self, name: str, factory: Callable[..., T]) -> None:
        """注册实现工厂。同名重复注册抛错，防止隐式覆盖。"""
        with self._lock:
            if name in self._factories:
                raise RegistryError(f"{self._label} '{name}' 已注册")
            self._factories[name] = factory

    def create(self, name: str, **kwargs: Any) -> T:
        """创建新实例（每次调用新建，不入缓存）。"""
        with self._lock:
            factory = self._factories.get(name)
        if factory is None:
            raise RegistryError(f"未注册的{self._label}: {name!r}")
        return factory(**kwargs)

    def get(self, name: str, **kwargs: Any) -> T:
        """获取单例实例（首次创建后缓存复用）。"""
        with self._lock:
            cached = self._singletons.get(name)
        if cached is not None:
            return cached
        instance = self.create(name, **kwargs)
        with self._lock:
            self._singletons.setdefault(name, instance)
        return instance

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._factories)

    def clear_singletons(self) -> None:
        """清空单例缓存（配置变更后调用）。"""
        with self._lock:
            self._singletons.clear()
