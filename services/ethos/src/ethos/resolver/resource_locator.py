"""资源定位：逻辑资源名 → 平台无关的绝对路径。

解决"盘符/用户主目录硬编码"问题：Windows 的 D:/、macOS 的 /Users/x、
Linux 的 /home/x 全部收敛到 resources.json，代码只写逻辑名。

示例 resources.json:
    {
      "resources": {
        "poetry_corpus":   "${POETRY_ROOT}/chinese-poetry",
        "chroma_index":    "${WORKSPACE}/data/chroma",
        "audit_log_dir":   "~/logs/ethos"
      }
    }
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional

from .config import ResourceConfig, expand_env, _resolve_dir


class ResourceLocator:
    """按逻辑名定位路径；支持运行时 override（环境变量优先）。"""

    def __init__(self, config: ResourceConfig) -> None:
        self._config = config
        self._overrides: dict[str, str] = {}

    # -- 构造 ------------------------------------------------------------- #

    @classmethod
    def from_file(cls, path: str) -> "ResourceLocator":
        return cls(ResourceConfig.load(path))

    # -- 定位 ------------------------------------------------------------- #

    def locate(self, name: str, default: str = "") -> str:
        """定位逻辑资源 → 绝对路径。找不到返回 default。"""
        if name in self._overrides:
            return self._overrides[name]
        env_val = _env_for(name)
        if env_val:
            return _resolve_dir(env_val)
        return self._config.path(name, default)

    def paths(self) -> dict[str, str]:
        """列出配置中所有资源 → 解析后路径。"""
        out: dict[str, str] = {}
        for key, value in self._config._data.items():
            if isinstance(value, str) and ("${" in value or "%" in value or "/" in value or value.startswith("~")):
                out[key] = self._config.path(key)
        return out

    def override(self, name: str, value: str) -> None:
        """运行时覆盖某个资源路径（测试/临时切换用）。"""
        self._overrides[name] = _resolve_dir(value)


def _env_for(name: str) -> str:
    """ETHOS_RESOURCE_<NAME> 环境变量覆盖。"""
    key = f"ETHOS_RESOURCE_{name.upper().replace('-', '_')}"
    return os_getenv(key, "")


def os_getenv(key: str, default: str = "") -> str:
    import os

    return os.environ.get(key, default)
