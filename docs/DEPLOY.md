# gfcc 部署手册

## 1. 架构总览

| 服务 | 端口 | 说明 | 镜像来源 |
|---|---|---|---|
| tatha | 5210 | 中央大脑，`POST /v1/ask` 单入口 | 本仓库构建 |
| demopeter | 5220 | RAG 知识库（上传/检索/问答） | 本仓库构建 |
| chroma | 内部 | 向量库（持久卷 `chroma_data`） | `chromadb/chroma:latest` |
| am-gateway | 3210 | agentmemory 认证网关（对外唯一入口） | 本仓库构建 |
| am-bridge | 内部 | 记忆 REST 桥（Node，`mem::*` 跨 worker 直调） | 本仓库构建 |
| am-engine | 内部 | 黑盒记忆引擎（**不暴露宿主端口**） | `iiidev/iii:0.11.2` |
| gfcc_kernel | 5211 | 格契内核（契约信封 `/v1/ask` + 五槽 + 五端口），宿主机 Python 进程，不走 docker | 本地 pip 安装 |

> **gfcc_kernel 启动方式**（Step3 联调时 Mac/Windows 侧均适用）：
> ```bash
> pip install -e services/ethos -e services/gfcc_kernel   # ethos 是本地路径依赖，必须联合安装
> uvicorn gfcc_kernel.app:app --host 0.0.0.0 --port 5211
> curl http://localhost:5211/health   # {"service":"gfcc_kernel","version":"1.1.0",...}
> ```
> 槽位由环境变量装配：`LLM_PROVIDER`（stub/ollama）、`STORE_PROVIDER`（stub/sqlite）、`STORE_DB_PATH`、`OLLAMA_MODEL`、`OLLAMA_BASE_URL`、`CONSENSUS_THRESHOLD`（默认 85），详见 `.env.example`。

## 2. 前置条件

- Docker Engine 24+ 与 Docker Compose v2 插件
- 服务器至少 4C8G（记忆引擎较重），磁盘 20GB+
- 出网访问 Docker Hub（拉取 `iiidev/iii`、`chromadb/chroma`）；离线环境见 §6

## 3. 首次部署

```bash
git clone <你的远端仓库> gfcc && cd gfcc
cp .env.example .env
# 编辑 .env：
#   ETHOS_AUTH_SECRET=       ← 必填，python -c "import secrets; print(secrets.token_urlsafe(48))"
#   DEEPSEEK_API_KEY=        ← 必填（Tatha 意图/问答与 DemoPeter 引用回答）
docker compose up -d --build
docker compose ps           # 全部 healthy/running
curl http://localhost:5210/v1/region
```

> 注：`am-init` 一次性初始化数据卷权限后自动退出，属正常现象。

## 4. 数据导入（用户自理）

### 4.1 记忆体

准备 jsonl（每行一个 JSON）：

```json
{"content": "ZERVIGO_FUTURE 使用 MySQL 8.4", "type": "fact", "importance": 8, "metadata": {"source": "wiki"}}
```

导入（走网关链路，支持断点续传）：

```bash
python tools/import_memories.py data/chunks.jsonl --resume
# HMAC 严格模式需带令牌：
python tools/import_memories.py data/chunks.jsonl --token <JWT> --resume
```

### 4.2 知识库

- 上传：`POST /api/documents/upload`（multipart，需鉴权）
- 批量：DemoPeter 自带索引器（见 `services/demopeter/scripts/`）
- 亦可直接将文档放入挂载卷后重建索引

## 5. 升级与回滚

```bash
# 拉取新代码 + 重建
git pull
docker compose up -d --build --remove-orphans

# 回滚（用 tag 版本）
git checkout <上一版本tag> && docker compose up -d --build
```

## 6. 离线环境部署

外网受限时，先在联网机器上打包：

```bash
docker pull iiidev/iii:0.11.2
docker pull chromadb/chroma:latest
docker save iiidev/iii:0.11.2 chromadb/chroma:latest -o images.tar.gz  # 或 -o 单文件
# 本仓库四个镜像：
docker build -f services/tatha/Dockerfile        -t gfcc/tatha:latest .
docker build -f services/demopeter/Dockerfile    -t gfcc/demopeter:latest .
docker build -f services/agentmemory/Dockerfile.gateway -t gfcc/am-gateway:latest .
docker build -f services/agentmemory/Dockerfile.bridge   -t gfcc/am-bridge:latest .
docker save gfcc/tatha gfcc/demopeter gfcc/am-gateway gfcc/am-bridge -o gfcc-images.tar
```

目标机：

```bash
docker load -i images.tar && docker load -i gfcc-images.tar
docker compose up -d
```

## 7. CI/CD

| 流水线 | 触发 | 行为 |
|---|---|---|
| `ci.yml` | push main / PR | test-libs（ethos/tenet 单测 + tatha/gateway import）→ test-kernel（内核 52 项）→ test-contracts（契约 JSON 校验）→ 构建并推送四镜像到 GHCR |
| `deploy.yml` | 手动 / tag `v*` | SCP 上传仓库 → SSH `compose pull && up` |

deploy.yml 所需 GitHub Secrets：

| Secret | 说明 |
|---|---|
| `DEPLOY_HOST` | 服务器 IP/域名 |
| `DEPLOY_USER` | SSH 用户 |
| `DEPLOY_SSH_KEY` | 私钥（OpenSSH 格式） |
| `DEPLOY_PORT` | 可选，默认 22 |

## 8. 安全清单

- [ ] `ETHOS_AUTH_SECRET` 使用强随机值且三端一致（tatha / demopeter / am-gateway）
- [ ] 对外仅暴露 5210 / 5220 / 3210，引擎 3111/49134 不映射宿主
- [ ] `.env` 不入库（.gitignore 已处理）
- [ ] 审计库：am-gateway 落 `/data/ethos_audit.db`，Tatha 落 `logs/audit.db`（均持久卷）
- [ ] 建议前置反向代理（Caddy/Nginx）终结 TLS 后再对外
