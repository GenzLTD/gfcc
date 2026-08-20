# gfcc — 智能体体系交付栈

**契约真源（先于实现）**：[格契端口真源提纲](docs/ports/README.md) · [`contracts/`](contracts/) · [`modes/`](modes/)  
默认组合是内核 + identity / memory / consensus / contribution。DemoPeter、agentmemory/iii、JobFirst 意图是可选画像，不是脊柱。

**中央大脑 + 统一安全底座 + 可调度知识服务** 的单仓库（monorepo）交付形态。

```
用户 / 上层助理
      │ POST /v1/ask（Tatha 单入口，ethos 认证 + 配额 + 审计）
      ▼
 Tatha 中央大脑 (:5210)
 ├─ knowledge 意图 ──► DemoPeter RAG 知识库 (:5220)
 ├─ memory 意图    ──► am-gateway (:3210) ─► am-bridge (:3220) ─► iii-engine 记忆引擎
 └─ job_match / poetry / credit / mbti ──► 内置本地能力
                ▲
        同一把 ETHOS_AUTH_SECRET（HMAC 严格模式），系统令牌跨服务互通
```

## 目录结构

```
gfcc/
├── docker-compose.yml            # 单栈编排（6 服务）
├── .env.example                  # 环境模板（复制为 .env）
├── services/
│   ├── ethos/                    # 安全底座（认证/鉴权/配额/审计，零依赖库）
│   ├── tenet/                    # 共享内核（Tatha 依赖）
│   ├── tatha/                    # 中央大脑（单入口 /v1/ask）
│   ├── demopeter/                # RAG 知识库（文档上传/检索/问答）
│   └── agentmemory/              # 长期记忆（网关 + 桥 + 引擎配置）
├── tools/import_memories.py      # 记忆体导入器（断点续传，走网关链路）
├── deploy/deploy.sh              # 一键部署脚本
├── docs/DEPLOY.md                # 部署手册
└── .github/workflows/            # CI（构建推送镜像）+ Deploy（SSH 自动部署）
```

## 快速开始

```bash
# 1. 配置
cp .env.example .env
#    生产必须设置：ETHOS_AUTH_SECRET（统一鉴权密钥）、DEEPSEEK_API_KEY

# 2. 启动（首次构建约 5-10 分钟）
docker compose up -d --build

# 3. 验证
curl http://localhost:5210/v1/region          # 定价/区域（无鉴权）
curl -X POST http://localhost:5210/v1/ask \
     -H 'Content-Type: application/json' \
     -d '{"text":"记住 ZERVIGO_FUTURE 数据库配置为 MySQL 8.4"}'   # 写记忆
curl -X POST http://localhost:5210/v1/ask \
     -H 'Content-Type: application/json' \
     -d '{"text":"之前关于数据库配置的记忆"}'                       # 检索记忆
```

## 对外能力面

| 入口 | 能力 | 鉴权 |
|---|---|---|
| `POST /v1/ask` | 意图统一入口（memory / knowledge / job_match / poetry / document / credit…） | ethos |
| `GET /v1/region` | 区域定价 | 无 |
| `GET/POST /agentmemory/*` | 记忆读写（对外直连通道） | ethos（memory.read/write 需 pro） |
| `POST /api/rag/query` | RAG 问答（DemoPeter 直连） | ethos |
| `POST /api/documents/upload` | 知识库灌数据 | ethos |

## 数据边界

交付的是**体系与能力**，数据由使用方自理：

- **记忆体**：首次启动空库，用 `tools/import_memories.py data/chunks.jsonl --resume` 导入
- **知识库**：首次启动空库，用 DemoPeter 上传/导入 API 灌入自己的文档

部署细节见 [docs/DEPLOY.md](docs/DEPLOY.md)。
