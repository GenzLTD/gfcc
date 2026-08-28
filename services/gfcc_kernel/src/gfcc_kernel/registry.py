"""端口注册表 —— 对齐 contracts/registry.v1.json。

默认组合（gfcc.default）：五个一等端口全部 stub，required_in_default_mode=true。
profile.demo 中的厂商服务（demopeter/agentmemory/iii/job_match/poetry/credit/mbti）
在默认模式下为 forbidden_in_default_tools，不注册。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .ports.circle import CircleAdapter
from .ports.consensus import ConsensusAdapter
from .ports.contribution import ContributionAdapter
from .ports.identity import IdentityAdapter
from .ports.memory import MemoryAdapter
from .slots import SessionStore, StubStore

FIRST_CLASS_PORTS = ["circle", "identity", "memory", "consensus", "contribution"]

# profile.demo 才启用的厂商适配器（默认模式禁止）
FORBIDDEN_IN_DEFAULT_TOOLS = ["demopeter", "agentmemory", "iii", "job_match", "poetry", "credit", "mbti"]


@dataclass
class KernelContext:
    """内核上下文：五槽装配 + 请求级元数据。"""

    session_id: Optional[str] = None
    circle_id: Optional[str] = None
    dialog_mode: str = "collaboration"
    # 五槽
    llm: Any = None
    tools: Dict[str, Any] = field(default_factory=dict)
    session: Optional[SessionStore] = None
    policy: Any = None
    store: Optional[StubStore] = None


class PortRegistry:
    """注册表：端口名 → 适配器。加能力 = 注册适配器，不增长 intent 表。"""

    def __init__(self, threshold: int = 85, store: Optional[Any] = None, flow: Optional[Any] = None) -> None:
        self._store = store or StubStore()
        self._session = SessionStore()
        self._circle = CircleAdapter(flow=flow)
        self._identity = IdentityAdapter()
        self._memory = MemoryAdapter(store=self._store)
        self._consensus = ConsensusAdapter(threshold=threshold, flow=flow)
        self._contribution = ContributionAdapter(identity=self._identity)
        self._ports: Dict[str, Any] = {
            "circle": self._circle,
            "identity": self._identity,
            "memory": self._memory,
            "consensus": self._consensus,
            "contribution": self._contribution,
        }

    def get(self, port: str) -> Optional[Any]:
        return self._ports.get(port)

    def register(self, port: str, adapter: Any) -> None:
        self._ports[port] = adapter

    def list_ports(self) -> List[str]:
        return list(self._ports.keys())

    def build_context(self, session_id: Optional[str], circle_id: Optional[str],
                      dialog_mode: str, policy: Any, llm: Any) -> KernelContext:
        return KernelContext(
            session_id=session_id,
            circle_id=circle_id,
            dialog_mode=dialog_mode,
            llm=llm,
            tools=dict(self._ports),
            session=self._session,
            policy=policy,
            store=self._store,
        )
