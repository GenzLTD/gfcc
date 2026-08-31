"""L3 厂商适配器：memory.agentmemory_iii —— store 槽 → agentmemory 网关。

对齐 contracts/registry.v1.json optional_adapters["memory.agentmemory_iii"]：
"Third-party memory engine behind ctx.store. Unloadable."

设计（接入样例，诚实边界）：
- 本地影子（继承 StubStore）：record 主存 + 可见性强制（actor_sub/circle_id）
  + 过滤函数执行 —— store.query 接收的是 Python 函数，只能本地执行；
- 远程（agentmemory gateway :3210 → 桥 :3220 → mem::*）：语义持久层，
  best-effort 同步（put/supersede 时推一份语义记忆），失败只记 WARNING 不抛；
- 网关不可达（is_available()=False）自动降级纯 stub —— 契约允许 stub 合法、
  空数据合法，且"卸画像 = 默认格契栈仍可启动"。

契约红线不变（继承自 StubStore）：
- supersede observed_by=ai 仍禁止（AI 只能 observe，不能静默改写）；
- get/query 无 circle_id 时必须 actor_sub（按人隔离，防跨人读）。

run: uvicorn gfcc_kernel.app:app 时经 adapters.bind_profile_demo() 装配；
dispatch 不 import 本模块（只经 registry 绑定，docs/ports/README.md §3）。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..slots import StubStore

logger = logging.getLogger("gfcc_kernel")


class AgentMemoryIIIStore(StubStore):
    """store 槽适配器：本地影子 + agentmemory 远程语义持久层（best-effort）。"""

    def __init__(self, gateway_url: Optional[str] = None, token: Optional[str] = None,
                 timeout: float = 5.0) -> None:
        super().__init__()
        self._gateway = (gateway_url or os.getenv("AM_GATEWAY_URL", "http://127.0.0.1:3210")).rstrip("/")
        self._token = token or os.getenv("AM_GATEWAY_TOKEN", "") or None
        self._timeout = timeout
        self._available: Optional[bool] = None
        self._checked_at: float = 0.0
        self._ttl = 5.0

    # ------------------------------------------------------------------ #
    # 探测
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        """探测 gateway /healthz（ethos JWT 豁免路径），5s TTL 缓存。"""
        now = time.monotonic()
        if self._available is not None and (now - self._checked_at) < self._ttl:
            return self._available
        ok = False
        try:
            with urllib.request.urlopen(f"{self._gateway}/healthz", timeout=1.5) as resp:
                ok = resp.status == 200
        except Exception:  # noqa: BLE001
            ok = False
        self._available = ok
        self._checked_at = now
        return ok

    # ------------------------------------------------------------------ #
    # HTTP 传输（集中到 _post，测试可 monkeypatch）
    # ------------------------------------------------------------------ #

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = urllib.request.Request(
            f"{self._gateway}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _remember_remote(self, record: Dict[str, Any]) -> None:
        """把一条 record 作为语义记忆同步到 agentmemory（best-effort，失败不抛）。"""
        if not self.is_available():
            return
        text = record.get("body")
        if not isinstance(text, str) or not text:
            text = json.dumps(
                {k: v for k, v in record.items()
                 if k not in ("id", "library", "actor_sub", "circle_id", "observed_at")},
                ensure_ascii=False,
            )
        payload = {
            "text": text,
            "user": record.get("actor_sub"),
            "tags": [record["library"]] if record.get("library") else [],
        }
        try:
            self._post("/agentmemory/remember", payload)
        except Exception:  # noqa: BLE001
            logger.warning("agentmemory_iii: remember remote failed (best-effort, id=%s)", record.get("id"))

    # ------------------------------------------------------------------ #
    # store 槽接口覆盖：put / supersede 同步远程，其余继承 StubStore 影子
    # ------------------------------------------------------------------ #

    def put(self, record: Dict[str, Any]) -> Dict[str, Any]:
        stored = super().put(record)
        self._remember_remote(stored)
        return stored

    def supersede(self, rid: str, new_body: Dict[str, Any], actor_sub: str,
                  observed_by: str = "human") -> Optional[Dict[str, Any]]:
        """本地影子 supersede（沿用 observed_by=ai 禁令）；远程 best-effort。

        边界：远端 forget 需要 agentmemory 记忆 id（黑盒无 id 映射），接入样例
        只推送新记录语义副本，不删除远端旧记忆 —— 深集成留 L3 后续。
        """
        new_record = super().supersede(rid, new_body, actor_sub, observed_by=observed_by)
        if new_record is not None:
            self._remember_remote(new_record)
        return new_record

    # 语义召回（smart-search）作为增强查询：profile.demo 阶段保持影子过滤为
    # 真源（filter_fn 必须在本地执行），此处不覆盖 query —— 深集成时再加。
