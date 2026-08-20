# 格契（GFCC）

**格契**是社区共同体的牵引力层：把「记得住、协商得了、贡献兑得现」做成可交付的体系。方向盘在共同体手里（Tractor：你掌方向，我出力气）。

- **gfcc = 契约层（真源）**：[价值层](docs/vision.md) · [端口提纲](docs/ports/README.md) · [`contracts/`](contracts/)
- **Tatha = 实现层**：当前仓里 `POST /v1/ask` 的一个实现，可替换；不是真源。
- 默认组合：内核 + circle / identity / memory / consensus / contribution。DemoPeter、agentmemory/iii、JobFirst 是可选画像，可卸载。
- v1 不依赖链；链是未来可选的一层，不是现在的承诺。

版本：契约 **1.1.0** · [VERSIONING](docs/VERSIONING.md) · [CHANGELOG](docs/CHANGELOG.md)

---

# 当前实现画像（可卸载）

下面这张图是仓库里正在跑的 Tatha + DemoPeter + iii 栈，对应 `modes/profile.demo.yaml`，**不是**格契默认脊柱。

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
├── docs/vision.md                # L-1 价值层（为谁而生）
├── docs/ports/README.md          # 端口真源提纲
├── contracts/                    # L0 机器可读契约
├── modes/                        # 默认组合 vs 演示画像
├── docker-compose.yml            # 单栈编排（6 服务，偏 demo 画像）
├── .env.example
├── services/
│   ├── ethos/                    # 安全底座（认证/鉴权/配额/审计）
│   ├── tenet/                    # 共享内核（Tatha 依赖）
│   ├── tatha/                    # Ask 信封的一个实现（可替换）
│   ├── demopeter/                # RAG 样例（可卸载）
│   └── agentmemory/              # 记忆引擎样例（可卸载）
├── tools/import_memories.py
├── deploy/deploy.sh
├── docs/DEPLOY.md
└── .github/workflows/
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

## 对外能力面（demo 画像，正在跑的 HTTP）

契约层一等端口是 circle / identity / memory / consensus / contribution，见 [`contracts/registry.v1.json`](contracts/registry.v1.json)。下表是当前 Tatha 实现已暴露的入口，不等于默认脊柱。

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
