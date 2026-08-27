# 部署后联邦硬化（格契侧摘录）

> **地位**：备忘。完整待办在 THOMAS [`docs/POST_DEPLOY_RESILIENCE_BACKLOG.md`](/Users/jason/THOMAS/docs/POST_DEPLOY_RESILIENCE_BACKLOG.md)。  
> **纪律**：~~单机云端部署完成前不实施~~ **部署已完成（2026-08-26 中央机验收 + 2026-08-27 P3 归档），本页可进入排期**。仍不改冻结契约；硬化若要动信封，必须先走 [`VERSIONING.md`](VERSIONING.md)。  
> **记录日期**：2026-08-25（2026-08-27 更新：部署完成，硬化可排期）。

部署形态（已拍板）：一台高性能机。现网 `:5211` 听 `0.0.0.0`（Docker `host.docker.internal` 需要），**安全组不放行**，公网超时；格契 Ask / signal-ingest **不对路人开放**。公网只出人网站（80/443）。

## 部署后才做的格契相关项

从 THOMAS 清单 R1–R6 抽出内核侧：

| 来源 | 格契动作 | 完成 |
|------|----------|------|
| R1 | ingest 失败不得反向拖垮 THOMAS 注册；URL 空 / 内核挂 = 对端 no-op | ☐ |
| R2 | 消费侧可按 nonce 查 `signal_log`；出站重放是 THOMAS 发件箱，内核保持幂等 `duplicate` | △ 内核可读（`scripts/query_signal_log.py` + UNIQUE 三元组）；THOMAS 发件箱重放未做 |
| R3 | 验签 + 落 `signal_log` 后快回 200，再路由 identity/consensus；过旧 `timestamp` 是否 401 → 先改契约再改代码 | ☐ |
| R4 | 内测 `SIGNAL_INGEST_SECRET` 双活轮换 | ☐ 轮换未做。**密钥本身已换内测值**（2026-08-26 联邦 L5）：发收同一把，≠ `ETHOS_AUTH_SECRET`，留空免签未上云 |
| R5 | `signal_log` 只追加；新语义新 `signal_type`；禁止补丁改旧 payload | △ 落库只追加已实现；新 `signal_type` 仍须先走 [`VERSIONING.md`](VERSIONING.md) |
| R6 | 内核进程独立限额与备份 `data/memory.db`（或 `SIGNAL_LOG_DB`）；Nginx 不把 5211 暴露到 443 以外的 Host | ☐ |

G6（circle / consensus / contribution 走完真人剧本）仍见 [`MVP_资源配置清单.md`](MVP_资源配置清单.md)，**不是**本页硬化范围。

## 不要做

同机读 THOMAS 数据库；为方便给内核做公网 Host；把联调 `dev-signal-secret-*` 当内测密钥长期使用。
