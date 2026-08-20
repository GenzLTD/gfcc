#!/usr/bin/env bash
# gfcc 一键部署脚本（目标机：Linux + Docker + Docker Compose）
#
#   curl -fsSL <你的脚本URL> | bash
#   或
#   git clone <你的远端仓库> gfcc && cd gfcc && bash deploy/deploy.sh
set -euo pipefail

echo "==> [1/5] 检查 Docker"
command -v docker >/dev/null || { echo "缺少 docker"; exit 1; }
docker compose version >/dev/null || { echo "缺少 docker compose 插件"; exit 1; }

echo "==> [2/5] 准备 .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 .env，请编辑填写 ETHOS_AUTH_SECRET 与 DEEPSEEK_API_KEY 后重跑"
  exit 0
fi

echo "==> [3/5] 拉取镜像（黑盒引擎 iiidev/iii:0.11.2）"
docker compose pull || echo "WARN: 拉取失败，若为离线环境请先 docker load 打包镜像"

echo "==> [4/5] 构建 + 启动"
docker compose up -d --build --remove-orphans

echo "==> [5/5] 健康检查"
sleep 3
docker compose ps
curl -sf http://localhost:5210/v1/region && echo " Tatha OK" || echo "WARN: Tatha 未就绪，稍后重试"

cat <<'EOF'

部署完成。接下来按需灌数据：
  记忆：  python tools/import_memories.py data/chunks.jsonl --resume
  知识库：POST http://<host>:5220/api/documents/upload（鉴权见 .env 的 ETHOS_AUTH_SECRET）
EOF
