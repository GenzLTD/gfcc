#!/bin/bash
# ============================================================
# szpeter2026 知识库 — 阿里云 ECS 一键部署脚本
# ============================================================
# 用法（在阿里云 ECS 上执行）：
#   curl -fsSL https://raw.githubusercontent.com/szpeter2026/szpeter2026/main/deploy.sh | bash
#   或
#   git clone https://github.com/szpeter2026/szpeter2026.git
#   cd szpeter2026 && bash deploy.sh
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  szpeter2026 知识库 — 阿里云部署脚本      ${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ---- 获取项目目录 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DEPLOY_DIR="/opt/szpeter2026"

# ---- 0. 系统检查 ----
echo -e "${YELLOW}[0/6] 系统检查...${NC}"

# 检测发行版
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo -e "${GREEN}       系统: $ID $VERSION_ID${NC}"
else
    echo -e "${RED}       无法检测系统版本${NC}"
    exit 1
fi

# 检查内存
TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
echo -e "${GREEN}       内存: ${TOTAL_MEM}GB${NC}"

# 检查磁盘
DISK_AVAIL=$(df -BG /opt 2>/dev/null | awk 'NR==2{print $4}' | tr -d 'G')
if [ -z "$DISK_AVAIL" ]; then
    DISK_AVAIL=$(df -BG / 2>/dev/null | awk 'NR==2{print $4}' | tr -d 'G')
fi
echo -e "${GREEN}       可用磁盘: ${DISK_AVAIL}GB${NC}"

if [ "$DISK_AVAIL" -lt 10 ]; then
    echo -e "${RED}       ⚠ 磁盘空间不足 10GB，建议清理或扩容${NC}"
    exit 1
fi

# ---- 1. 安装 Docker ----
echo -e "${YELLOW}[1/6] 安装 Docker...${NC}"

if command -v docker &>/dev/null; then
    DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+' | head -1)
    echo -e "${GREEN}       Docker 已安装: $DOCKER_VERSION${NC}"
else
    echo -e "${YELLOW}       正在安装 Docker...${NC}"
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker
    echo -e "${GREEN}       Docker 安装完成${NC}"
fi

# 检查 Docker Compose 插件
if docker compose version &>/dev/null 2>&1; then
    echo -e "${GREEN}       Docker Compose 就绪${NC}"
else
    echo -e "${YELLOW}       安装 Docker Compose 插件...${NC}"
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin
    echo -e "${GREEN}       Docker Compose 安装完成${NC}"
fi

# 配置阿里云镜像加速
echo -e "${YELLOW}       配置阿里云镜像加速...${NC}"
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://registry.cn-hangzhou.aliyuncs.com",
    "https://mirror.ccs.tencentyun.com"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
EOF
systemctl daemon-reload
systemctl restart docker
echo -e "${GREEN}       镜像加速配置完成${NC}"

# ---- 2. 创建项目目录 ----
echo -e "${YELLOW}[2/6] 创建项目目录...${NC}"
mkdir -p "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR/db/chroma_docker"
mkdir -p "$DEPLOY_DIR/db/pgdata"
mkdir -p "$DEPLOY_DIR/db/pg-init"
mkdir -p "$DEPLOY_DIR/knowledge_base"
mkdir -p "$DEPLOY_DIR/import_staging"
echo -e "${GREEN}       目录就绪: $DEPLOY_DIR${NC}"

# ---- 3. 克隆代码（如果当前目录不是 git 仓库） ----
echo -e "${YELLOW}[3/6] 获取项目代码...${NC}"

if [ -d .git ]; then
    echo -e "${GREEN}       已在 Git 仓库中，拉取最新代码...${NC}"
    git pull origin main
else
    if [ "$(pwd)" != "$DEPLOY_DIR" ]; then
        echo -e "${YELLOW}       克隆代码到 $DEPLOY_DIR...${NC}"
        if [ -d "$DEPLOY_DIR/.git" ]; then
            cd "$DEPLOY_DIR" && git pull origin main
        else
            git clone https://github.com/szpeter2026/szpeter2026.git "$DEPLOY_DIR"
            cd "$DEPLOY_DIR"
        fi
    else
        echo -e "${YELLOW}       请先克隆代码: git clone https://github.com/szpeter2026/szpeter2026.git $DEPLOY_DIR${NC}"
        exit 1
    fi
fi

# ---- 4. 检查配置文件 ----
echo -e "${YELLOW}[4/6] 检查配置文件...${NC}"

if [ ! -f ".env.production" ]; then
    if [ -f ".env.production.example" ]; then
        cp .env.production.example .env.production
    else
        cat > .env.production <<'ENVEOF'
# szpeter2026 知识库 - 环境配置（阿里云生产环境）

# === AI 模型配置 ===
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
AI_PROVIDER=deepseek

# === 向量数据库配置（Docker Chroma 容器，remote 模式）===
CHROMA_MODE=remote
CHROMA_HOST=chroma
CHROMA_PORT=8001
CHROMA_COLLECTION=szpeter2026_kb

# === 检索模式 ===
SEARCH_MODE=hybrid
HYBRID_RRF_K=60

# === pgvector ===
PGVECTOR_ENABLED=true
PGVECTOR_HOST=pgvector
PGVECTOR_PORT=5432
PGVECTOR_USER=szpeter
PGVECTOR_PASSWORD=Szpeter2026!
PGVECTOR_DATABASE=szpeter2026
PGVECTOR_EMBEDDING_DIM=768

# === Web 面板配置 ===
WEB_HOST=0.0.0.0
WEB_PORT=5220
WEB_DEBUG=false

# === 文档处理配置 ===
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
ENVEOF
    fi
    echo -e "${RED}       ⚠ 已创建 .env.production 模板！${NC}"
    echo -e "${RED}       请编辑后重新运行：${NC}"
    echo -e "${RED}       vi .env.production${NC}"
    echo -e "${RED}       必须修改: DEEPSEEK_API_KEY 和 PGVECTOR_PASSWORD${NC}"
    exit 1
else
    # 检查 API Key 是否还是默认值
    if grep -q "sk-your-deepseek-api-key\|sk-xxx" .env.production 2>/dev/null; then
        echo -e "${RED}       ⚠ .env.production 中 API Key 未配置！${NC}"
        echo -e "${RED}       vi .env.production  ← 修改 DEEPSEEK_API_KEY${NC}"
        exit 1
    fi
    echo -e "${GREEN}       配置文件就绪${NC}"
fi

# ---- 5. 构建并启动服务 ----
echo -e "${YELLOW}[5/6] 构建并启动服务（生产模式）...${NC}"

# 使用生产配置（含 nginx）
docker compose -f docker-compose.prod.yml --profile production up -d --build

echo -e "${GREEN}       服务已启动${NC}"

# ---- 6. 验证 ----
echo -e "${YELLOW}[6/6] 验证部署...${NC}"
sleep 5

ALL_OK=true

for svc in nginx web chroma pgvector; do
    if docker ps --format '{{.Names}}' | grep -q "szpeter2026-$svc"; then
        STATUS=$(docker inspect --format='{{.State.Status}}' "szpeter2026-$svc" 2>/dev/null || echo "unknown")
        if [ "$STATUS" = "running" ] || [ "$STATUS" = "healthy" ]; then
            echo -e "${GREEN}       ✅ $svc ($STATUS)${NC}"
        else
            echo -e "${YELLOW}       ⚠️  $svc ($STATUS)${NC}"
            ALL_OK=false
        fi
    else
        echo -e "${RED}       ❌ $svc 未运行${NC}"
        ALL_OK=false
    fi
done

# 获取服务器公网 IP
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s ip.sb 2>/dev/null || echo "47.115.168.107")

# 测试 HTTP 连通性
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}       ✅ HTTP 访问正常 (200 OK)${NC}"
else
    echo -e "${YELLOW}       ⚠️  HTTP 状态码: $HTTP_CODE（启动中，稍后再试）${NC}"
fi

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  部署完成！                            ${NC}"
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  访问地址: http://${SERVER_IP}${NC}"
echo -e "${CYAN}  查看日志: docker compose -f docker-compose.prod.yml logs -f web${NC}"
echo -e "${CYAN}  重启服务: docker compose -f docker-compose.prod.yml --profile production restart web${NC}"
echo -e "${CYAN}  停止所有: docker compose -f docker-compose.prod.yml --profile production down${NC}"
echo -e "${CYAN}  入库语料: docker exec szpeter2026-web python /app/scripts/import_jsonl.py \\${NC}"
echo -e "${CYAN}            --file /app/import_staging/documents.jsonl --label md_import_staging${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

if [ "$ALL_OK" = false ]; then
    echo -e "${YELLOW}部分服务异常，请检查日志：${NC}"
    echo -e "${YELLOW}  docker compose -f docker-compose.prod.yml logs --tail=50${NC}"
    exit 1
fi
