"""资源配置加载：resources.json → 统一路径解析（跨平台）。

与 tenet.resolver.config 对齐，差异点：
- 环境变量前缀用 ETHOS_。
- 支持 ${VAR} 插值（Windows 上 %VAR% 也兼容）。
- 提供 ``resolve_path`` 作为顶层便捷函数。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

_VAR_RE = re.compile(r"\$\{(\w+)\}|%(\w+)%")


def expand_env(value: str) -> str:
    """展开 ${VAR} 或 %VAR%（缺失变量保留原样）。"""
    def _repl(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        return os.environ.get(name, m.group(0))

    return _VAR_RE.sub(_repl, value)


def _resolve_dir(value: str) -> str:
    """展开环境变量 + 绝对化 + 统一分隔符。"""
    expanded = expand_env(value)
    if not expanded:
        return ""
    p = Path(expanded).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    return str(p).replace("\\", "/")


class ResourceConfig:
    """resources.json 的加载与查询门面。"""

    def __init__(self, data: Mapping[str, Any], base_dir: Optional[str] = None) -> None:
        self._data = dict(data)
        self._base_dir = base_dir or os.getcwd()

    # -- 构造 ------------------------------------------------------------- #

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "ResourceConfig":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"资源配置不存在: {p}")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return cls(data, base_dir=str(p.parent))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResourceConfig":
        return cls(data)

    # -- 查询 ------------------------------------------------------------- #

    def get(self, key: str, default: Any = None) -> Any:
        """取原始值（含 ${VAR} 展开，路径不做绝对化）。"""
        value = self._data.get(key, default)
        if isinstance(value, str):
            return expand_env(value)
        return value

    def path(self, key: str, default: str = "") -> str:
        """取路径类值：展开 + 绝对化 + '/' 统一。"""
        raw = self.get(key, default)
        return _resolve_dir(str(raw)) if raw else ""

    def section(self, name: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        value = self._data.get(name, default or {})
        return dict(value) if isinstance(value, dict) else {}

    def services(self) -> Dict[str, str]:
        """读取 services 段（服务名 → URL），并对 value 做 ${VAR} 展开。"""
        raw = self.section("services")
        out: Dict[str, str] = {}
        for name, value in raw.items():
            if isinstance(value, str) and value:
                out[str(name).lower()] = expand_env(value)
        return out


def resolve_path(key: str, config_path: Optional[str] = None) -> str:
    """便捷函数：从配置（或默认 ./resources.json）取路径并解析。"""
    p = config_path or "resources.json"
    return ResourceConfig.load(p).path(key)
