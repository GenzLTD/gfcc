# ethos

跨平台共享 AI 管道内核 —— tenet 的演进版。**纯 Python 库，被消费方进程内 import**（同 `tenet`）。

## 定位与三项决策

| 决策 | ethos 的实现 |
|---|---|
| **纯验证者** | `security` 只验签解析身份（标准 JWT HS256，兼容 Rust/Go 两套 Claims），**不签发令牌** |
| **库内配额（可插拔远程）** | `QuotaManager` 默认 `LocalQuotaBackend`（内存+可选持久化），可换 `RemoteQuotaBackend`（HTTP） |
| **本地审计（可选上报）** | `Auditor` 默认 SQLite/JSONL 落库，可挂 `HttpReporter` 异步上报中心 |

## 安装

```bash
# 消费方项目内（Tatha / DemoPeter / agentmemory）
pip install -e D:/surface-zervi/GitHub/szjason72/ethos
# 可选依赖
pip install -e "D:/surface-zervi/GitHub/szjason72/ethos[consul,remote-quota]"
```

## 快速开始：security

```python
from ethos.security import init_security, QuotaLimit

sec = init_security(
    secret="<HMAC密钥>",                    # 留空 → StubVerifier 本地联调放行
    tier_policy={"rag.query": "pro"},
    quota_limits={"rag.query": QuotaLimit("rag.query", daily=100)},
    audit_db="logs/audit.db",
)

ctx = sec.verify(token)                     # 认证（验签）
if not ctx.ok:
    return 401

sec.require(ctx, "rag.query")               # 鉴权（tier）
state = sec.consume_quota(ctx, "rag.query") # 配额（库内计数）
sec.audit("rag.query", ctx)                 # 审计（本地落库）
```

### 环境变量

| 变量 | 作用 |
|---|---|
| `ETHOS_AUTH_SECRET` | HS256 密钥（缺省 → Stub 模式） |
| `ETHOS_AUDIT_DB` | 审计 SQLite 路径 |
| `ETHOS_AUDIT_REPORTER_URL` | 可选：审计上报端点 |
| `ETHOS_QUOTA_URL` | 可选：远程配额后端 |
| `ETHOS_QUOTA_PERSIST` | 本地配额持久化 JSON 路径 |

## 快速开始：resolver

```python
from ethos.resolver import init_resolver

rsl = init_resolver("config/resources.json")
corpus = rsl.path("poetry_corpus")      # 跨平台绝对路径
auth_url = rsl.service("auth")          # 服务 URL（静态表/Consul）
```

## 目录结构

```
src/ethos/
├── models.py            # Principal / AuthContext / Quota / AuditEvent
├── registry.py          # 可插拔后端注册中心（线程安全）
├── security/
│   ├── verifier.py      # TokenVerifier（HS256 验签 / Stub）
│   ├── authorizer.py    # TierAuthorizer / PermissionAuthorizer
│   ├── quota.py         # QuotaManager + Local/Remote Backend
│   ├── auditor.py       # Auditor + SQLite/JSONL/Null
│   └── reporters.py     # HttpReporter（异步上报）
└── resolver/
    ├── config.py        # resources.json 加载 + ${VAR} 展开
    ├── resource_locator.py  # 逻辑资源名 → 绝对路径
    └── service_locator.py   # 静态表 / Consul / TTL 缓存
```

## 与 Rust 网关的对接

ethos 是"协议定义方"；对外高并发入口由 **Rust 网关**复刻协议（axum+tokio），不 import ethos：

```
外部调用方 → 【Rust 网关】(验签/鉴权/审计/配额) → 【Python 服务】(import ethos)
```

协议要点见 **`docs/网关协议.md`**（令牌 / 签发职责 / 鉴权 / 配额 / 审计五段 + Rust 网关复刻 checklist）：HS256 JWT、`sub` 为唯一 uid 桥梁、档位键 `tier/plan/level`、`/quota` 计数语义、审计字段 `action/ts/user_id/tier/resource/meta`、旧审计表自动迁移（§4.4）、签发职责（§1.5：运行时系统自动签发 + 超管例外，业务接口不签发）。
