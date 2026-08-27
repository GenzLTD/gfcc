#!/bin/zsh
# gfcc_kernel 启动脚本（launchd 托管 / 手动两用）。
# 环境变量只来自 .env（不入库，六项含 ingest 密钥）。
#
#   launchd 托管: ~/Library/LaunchAgents/com.gfcc.kernel.plist 调用本脚本（前台 exec，生命周期归 launchd）
#   手动调试:     ./run_gfcc_kernel.sh            （前台，Ctrl-C 停）
#                  nohup ./run_gfcc_kernel.sh &   （临时后台）
set -euo pipefail
cd "$(dirname "$0")"

# 1) 环境变量：.env 不入库，密钥只在这里
if [[ ! -f .env ]]; then
  echo "run_gfcc_kernel.sh: missing .env（参照 .env.example 填写，SIGNAL_INGEST_SECRET 与 Looma THOMAS .env 同一把）" >&2
  exit 1
fi
set -a; source .env; set +a

# 2) 等 Ollama :11434 就绪（最多 30s）
for i in {1..30}; do
  curl -sf --max-time 1 http://localhost:11434/api/tags >/dev/null 2>&1 && break
  [[ "$i" -eq 30 ]] && { echo "run_gfcc_kernel.sh: ollama :11434 not up" >&2; exit 1; }
  sleep 1
done

# 3) 前台运行：launchd 管生命周期（崩溃自动拉起）
exec .venv/bin/python .venv/bin/uvicorn gfcc_kernel.app:app --host 0.0.0.0 --port 5211
