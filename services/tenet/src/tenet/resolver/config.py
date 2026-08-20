"""资源配置文件加载：把路径配置从代码中剥离，收敛到独立配置文件。

这是「动态 URL / 路径数据库」的落地载体：业务代码只传逻辑键，
真实路径全部写在 config 文件里，换平台只改配置、不动代码。

支持格式（按扩展名自动识别）：
- .json：标准 JSON，零依赖，Python 3.10+ 可用
- .toml：Python 3.11+ 内置 tomllib；3.10 需安装 tomli 并传入 loader

配置文件结构示例（JSON，与 StaticResourceLocator 的 mapping 同构）：
    {
      "chinese-poetry": {
        "win32":  "E:/FiveBlessings/chinese-poetry",
        "darwin": "${HOME}/FiveBlessings/chinese-poetry",
        "linux":  "/srv/data/chinese-poetry"
      },
      "chroma.poetry_full": "${TATHA_ROOT}/.data/chroma/poetry_full"
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10
    tomllib = None  # type: ignore[assignment]


def load_resource_config(
    path: str | Path,
    toml_loader: Optional[Callable[[Path], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """从配置文件加载资源映射，返回与 StaticResourceLocator.mapping 同构的 dict。

    - .json：用 json 解析（零依赖）。
    - .toml：优先用内置 tomllib（3.11+）；3.10 需通过 toml_loader 注入 tomli。
    其它/未知扩展名：先按 JSON 尝试，失败再按 TOML 尝试。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"资源配置文件不存在: {p}")

    suffix = p.suffix.lower()
    if suffix == ".json":
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif suffix == ".toml":
        data = _load_toml(p, toml_loader)
    else:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = _load_toml(p, toml_loader)

    if not isinstance(data, dict):
        raise ValueError(f"资源配置文件顶层必须是对象: {p}")
    return data


def _load_toml(
    p: Path,
    toml_loader: Optional[Callable[[Path], dict[str, Any]]] = None,
) -> dict[str, Any]:
    if toml_loader is not None:
        return toml_loader(p)
    if tomllib is None:
        raise RuntimeError(
            "TOML 配置需要 Python 3.11+（内置 tomllib）；3.10 请安装 tomli 并传入 toml_loader"
        )
    with open(p, "rb") as f:
        return tomllib.load(f)
