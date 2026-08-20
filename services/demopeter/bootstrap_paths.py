"""
统一 Python 路径引导 — 源码位于 static/src，需将项目根目录与 static/ 加入 sys.path。

在入口脚本中先插入项目根目录，再 `import bootstrap_paths`。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

for p in (str(ROOT / "static"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
