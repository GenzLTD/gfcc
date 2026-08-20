# agentmemory 接入 Ethos 改造清单（已落地）

> 目标：让 agentmemory 暴露的 HTTP 记忆接口（3111/3112）接入 ethos 的认证/鉴权/审计，并保持黑盒不动。
> 关键约束：agentmemory **不是自有代码工程**，而是 `iiidev/iii` 第三方镜像的 compose 部署目录
> （distroless、UID 65532、容器内 `node dist/index.mjs`）。因此 ethos 只能以**宿主侧网关**形态接入。
>
> **迁移说明**：本文档由 tenet 版迁移而来（tenet → ethos）。核心差异：
> - `init_security(auth="auto", audit="sqlite", audit_path=...)` → `init_security(secret=..., tier_policy=..., audit_db=...)`
> - 认证命名：`TENET_AUTH_SECRET` → `ETHOS_AUTH_SECRET`；审计 `tenet_audit.db` → `ethos_audit.db`（旧表自动迁移保留）
> - token 来源：tenet 版需 `/auth/login` 或预置 token 文件；**ethos 版由 Tatha `SystemMinter` 自动签发**（网关协议 §1.5），无需签发渠道

## 0. 现状盘点

| 项 | 现状 |
|---|---|
| 部署形态 | `E:\CorpusPipeline\agentmemory\docker-compose.yml`（含 `iii-init` chown 引导容器） |
| 镜像 | `iiidev/iii:0.11.2`（**钉死版本**，v0.11.6 的 sandbox worker 模型不兼容） |
| 暴露端口 | `127.0.0.1:49134`（内部）、`3111`（HTTP worker）、`3112`（stream）、`9464`（observability） |
| 数据 | `data/` 下 79 个 `.bin` + `state_store.db`；`memories_export.db` 为 SQLite 导出（约 35 万条） |
| 配置 | `iii-config.docker.yaml`（workers：http/state/queue/pubsub/cron/stream/observability/exec） |
| 自有代码 | 宿主侧 `gateway.py`（新）+ `test_embed_speed.mjs` |

---

## 1. 接入形态：宿主侧认证网关（已落地）

**为什么是网关**：distroless 镜像内无 Python、无 shell、只读根文件系统，ethos 无法进容器；
且 `iii-engine` 是黑盒第三方组件，不宜改动。宿主侧起一个 Python 网关（FastAPI），
把 3111/3112 收编成"仅网关可达"，对外只暴露网关端口 3210。

```
Tatha 智慧大脑 / 外部客户端
        │  Bearer <ethos JWT（svc:tatha 系统令牌 / 用户令牌）>
        ▼
 [ethos 网关 127.0.0.1:3210]   ←── gateway.py（FastAPI）
        │  认证→鉴权→审计→转发
        ├──► iii-engine :3111 (HTTP API，仅绑 127.0.0.1)
        └──► iii-engine :3112 (stream / SSE，透传)
```

### 1.1 `gateway.py`（已创建，`E:\CorpusPipeline\agentmemory\gateway.py`）

- **认证**：ethos `HmacJwtVerifier` 验签标准 JWT（无 `ETHOS_AUTH_SECRET` → Stub 放行，本地联调零配置）
- **鉴权**：GET → `memory.read`（pro 起）；POST/PUT/DELETE/PATCH → `memory.write`（pro 起）；
  `/config`、`/admin`、`/workers`、`/debug`、`/reset` 前缀 → `admin`
- **审计**：每次调用落 `data/ethos_audit.db`（ethos 统一结构，与 Tatha/DemoPeter 一致）
- **转发**：JSON → :3111；SSE（`accept: text/event-stream`）→ :3112 流式透传（`StreamingResponse`）
- **保护**：进程内限流（默认 60 req/min/IP，`AM_RATE_LIMIT` 可调）+ 上游 60s 超时兜底（`AM_UPSTREAM_TIMEOUT`）
- **豁免**：`/healthz`、`/health`、`/metrics`（探针直通）
- **运行**（宿主侧）：`uvicorn gateway:app --host 127.0.0.1 --port 3210`

### 1.2 compose 变更（已落地，`docker-compose.yml`）

- [x] 新增 `gateway` 服务（`python:3.11-slim` 免构建方案）：
  - ethos 源码从 `D:/surface-zervi/GitHub/szjason72/ethos` bind mount 进容器，启动时 `pip install -e /ethos`
  - `depends_on: iii-engine (service_healthy)`；`iii-engine` 补了 `healthcheck`（node fetch :3111）
  - 仅绑 `127.0.0.1:3210:3210`；环境变量 `AM_ENGINE_HTTP/AM_ENGINE_STREAM/AM_AUDIT_DB/ETHOS_AUTH_SECRET`
- [x] `iii-engine` 的 3111/3112 **保持只绑 127.0.0.1 且不对外暴露**（原有，未改）
- [ ] 注：若 Docker Desktop 跨盘挂载（D:）不可用，可退化为宿主侧直接跑 `uvicorn`（代码相同，零差异）

### 1.3 动作→策略映射（已落地，`TIER_POLICY`）

| iii-engine 接口类别 | HTTP 方法 | action | 档位 |
|---|---|---|---|
| 记忆读取（search/get/export） | GET | `memory.read` | pro |
| 记忆写入（add/save/import） | POST/PUT | `memory.write` | pro |
| 删除/清理 | DELETE | `memory.write` | pro |
| 管理/配置 | 任意 | `admin` | admin |

> 与 Tatha `_TIER_POLICY`、DemoPeter `TIER_POLICY` 三处对齐，同一把 `ETHOS_AUTH_SECRET` 互通。

### 1.4 Tatha 调度（已落地）

- `central_brain.py` 新增 **`memory` 意图**：关键词「记忆/回忆/记得/之前说过」+ LLM 枚举同步
- `dispatch("memory", ...)` → `GET {TATHA_MEMORY_URL}/v1/memories/search?q=...&limit=10`（默认 `http://127.0.0.1:3210`）
- HMAC 模式下自动携带 `svc:tatha` 系统令牌（`tier=admin`，网关 `memory.read=pro` 放行）；stub 模式不带头

---

## 2. Resolver 接入（低优先，可选）

- [ ] 路径收敛（`data/`、`memories_export.db`、`iii-config.docker.yaml`、审计库）收益评估
- [ ] `gateway.py` 中路径改用 resolver 解析（当前用环境变量 `AM_AUDIT_DB` 覆盖，足够）

---

## 3. 数据质量治理（独立工作项，强烈建议）

`memories_export.db` 约 35 万条记忆中混入大量 `FileOrganizer` 路径搬运产生的 **ERROR 级误入库记录**
（untrusted mount / 路径失败日志被当记忆写入）。

- [ ] 导出 → 清洗（按 `level=ERROR`、`source="FileOrganizer"`、关键词 `untrusted mount` 过滤）→ 重建
- [ ] 清洗脚本放 `scripts/clean_memories.py`，接入网关前执行一次

---

## 4. 验证清单（已通过，见 `test_gateway.py` 10 项）

| # | 场景 | 预期 | 结果 |
|---|---|---|---|
| 1 | `/healthz` 无 token | 200 | ✅ |
| 2 | Stub 模式（无 `ETHOS_AUTH_SECRET`）调 `/v1/memories/search` | 透传 200 | ✅ |
| 3 | HMAC 模式无 token | 401 | ✅ |
| 4 | `tier=free` token 读 | 403（memory.read 需 pro） | ✅ |
| 5 | `tier=pro` token 读 | 透传 200 | ✅ |
| 6 | `tier=admin`（svc:tatha）写 | 透传 200 | ✅ |
| 7 | `tier=free` token 写 | 403 | ✅ |
| 8 | 管理路径 `/admin/*`：pro 拒 / admin 放 | 403/200 | ✅ |
| 9 | 上游不可达 | 502 | ✅ |
| 10 | 审计落库 | `ethos_audit.db` 有 `memory.read/u2` | ✅ |

---

## 5. 风险与注意

1. **版本钉死**：`iii-engine` 保持 v0.11.2。v0.11.6 升级是独立工作项（需先重构为 sandboxed worker），本次不碰。
2. **SSE 透传**：3112 是 stream，网关必须透传 `text/event-stream`，不能缓冲或转 JSON（`StreamingResponse` 已处理）。
3. **token 来源**：ethos 版**无需签发渠道**——Tatha 运行时 `SystemMinter` 自动签发 `svc:tatha`（§1.5），
   外部调用方（如需）用 `/v1/admin/tokens` 超管 mint 或外部签发方。
4. **审计库位置**：`data/ethos_audit.db`，随容器数据卷持久化；旧 `tenet_audit.db` 若存在会自动迁移保留。
5. **黑盒边界**：网关只做认证/转发，不理解 iii 内部协议；引擎路由（如 `/v1/memories/search`）由调用方
   与引擎约定，网关 `/{path:path}` 全透传，路由变更无需改网关。
6. **Docker 跨盘挂载**：Windows 下 `D:/...` bind mount 依赖 Docker Desktop 共享驱动器；
   不可用则宿主侧直接跑 uvicorn（推荐，代码零差异）。
