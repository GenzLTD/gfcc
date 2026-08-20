#!/usr/bin/env bash
# Tenet 安装脚本（macOS / Linux）
# 用法: ./scripts/install.sh    （在项目根目录执行）
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 安装 tenet（editable + dev 依赖）..."
python3 -m pip install -e ".[dev]"

echo "==> 运行测试..."
python3 -m pytest tests/ -v

echo "==> 完成。在任意 Python 项目中："
echo "    from tenet.security import init_security"
echo "    from tenet.resolver import init_resolver"
