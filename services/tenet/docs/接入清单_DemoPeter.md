# DemoPeter 接入 Ethos 改造清单（已落地）

> 目标：DemoPeter（szpeter2026 知识库，Flask 5220）接入 ethos 的 `security`（认证/鉴权/审计），
> 同时**默认保持纯本地零登录体验**。
> 原则：无 `ETHOS_AUTH_SECRET` 时自动 Stub 放行；配置密钥后自动进入 HMAC 严格模式。
>
> **迁移说明**：本文档由 tenet 版迁移而来（tenet → ethos，`TENET_AUTH_SECRET` → `ETHOS_AUTH_SECRET`，
> `init_security(auth=..., audit=...)` → `init_security(secret=..., tier_policy=..., audit_db=...)`）。
> 安全语义与 Tatha（ethos 接入）完全对齐：同一 secret、同一档位键、同一审计结构（网关协议 §1/§4）。

## 0. 现状盘点

| 项目 | 现状 |
|---|---|
| 依赖管理 | `requirements.txt`（无 pyproject，非 uv 工程） |
| 入口 | `static/src/web_dashboard.py`（Flask）、`static/src/mcp_server.py`（MCP，Agent 接入）、`static/src/kb_service.py`（服务层） |
| 配置 | `config/settings.py` + `.env` |
| 路由 | 30 个 `@app.route`（页面 5 + 业务 API 25） |

## 1. 工程层：依赖接入（已落地）

- [x] `requirements.txt` 追加本地路径依赖：
  ```
  ethos @ file:///D:/surface-zervi/GitHub/szjason72/ethos
  ```
- [x] `pip install -e D:/surface-zervi/GitHub/szjason72/ethos` 后验证 `import ethos`

## 2. Security 接入（已落地）

### 2.1 新增 `static/src/ethos_bootstrap.py`（已创建）

核心内容：

```python
TIER_POLICY = {
    "search": "free",        # 数据读取 / 列表 / 索引检索
    "rag.query": "pro",      # RAG 问答 / 流式 / 报告生成
    "memory.write": "pro",   # 导入 / 上传 / 删除 / 索引扫描
    "admin": "admin",        # 重置 / 清空类管理操作
}

def get_security():          # 惰性单例
    return init_security(
        secret=os.getenv("ETHOS_AUTH_SECRET") or None,   # 空 → Stub 放行（本地零登录）
        tier_policy=TIER_POLICY,
        audit_db=str(config.DB_DIR / "ethos_audit.db"),  # ethos 统一结构，旧 tenet 表自动迁移（§4.4）
    )

def init_ethos_guard(app):   # before_request 统一拦截 /api/*
    ...
```

豁免（直通不鉴权）：`/api/health/*`、`/api/system/check`、`/api/webhook/gitea`（已有 Gitea HMAC）、
`/auth/outlook/*`（非 `/api` 前缀天然豁免）。

### 2.2 路由改造矩阵（`static/src/web_dashboard.py`，已挂载）

`CORS(app)` 之后一行 `init_ethos_guard(app)`，按路径自动映射 action：

| 路由 | 改造 | action（策略档位） |
|---|---|---|
| `/`、`/documents`、`/query`、`/reports`、`/d-search` | 页面豁免 | — |
| `/api/stats`、`/api/documents`、`/api/documents/<id>` GET | 鉴权 | `search`（free） |
| `/api/rag/query`、`/api/rag/stream` | 鉴权+审计 | `rag.query`（pro） |
| `/api/reports/generate` | 鉴权+审计 | `rag.query`（pro） |
| `/api/reports/queries` | 鉴权 | `search`（free） |
| `/api/documents/import`、`/api/documents/upload` | 鉴权+审计 | `memory.write`（pro） |
| `/api/documents/<id>` DELETE | 鉴权+审计 | `memory.write`（pro） |
| `/api/d-index/search` | 鉴权 | `search`（free） |
| `/api/d-index/scan`、`/api/d-index/clear`、`/api/d-index/checkpoint/reset` | 鉴权+审计 | `admin` |
| `/api/d-index/checkpoint` GET/DELETE、`/api/d-index/stats`、`/api/d-index/projects` | 鉴权 | `search`（free） |
| `/api/health/*`、`/api/system/check` | 豁免 | — |
| `/api/webhook/gitea` | 豁免（已有 Gitea HMAC 签名） | — |
| `/auth/outlook/login`、`/auth/outlook/callback` | 豁免（OAuth 回调） | — |

> 实现：`before_request` 钩子按路径前缀统一拦截 `/api/*`（排除豁免清单），
> 认证失败 401、档位不足 403，审计 `sec.audit(action, principal=..., resource=path)`。

### 2.3 MCP 接入（`static/src/mcp_server.py`）— 待办（本次未做）

- [ ] MCP 走 stdio（Agent 本地直连），无 HTTP 头：认证改为**进程级启动校验**
  ```python
  token = os.getenv("ETHOS_AUTH_TOKEN", "")
  ctx = get_security().verify(token)
  # Stub 模式（无 ETHOS_AUTH_SECRET）自动放行 local-dev；HMAC 模式无 token 拒绝启动
  ```
- [ ] 四个工具按 action 鉴权：`kb_stats`→`search`、`kb_search`→`search`、`kb_ask`→`rag.query`、`kb_import`→`memory.write`
- [ ] `kb_ask` / `kb_import` 执行前后 `sec.audit(...)`

### 2.4 前端配套（可选，研讨点）

- [ ] 浏览器面板调用 `/api/*` 需携带 token：登录页用 ethos 验签端之外的签发方（Tatha SystemMinter / Go / Rust）签发，存 `localStorage`
- [ ] 或维持"页面豁免 + API 鉴权"：页面里嵌入启动时生成的短期 token（本地单机可接受）

## 3. Resolver 接入（独立工作项，不在本次范围）

跨平台路径收敛（`config/resources.json`、消灭 `D:/` 字面量）与 ethos 无关，见原 tenet 清单 §3，暂缓。

## 4. 验证清单（已通过，见 `tests/test_ethos_guard.py` 10 项）

| # | 场景 | 预期 | 结果 |
|---|---|---|---|
| 1 | 无 `ETHOS_AUTH_SECRET` 启动，调 `/api/rag/query` 无 token | 200（Stub 放行，本地体验不破坏） | ✅ |
| 2 | 设置 `ETHOS_AUTH_SECRET` 后，无 token 调 `/api/rag/query` | 401 | ✅ |
| 3 | 签发 `tier=free` token 调 `/api/rag/query` | 403（rag.query 需 pro） | ✅ |
| 4 | 签发 `tier=pro` token 调 `/api/rag/query` | 200 | ✅ |
| 5 | 签发 `tier=admin` token（Tatha 系统令牌 `svc:tatha`）调 `/api/rag/query` | 200 | ✅ |
| 6 | admin token 调 `/api/d-index/clear` | 放行（403 仅对非 admin） | ✅ |
| 7 | `/api/health/config` 无 token | 200（豁免） | ✅ |
| 8 | 审计库 | `db/ethos_audit.db`（ethos 统一结构） | ✅ |

## 5. 风险与注意

1. **本地体验取舍**：默认 Stub（admin 档位，全部放行）保持零登录；只有部署对外暴露时才配 `ETHOS_AUTH_SECRET`。
2. **OAuth 与 Webhook 豁免**：Outlook 回调、Gitea 签名不能误拦，before_request 白名单要精确。
3. **CORS**：当前 `flask-cors` 全开，前端携 token 的改造是独立工作项（见 2.4），不阻塞后端。
4. **后台任务**：`d_indexer` 定时扫描（凌晨 3 点）不经 HTTP，不撞认证；如需审计可在调度入口补 `sec.audit`。
5. **审计库位置**：`db/ethos_audit.db`，与现有 `szpeter2026.db` 一起备份；旧 `tenet_audit.db` 若存在会在首次启动时自动迁移（ethos §4.4）。
