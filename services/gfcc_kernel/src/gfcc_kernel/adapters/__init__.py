"""L3 profile.demo 厂商适配器装配面（总装 + 本地组件）。

真源链：
- modes/profile.demo.yaml      —— 模式清单（slots.store=agentmemory_iii, tools_extra）
- contracts/registry.v1.json   —— 适配器语义（optional_adapters）
- docs/ports/README.md §3      —— dispatch 不得 import 实现；只经 registry 绑定

本模块是"装配面"：bind_profile_demo() 在启动装配时把厂商适配器注入 registry；
dispatcher 只经 registry.get_tool()/ctx.store 取用，不 import 本包。

可卸载：不调用 bind_profile_demo（GFCC_MODE != profile.demo）即回默认格契栈。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("gfcc_kernel")


def bind_profile_demo(registry: Any, *, gateway_url: Optional[str] = None,
                      demopeter_url: Optional[str] = None,
                      token: Optional[str] = None) -> Any:
    """profile.demo 装配：store 槽 → agentmemory_iii；注册 knowledge.demopeter 工具。

    返回新 store（调用方需同步 signal-ingest 的 _store 引用）。
    其余 auxiliary 适配器（job_match/poetry/credit/mbti）走 identity 的
    AUXILIARY_SOURCES 白名单（identity.py 已含 job_match/mbti），
    不进一等端口 —— 本阶段不注册独立适配器。
    """
    from .agentmemory_store import AgentMemoryIIIStore
    from .demopeter_knowledge import DemoPeterKnowledge

    am_store = AgentMemoryIIIStore(gateway_url=gateway_url, token=token)
    registry.bind_store(am_store)
    registry.register_tool(
        "knowledge.demopeter",
        DemoPeterKnowledge(base_url=demopeter_url or os.getenv("DEMOPETER_URL", "http://127.0.0.1:5220")),
    )
    logger.info("profile.demo: store -> agentmemory_iii(%s), tools -> [knowledge.demopeter]", am_store._gateway)
    return am_store
