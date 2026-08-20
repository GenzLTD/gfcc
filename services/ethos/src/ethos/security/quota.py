"""配额管理器：默认库内计数，远程后端可插拔。

ethos 定位"库内配额（可插拔远程）"：
- QuotaBackend 协议定义计数语义（check / consume / reset）。
- LocalQuotaBackend：内存 + 可选的 SQLite 持久化，默认实现，零依赖。
- RemoteQuotaBackend：HTTP 后端（可选，需 httpx），对接统一配额服务。
- QuotaManager 是门面：决定用哪个后端，并把"谁/什么资源"组合成计数键。

计数键设计（跨服务避免撞名）：``{tenant}:{user_id}:{resource}``，
其中 tenant 缺省为 "default"。这与 Go 端多租户字段保持一致。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional, Protocol

from ..models import QuotaLimit, QuotaState


# --------------------------------------------------------------------------- #
# 后端协议
# --------------------------------------------------------------------------- #

class QuotaBackend(Protocol):
    """配额后端的统一协议。实现者须保证线程安全。"""

    def check(self, key: str, limit: QuotaLimit) -> QuotaState: ...

    def consume(self, key: str, limit: QuotaLimit, amount: int = 1) -> QuotaState: ...


# --------------------------------------------------------------------------- #
# 本地后端（默认）
# --------------------------------------------------------------------------- #

class LocalQuotaBackend:
    """库内配额：内存计数 + 按日重置。

    persist_path 传入时会把计数写入 JSON 文件（进程重启不丢）；
    每天按窗口(day_window, 默认"自然日")归零。
    """

    def __init__(
        self,
        persist_path: Optional[str] = None,
        day_window: Optional[int] = None,
    ) -> None:
        self._persist_path = persist_path
        self._day_window = day_window  # 自定义窗口秒数；None=自然日
        self._counts: Dict[str, float] = {}
        self._days: Dict[str, int] = {}
        self._lock = threading.Lock()
        if persist_path:
            self._load()

    # -- 内部 ------------------------------------------------------------- #

    def _day_of(self, now: float) -> int:
        if self._day_window:
            return int(now // self._day_window)
        t = time.localtime(now)
        return t.tm_year * 10000 + t.tm_mon * 100 + t.tm_mday

    def _load(self) -> None:
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self._counts = {k: float(v) for k, v in data.get("counts", {}).items()}
            self._days = {k: int(v) for k, v in data.get("days", {}).items()}
        except (OSError, ValueError):
            self._counts, self._days = {}, {}

    def _flush(self) -> None:
        if not self._persist_path:
            return
        try:
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump({"counts": self._counts, "days": self._days}, f)
        except OSError:
            pass  # 持久化失败不阻塞配额逻辑

    # -- 协议实现 ---------------------------------------------------------- #

    def check(self, key: str, limit: QuotaLimit) -> QuotaState:
        now = time.time()
        day = self._day_of(now)
        with self._lock:
            if self._days.get(key) != day:
                self._days[key] = day
                self._counts[key] = 0.0
            used = int(self._counts.get(key, 0.0))
        remaining = max(limit.daily - used, 0) if limit.daily else -1
        ok = True if limit.daily == 0 else remaining > 0
        return QuotaState(
            resource=limit.resource,
            remaining=remaining,
            limit=limit.daily,
            ok=ok,
            message="" if ok else "daily quota exhausted",
        )

    def consume(self, key: str, limit: QuotaLimit, amount: int = 1) -> QuotaState:
        now = time.time()
        day = self._day_of(now)
        with self._lock:
            if self._days.get(key) != day:
                self._days[key] = day
                self._counts[key] = 0.0
            used = int(self._counts.get(key, 0.0))
            if limit.daily and used + amount > limit.daily:
                self._flush()
                return QuotaState(
                    resource=limit.resource,
                    remaining=max(limit.daily - used, 0),
                    limit=limit.daily,
                    ok=False,
                    message="daily quota exhausted",
                )
            self._counts[key] = used + amount
            self._flush()
        remaining = max(limit.daily - (used + amount), 0) if limit.daily else -1
        return QuotaState(
            resource=limit.resource,
            remaining=remaining,
            limit=limit.daily,
            ok=True,
            message="",
        )


# --------------------------------------------------------------------------- #
# 远程后端（可选）
# --------------------------------------------------------------------------- #

class RemoteQuotaBackend:
    """HTTP 远程配额后端：委托给统一认证服务的配额端点。

    需要 httpx。URL 约定：base_url + '/quota'，POST JSON：
        {"key": "...", "resource": "...", "amount": 1, "tenant": "..."}
    响应：{"ok": bool, "remaining": int, "limit": int, "message": str}

    note: 若后端没有该端点（如 404），会抛 QuotaBackendError，
    由调用方决定是降级本地还是拒绝。
    """

    def __init__(self, base_url: str, timeout: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = None  # 惰性创建 httpx.Client

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("RemoteQuotaBackend 需要 httpx：pip install 'ethos[remote-quota]'") from exc
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        resp = self._client.post(f"{self._base_url}/quota", json=payload)
        if resp.status_code == 404:
            raise RuntimeError(f"远程配额端点不存在：{self._base_url}/quota")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("远程配额返回格式非法")
        return data

    def check(self, key: str, limit: QuotaLimit) -> QuotaState:
        return self._call(key, limit, amount=0)

    def consume(self, key: str, limit: QuotaLimit, amount: int = 1) -> QuotaState:
        return self._call(key, limit, amount=amount)

    def _call(self, key: str, limit: QuotaLimit, amount: int) -> QuotaState:
        payload = {
            "key": key,
            "resource": limit.resource,
            "amount": amount,
            "tenant": "default",
        }
        data = self._post(payload)
        return QuotaState(
            resource=limit.resource,
            remaining=int(data.get("remaining", -1)),
            limit=int(data.get("limit", limit.daily)),
            ok=bool(data.get("ok", False)),
            message=str(data.get("message", "")),
        )


# --------------------------------------------------------------------------- #
# 门面：QuotaManager
# --------------------------------------------------------------------------- #

class QuotaManager:
    """配额门面：解析 resource → 上限，路由到选定后端。

    usage:
        qm = QuotaManager(
            limits={"ai:resume_analysis": QuotaLimit("ai:resume_analysis", daily=5)},
            backend=LocalQuotaBackend(),
        )
        qm.check("user-1", "ai:resume_analysis")      # 不计数
        qm.consume("user-1", "ai:resume_analysis")    # 计数并返回最新状态
    """

    def __init__(
        self,
        limits: Optional[Dict[str, QuotaLimit]] = None,
        backend: Optional[QuotaBackend] = None,
    ) -> None:
        self._limits = dict(limits or {})
        self._backend = backend or LocalQuotaBackend()

    def set_limits(self, limits: Dict[str, QuotaLimit]) -> None:
        self._limits.update(limits)

    def limit_for(self, resource: str) -> Optional[QuotaLimit]:
        return self._limits.get(resource)

    def _key(self, user: str, resource: str, tenant: str = "default") -> str:
        return f"{tenant}:{user}:{resource}"

    def check(self, user: str, resource: str, tenant: str = "default") -> QuotaState:
        limit = self._limits.get(resource)
        if limit is None or limit.daily == 0:
            return QuotaState(resource=resource, remaining=-1, limit=0, ok=True)
        return self._backend.check(self._key(user, resource, tenant), limit)

    def consume(self, user: str, resource: str, tenant: str = "default", amount: int = 1) -> QuotaState:
        limit = self._limits.get(resource)
        if limit is None or limit.daily == 0:
            return QuotaState(resource=resource, remaining=-1, limit=0, ok=True)
        return self._backend.consume(self._key(user, resource, tenant), limit, amount)
