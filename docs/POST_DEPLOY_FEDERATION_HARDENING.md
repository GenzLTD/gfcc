# 部署后联邦硬化（格契侧摘录）

> **地位**：备忘。完整待办在 THOMAS [`docs/POST_DEPLOY_RESILIENCE_BACKLOG.md`](/Users/jason/THOMAS/docs/POST_DEPLOY_RESILIENCE_BACKLOG.md)。  
> **纪律**：单机云端部署完成前 **不实施**。不改冻结契约；硬化若要动信封，必须先走 [`VERSIONING.md`](VERSIONING.md)。  
> **记录日期**：2026-08-25。

部署形态（已拍板）：一台高性能机；`:5211` 只绑回环；公网只出注册和日常站。格契 Ask / signal-ingest **不对路人开放**。

## 部署后才做的格契相关项

从 THOMAS 清单 R1–R6 抽出内核侧：

| 来源 | 格契动作 | 完成 |
|------|----------|------|
| R1 | ingest 失败不得反向拖垮 THOMAS 注册；URL 空 / 内核挂 = 对端 no-op | ☐ |
| R2 | 消费侧可按 nonce 查 `signal_log`；出站重放是 THOMAS 发件箱，内核保持幂等 `duplicate` | ☐ |
| R3 | 验签 + 落 `signal_log` 后快回 200，再路由 identity/consensus；过旧 `timestamp` 是否 401 → 先改契约再改代码 | ☐ |
| R4 | 内测 `SIGNAL_INGEST_SECRET` 双活轮换；留空免签禁止上云；≠ `ETHOS_AUTH_SECRET` | ☐ |
| R5 | `signal_log` 只追加；新语义新 `signal_type`；禁止补丁改旧 payload | ☐ |
| R6 | 内核进程独立限额与备份 `data/memory.db`（或 `SIGNAL_LOG_DB`）；Nginx 不把 5211 暴露到 443 以外的 Host | ☐ |

G6（circle / consensus / contribution 走完真人剧本）仍见 [`MVP_资源配置清单.md`](MVP_资源配置清单.md)，**不是**本页硬化范围。

## 不要做

同机读 THOMAS 数据库；为方便给内核做公网 Host；把联调 `dev-signal-secret-*` 当内测密钥长期使用。
