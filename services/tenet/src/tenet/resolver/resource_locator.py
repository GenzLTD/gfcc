"""资源定位：逻辑资源键 → 平台感知的本地路径。

这是解决 Windows / macOS 硬编码路径问题的核心层：
业务代码只传逻辑键（如 "vault.json"），本层按当前平台解析出实际路径。

配置格式（支持三平台分支 + ${ENV} 占位符）：
    mapping = {
        "vault.json": {
            "win32":  "E:/Data/vault.json",          # Windows
            "darwin": "/Users/me/Data/vault.json",   # macOS
            "linux":  "/srv/data/vault.json",
            "any":    "/fallback/vault.json",        # 兜底
        },
        "chroma": "${CHROMA_PERSIST_DIR}",           # 单字符串 + 环境变量
    }
未配置的键：回退相对路径 data/<key>（双平台通用，不写盘符）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Optional, Protocol


class ResourceLocator(Protocol):
    def resolve(self, key: str) -> Path:
        """把逻辑资源键解析为本地路径。未配置且无兜底时抛 KeyError。"""
        ...


class StaticResourceLocator:
    """静态配置实现，支持按平台分支解析。"""

    def __init__(self, mapping: Optional[Mapping[str, object]] = None) -> None:
        self._mapping: dict[str, object] = dict(mapping or {})
        self._platform = sys.platform

    def resolve(self, key: str) -> Path:
        spec = self._mapping.get(key)
        if spec is None:
            return Path("data") / key  # 默认相对路径，双平台通用

        if isinstance(spec, Mapping):
            raw = str(spec.get(self._platform) or spec.get("any") or "")
            if not raw:
                raise KeyError(f"资源 {key!r} 未配置平台 {self._platform!r} 的路径")
        else:
            raw = str(spec)

        return Path(os.path.expandvars(raw)).expanduser()


class EnvResourceLocator:
    """环境变量兜底：TENET_RESOURCE_<KEY>（KEY 中 . - 转 _）。"""

    def resolve(self, key: str) -> Path:
        env_key = "TENET_RESOURCE_" + key.upper().replace(".", "_").replace("-", "_")
        raw = os.getenv(env_key)
        if not raw:
            raise KeyError(f"未配置环境变量 {env_key}")
        return Path(raw).expanduser()


class ChainedResourceLocator:
    """主配置优先，未命中时回退到兜底定位器（如环境变量）。"""

    def __init__(self, primary: ResourceLocator, fallback: ResourceLocator) -> None:
        self._primary = primary
        self._fallback = fallback

    def resolve(self, key: str) -> Path:
        try:
            return self._primary.resolve(key)
        except KeyError:
            return self._fallback.resolve(key)
