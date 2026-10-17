# 契约版本策略

> 契约是权威，就必须回答权威怎么变。价值层 [`docs/vision.md`](vision.md) 约束本文件。  
> **现状锚点（2026-10-17）**：Ask / 五端口 **1.3.0**（兼容新增：过渡校验者 `zervi-auth`、模式 `gfcc.terminal`、store 适配器 `cortex-mcp` 与 pgvector 库 `gfcc`）。1.2.0 的 consensus `rejected`/`withdrawn` 仍在。信号家族仍冻在 **1.0.0**。管道层 + 拓扑层（P3 归档）已过；**围坐 MVP 未开**（人未齐，见 [`MVP_资源配置清单.md`](MVP_资源配置清单.md)）。本页管契约怎么变，**不管**招人、会场 UI、进程内存实现。

## Semver（`contracts/*.json` 的 `version`）

| 变更 | 版本 | 例子 |
|---|---|---|
| 破坏性 | **主版本** | 删字段、改枚举语义、去掉端口、让算法/录像跳过 ack、把 parties 全员 ack 改成多数/法定人数/弃权规则 |
| 兼容新增 | **次版本** | 加字段、加端口、加 `status=partial`、新 `signal_type`（旧 payload 只追加、不改语义） |
| 文案/示例 | **修订号** | 注释、zh 标签 |

当前线：Ask / 五端口 **1.3.0**（`ask.envelope` + `circle` / `identity` / `memory` / `consensus` / `contribution` + `roles` + `registry`）。信号线（`signal.envelope` + `contracts/signals/`）**1.0.0**，与 1.3.0 分家族，互不要求同号。种子期 `signal_type` 仅 `personality_beacon`、`consensus_match`。

## 变更流程

1. 过 **L-1**：[vision.md](vision.md) 的定位句与五条成功判据仍成立。
2. 改 JSON（先真源）。
3. 改 [ports/README.md](ports/README.md)。
4. 记入 [CHANGELOG.md](CHANGELOG.md)。
5. 再改适配器 / 调用方。

禁止为迁就 JobFirst intent 表或某个 vendor 实现倒改契约。

部署后的信封时间窗、新 `signal_type` 等硬化，见 [`POST_DEPLOY_FEDERATION_HARDENING.md`](POST_DEPLOY_FEDERATION_HARDENING.md)。**上机与 P3 已完成（2026-08-26 / 08-27），硬化可排期**；仍不改冻结契约。动信封必须先改本页 Semver，再改 JSON。例如：过旧 `timestamp` 是否 401（硬化 R3）= 先本页再改代码。

## 要 bump / 不要 bump

| 要走本页 | 不要走本页（实现债或产品落地） |
|---|---|
| 改 JSON 字段、枚举、必填、`$ref` | circle / consensus / identity / session **仍在进程内存**（重启丢围坐态；`memory_records` 与 `signal_log` 已进 SQLite） |
| 新 `signal_type` 或改旧 payload 语义 | 围坐专用网页未做；场次用视频开会 + 主持人发令牌 |
| 让分数/转写/AI 观察代替人类 ack | PlanetX 注册、Tatha `demo-token-*`、知识库 `:5220` |
| 把 ethos 从「纯验证者」改成签发方 | 招人、席位表、腾讯会议当说话场 |

红线（升主版本也不得破）：**ack 必须是人类 party 本人**；AI 不是 party；录像/转写最多当 `score_evidence` 附件，不能当 `consensus_verified`。

须走主版本、不得会务绕过：全员 ack 改多数或改阈值 = 破坏性主版本变更；会场切分、轮询、名单施工单都不得顺手改表决规则。

## 谁评审

契约变更须能回答：人还是目的吗？AI 有没有变成决策者？治理权有没有被卖掉？有结果是否仍不等于成功？
