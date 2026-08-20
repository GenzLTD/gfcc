"""
语料库配置加载 — 融合多数据源（科锐国际 + Python数据分析实战）
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from config.settings import config


@dataclass
class CorpusSource:
    id: str
    label: str
    path: Path
    description: str = ""


def load_corpus_sources(config_path: Path | None = None) -> list[CorpusSource]:
    """从 config/corpora.json 或 CORPUS_CONFIG 环境变量加载语料源。"""
    path = config_path or config.CORPUS_CONFIG
    if not path.exists():
        return _default_projects_sources()
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = []
    for item in data.get("sources", []):
        sources.append(CorpusSource(
            id=item["id"],
            label=item["label"],
            path=Path(item["path"]).expanduser().resolve(),
            description=item.get("description", ""),
        ))
    return sources


def _default_projects_sources() -> list[CorpusSource]:
    projects = Path("/Users/jason/Projects")
    return [
        CorpusSource(
            id="careerintl",
            label="科锐国际",
            path=projects / "300662科锐国际",
            description="300662 科锐国际财报",
        ),
        CorpusSource(
            id="python_data_analysis",
            label="数据分析与Python实战",
            path=projects / "数据分析与python实战-代码",
            description="Jupyter + CSV 数据分析实战",
        ),
    ]
