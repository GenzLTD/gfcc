#!/usr/bin/env bash
# DemoPeter — macOS/Linux 管理脚本
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"

usage() {
  cat <<EOF
用法: ./scripts/manage.sh <command>

命令:
  setup          创建 venv 并安装依赖
  dev|start      启动 Flask 开发面板 (port 5220)，start 为 dev 别名
  mcp            启动 MCP Server (stdio)
  import         融合导入科锐国际 + Python实战语料
  import-corpus  同 import（别名）
  corpus-list    预览融合语料文件数
  stress         压测: 融合语料导入 + 检索基准（默认）
  stress-full    融合语料全量导入 + 检索压测
  stress-imart   压测 ImartOS 大规模语料（需设 LIMIT）
  test           运行单元测试

环境变量:
  CORPUS         指定单目录语料时覆盖融合模式
  LIMIT          单目录模式下的导入上限（默认 100）
  SEARCH_MODE    hybrid | vector | keyword
  USE_FUSED_CORPUS  true|false（默认 true）
EOF
}

activate_venv() {
  if [[ -f "$VENV/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
  fi
}

cmd_setup() {
  "$PYTHON" -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  pip install -U pip
  pip install -r requirements.txt
  if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "已创建 .env — 请编辑 DEEPSEEK_API_KEY 和 CHROMA_MODE=persistent"
  fi
}

cmd_dev() {
  activate_venv
  export PYTHONPATH="$ROOT"
  "$PYTHON" src/web_dashboard.py
}

cmd_mcp() {
  activate_venv
  export PYTHONPATH="$ROOT"
  exec "$PYTHON" src/mcp_server.py
}

cmd_import() {
  activate_venv
  export PYTHONPATH="$ROOT"
  "$PYTHON" scripts/import_corpus.py "$@"
}

cmd_corpus_list() {
  activate_venv
  export PYTHONPATH="$ROOT"
  "$PYTHON" scripts/import_corpus.py --list
}

cmd_stress() {
  activate_venv
  export PYTHONPATH="$ROOT"
  local args=(--fused --output "$ROOT/reports/stress_$(date +%Y%m%d_%H%M%S).json")
  if [[ -n "${CORPUS:-}" ]]; then
    args=(--corpus "$CORPUS" --limit "${LIMIT:-100}" --output "$ROOT/reports/stress_$(date +%Y%m%d_%H%M%S).json")
  fi
  "$PYTHON" scripts/stress_test.py "${args[@]}"
}

cmd_stress_full() {
  activate_venv
  export PYTHONPATH="$ROOT"
  local args=(--fused --full-import --output "$ROOT/reports/stress_full_$(date +%Y%m%d_%H%M%S).json")
  if [[ -n "${CORPUS:-}" ]]; then
    args=(--corpus "$CORPUS" --full-import --output "$ROOT/reports/stress_full_$(date +%Y%m%d_%H%M%S).json")
  fi
  "$PYTHON" scripts/stress_test.py "${args[@]}"
}

cmd_stress_imart() {
  activate_venv
  export PYTHONPATH="$ROOT"
  CORPUS="${CORPUS:-/Users/jason/Documents/ImartOS/md_documents_collected}" \
  LIMIT="${LIMIT:-100}" \
  "$PYTHON" scripts/stress_test.py \
    --corpus "$CORPUS" --limit "$LIMIT" \
    --output "$ROOT/reports/stress_imart_$(date +%Y%m%d_%H%M%S).json"
}

cmd_test() {
  activate_venv
  export PYTHONPATH="$ROOT"
  "$PYTHON" -m unittest discover -s tests -p 'test_*.py' -v
}

case "${1:-}" in
  setup) cmd_setup ;;
  dev|start) cmd_dev ;;
  mcp) cmd_mcp ;;
  import) cmd_import ;;
  import-corpus) cmd_import ;;
  corpus-list) cmd_corpus_list ;;
  stress) cmd_stress ;;
  stress-full) cmd_stress_full ;;
  stress-imart) cmd_stress_imart ;;
  test) cmd_test ;;
  *) usage ;;
esac
