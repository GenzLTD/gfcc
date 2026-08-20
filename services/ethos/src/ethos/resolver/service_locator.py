"""服务发现：服务名 → 基础 URL（对应 zervi-rust consul-client 的 Python 版）。

- StaticServiceLocator：静态表 + 环境变量覆盖（默认，零依赖，本地联调）。
- ConsulServiceLocator：Consul 健康服务目录（可选依赖 httpx）。
- TtlCachedLocator：TTL 缓存包装（避免每请求查外部）。

环境变量约定：ETHOS_SERVICES_<NAME> = http://host:port
    例：ETHOS_SERVICES_KNOWLEDGE_API=http://127.0.0.1:8000
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, Mapping, Optional, Protocol


class ServiceLocator(Protocol):
    def locate(self, service_name: str) -> Optional[str]: ...


class StaticServiceLocator:
    """静态表实现：构造 dict ← 环境变量 ETHOS_SERVICES_<NAME>（后者优先）。"""

    def __init__(self, services: Optional[Mapping[str, str]] = None) -> None:
        self._services: dict[str, str] = {k.lower(): v for k, v in (services or {}).items()}
        for key, value in os.environ.items():
            if key.startswith("ETHOS_SERVICES_"):
                name = key[len("ETHOS_SERVICES_"):].lower()
                self._services[name] = value

    def locate(self, service_name: str) -> Optional[str]:
        return self._services.get(service_name.lower())


class ConsulServiceLocator:
    """Consul 服务发现（需安装 httpx：pip install 'ethos[consul]'）。"""

    def __init__(self, consul_url: Optional[str] = None) -> None:
        self._consul_url = consul_url or os.getenv("CONSUL_URL", "http://localhost:8500")

    def locate(self, service_name: str) -> Optional[str]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "ConsulServiceLocator 需要 httpx：pip install 'ethos[consul]'"
            ) from exc
        url = f"{self._consul_url}/v1/health/service/{service_name}?passing=true"
        resp = httpx.get(url, timeout=2.0)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return None
        inst = data[0]["Service"]
        return f"http://{inst['Address']}:{inst['Port']}"


class TtlCachedLocator:
    """TTL 缓存包装器：外部查询结果缓存 N 秒。"""

    def __init__(self, inner: ServiceLocator, ttl_seconds: float = 30.0) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._cache: Dict[str, tuple[float, Optional[str]]] = {}
        self._lock = threading.Lock()

    def locate(self, service_name: str) -> Optional[str]:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(service_name.lower())
            if hit is not None and now - hit[0] < self._ttl:
                return hit[1]
        url = self._inner.locate(service_name)
        with self._lock:
            self._cache[service_name.lower()] = (now, url)
        return url
