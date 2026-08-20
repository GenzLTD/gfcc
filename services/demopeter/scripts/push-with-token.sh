#!/usr/bin/env bash
# 使用项目根目录 macos.token 推送（勿提交该文件）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOKEN_FILE="${ROOT}/macos.token"

if [[ ! -f "$TOKEN_FILE" ]]; then
  echo "❌ 未找到 $TOKEN_FILE"
  echo "   请将 GitHub Personal Access Token 写入该文件（单行，无空格换行）"
  exit 1
fi

TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
if [[ -z "$TOKEN" ]]; then
  echo "❌ token 文件为空"
  exit 1
fi

USER="${GITHUB_USER:-szpeter2026}"
REPO="${GITHUB_REPO:-szpeter2026/DemoPeter}"
BRANCH="${1:-main}"

echo "→ 推送到 https://github.com/${REPO}.git (${BRANCH})"
# 部分网络/VPN 下 HTTP/2 会报 "Error in the HTTP2 framing layer"，改用 HTTP/1.1
git -C "$ROOT" -c http.version=HTTP/1.1 push "https://${USER}:${TOKEN}@github.com/${REPO}.git" "$BRANCH"
