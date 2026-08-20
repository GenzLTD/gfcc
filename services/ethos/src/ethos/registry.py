"""可插拔后端注册中心：ethos 的"Protocol + Registry"接线层。

与 tenet 的差异：tenet 的 registry 是模块级单例 dict；
ethos 允许按需创建独立 registry 实例，便于多租户/多配置并存。
"""

from __future__ import annotations

import threading
from typing import Dict, Generic, Optional, Type, TypeVar, Union

T = TypeVar("T")


class Registry(Generic[T]):
    """按名字注册/获取某种 Protocol 的实现（类或实例均可）。线程安全。"""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: Dict[str, Union[Type[T], T]] = {}
        self._lock = threading.Lock()

    def register(self, name: str, impl: Union[Type[T], T]) -> None:
        with self._lock:
            self._items[name.lower()] = impl

    def get(self, name: str) -> Optional[Union[Type[T], T]]:
        with self._lock:
            return self._items.get(name.lower())

    def get_or_raise(self, name: str) -> Union[Type[T], T]:
        impl = self.get(name)
        if impl is None:
            raise KeyError(
                f"{self._kind} 后端 '{name}' 未注册。可用：{sorted(self._items)}"
            )
        return impl

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._items)

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def __repr__(self) -> str:  # pragma: no cover
        return f"Registry[{self._kind}]({self.names()})"


# --------------------------------------------------------------------------- #
# 默认全局注册表（多数场景直接复用；特殊场景自行 new Registry）
# --------------------------------------------------------------------------- #

_security_registry: Optional[Registry] = None
_resolver_registry: Optional[Registry] = None
_lock = threading.Lock()


def get_registry(kind: str) -> Registry:
    """获取全局共享 registry。kind: 'security' | 'resolver'。"""
    global _security_registry, _resolver_registry
    with _lock:
        if kind == "security":
            if _security_registry is None:
                _security_registry = Registry(kind)
            return _security_registry
        if kind == "resolver":
            if _resolver_registry is None:
                _resolver_registry = Registry(kind)
            return _resolver_registry
        raise KeyError(f"未知 registry kind: {kind}")
