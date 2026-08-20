"""审计上报器：把本地审计事件外发到中心（可选，best-effort）。

ethos 定位"本地审计（可选上报）"——上报器只在明确配置时才挂载。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Optional

from ..models import AuditEvent

logger = logging.getLogger("ethos.audit.reporter")


class HttpReporter:
    """HTTP 上报：POST JSON 到中心端点。异步发送（不阻塞业务线程）。"""

    def __init__(self, url: str, timeout: float = 2.0) -> None:
        self._url = url
        self._timeout = timeout
        self._client = None
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    def _post(self, payload: dict) -> None:
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            logger.warning("上报需要 httpx：pip install 'ethos[remote-quota]'（%s）", exc)
            return
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        resp = self._client.post(self._url, json=payload)
        if resp.status_code >= 400:
            logger.warning("审计上报失败: %s %s", resp.status_code, resp.text[:200])

    def report(self, event: AuditEvent) -> None:
        # 异步发送：上报失败绝不影响主流程
        t = threading.Thread(target=self._post, args=(event.to_dict(),), daemon=True)
        with self._lock:
            self._threads = [x for x in self._threads if x.is_alive()][-50:]
            self._threads.append(t)
        t.start()
