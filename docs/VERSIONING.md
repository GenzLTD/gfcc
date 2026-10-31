# 契约版本策略

> 契约是权威，就必须回答权威怎么变。价值层 [`docs/vision.md`](vision.md) 约束本文件。  
> **现状锚点（2026-11-01）**：L0 契约家族 **1.6.0**（新增独立 `invitation.v1.json`；外部身份以 namespaced `(issuer, subject)` 映射到规范 `principal.sub`；邀请按 audience/purpose 隔离并由已认证 redeemer 原子兑换；设备证明只定义策略与一次性 challenge/proof 扩展形状）。`identity.value_axes` 仍在；写口 `identity.value_axes.write` 只属于 `planetx` / `system`；`job_match` 只有读口，职位分区间见 `job_match.v1.json`，`writes_to: none`。内核软件版本仍是 **1.1.0**。信号家族 **1.1.0**（与 L0 分开；`value_axis_choice` 及既有 payload 语义不变）。当前 PWA 不实现硬件/可穿戴设备认证；硬件算法、密钥存储、设备登记及证明等级待设备方案定型。围坐 MVP 状态不因本次契约新增而改变。

## Semver（`contracts/*.json` 的 `version`）

| 变更 | 版本 | 例子 |
|---|---|---|
| 破坏性 | **主版本** | 删字段、改枚举语义、去掉端口、让算法/录像跳过 ack、把 parties 全员 ack 改成多数/法定人数/弃权规则 |
| 兼容新增 | **次版本** | 加字段、加端口、加 `status=partial`、新 `signal_type`（旧 payload 只追加、不改语义） |
| 文案/示例 | **修订号** | 注释、zh 标签 |

当前线：L0 **1.6.0**（`ask.envelope` + 五端口 + `roles` + `registry` + `job_match` + 联邦契约 `invitation`，该契约不加入默认五端口）。信号线（`signal.envelope` + `contracts/signals/`）**1.1.0**，与 L0 分家族，互不要求同号。内核软件版本仍是 **1.1.0**。`signal_type` 为 `personality_beacon`、`consensus_match`、`value_axis_choice`。

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
