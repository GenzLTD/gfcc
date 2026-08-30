# 格契端口真源提纲

> **价值层（先读）**：[docs/vision.md](../vision.md) —— 为谁而生、成什么算成。迷茫时：[围坐初心](../reviews/围坐初心_不是聊天室_防自嗨_2026-08-30.md)。本页是机器可执行的契约层。  
> **地位**：本页 + `contracts/*.v1.json` 是 GFCC / 格契对外能力的**契约真源**。实现向它适配；改能力先过价值层，再改契约，再改代码。  
> **方法**（学自四份，不抄产品字段）：Steedar CONTRACT（契约权威、先改真源）；ethos 网关协议（定义方 vs 复刻方、`sub` 为 uid、deny-by-default）；Tatha 单入口（一个 Ask 信封、内部可换）；Agent Runtime 槽位（`llm/tools/session/policy/store`，模式 = 插件清单）。共识课：阈值 + **双向确认**，「有结果」不是成功。  
> **产品轴**：Genesis · Fellowship · Consensus · Circle。交付**体系与能力**；数据是使用方的，首次为空。

## 0. 权威层级

| 层 | 路径 | 服从关系 |
|---|---|---|
| **L-1 价值层** | [`docs/vision.md`](../vision.md) | 不参与执行；**约束一切变更**。先过「人是目的 / 成功判据」再改契约 |
| **L0 真源** | 本页 · `contracts/*.v1.json` | 实现、演示栈、文档示例都向它适配 |
| **L1 内核** | ethos 验证 · `POST /v1/ask` 信封 · 五槽 | 只认端口接口，不认服务名 |
| **L2 默认组合** | kernel + 五个一等端口（stub 合法） | 空数据合法。**实现对照（非契约，2026-08-30）**：sqlite 持久化 `memory_records` + `signal_log` + 圈态库 `circle_flow.db`（circle / consensus / 地板，重启不丢）；consensus 适配器含 `reject` / `withdraw` / `expire` / `expire_stale`；identity / session 仍内存 |
| **L3 可选画像** | `modes/profile.demo.yaml` | 可卸载；**不得**进入 L0 必选项 |

**谁是权威、谁是执行**：**gfcc = 契约层（真源）**；**Tatha = 实现层**（`POST /v1/ask` 的一个具体实现，可替换）。方法学来自 Tatha 单入口文档，不等于 Tatha 是真源。

**变更顺序**：过 L-1 → 改 JSON → 改本页 → 改分发/适配器 → 改调用方。禁止为迁就现有 JobFirst intent 表改契约。版本规则见 [`docs/VERSIONING.md`](../VERSIONING.md)。

## 1. 内核（默认常开）

- **单入口**：`POST /v1/ask`。用户只交需求；解析与分发是内部事。信封见 `contracts/ask.envelope.v1.json`。
- **信号入口**（并列，不是 Ask 的替代）：`POST /v1/signal-ingest`。机机事件；HMAC 验签；不占成员配额、不经 llm 槽。信封见 `contracts/signal.envelope.v1.json`（v1.0.0）；payload 见 `contracts/signals/`。种子期两种：`consensus_match` → consensus，`personality_beacon` → identity。
- **信封稳定**：`AskRequest { message, context }` → `AskResponse { port, status, result, suggestions }`。`status` 含 `partial`（半成功：已成功子操作不回滚，未成功可重试）。`intent` 仅作弃用别名，映射到 `port`。`dialog_mode`：`collaboration`（协作）或 `coach`（教练）。
- **ethos 纯验证者**：验签 / 鉴权 / 配额 / 审计，**不签发**。`sub` 是唯一 uid 桥梁。未认证、uid 空、scope 未列、配额后端不可达 → 拒绝（401 / 403 / 429）。档位 `free/basic/pro/admin` 只管配额，不替代身份。
- **八角梯**（JWT `roles` + `permissions`，**不是**八个微服务）：旁观 → 参与 → 尝试 → 提议 → 主理 → 组织 → 行动 → 提案。每级「新增的责任」见 `roles.v1.json` `ladder_logic`。升降应有 Dual / CoCo 证据；AI 观察只作辅助；管理员开关只作运维例外。
- **营造师**（与八角梯正交）：协作推进 / 赋能项目 / 在地连接 / 持续运营。角色管「能不能」，营造师管「擅长做什么」。
- **五槽**：`llm | tools | session | policy | store`。`llm` 是生成器，不是洞察层。洞察走 `memory.observe`（可 `observed_by: ai`）与共识 `score_evidence`。`tools ≠ 某家 RAG`；`store ≠ 某家记忆引擎`。

## 2. 一等端口（格契默认，分发只认接口）

| 端口 | 契约 | 语义 | 明确不是 |
|---|---|---|---|
| **circle** | `circle.v1.json` | 围坐容器：创建 / 加入 / 解散；记忆与共识的归属 | 不是隐式字符串；解散不删历史 |
| **identity** | `identity.v1.json` | PPI：价值观、能力轨迹、承诺、营造师标签；`sub` 绑档案 | 不是付费档；证据源白名单，无 `optional` |
| **memory** | `memory.v1.json` | Dual 七库：**议题 / 行动 / 事件 / 方法论价值 / 人 / 组织 / 资源**；人与 AI 均可观察 | 不是个人备忘；AI 观察不得静默改写 |
| **consensus** | `consensus.v1.json` | 共议：分数 ≥ 阈值 **且** 双向确认才 `verified`；评分必须带证据。1.2.0 加 `reject`/`withdraw`/`expire`（作废当前句，不改全员 ack） | 不是求职匹配；失败不得自动成功；确认必须是人 |
| **contribution** | `contribution.v1.json` | CoCo：认定 → 兑现 → 可申诉；兑现后可回写轨迹 | 不是积分主叙事；v1 不依赖链 |

默认 `tools` 清单 = 上表五端口。DemoPeter、agentmemory/iii、job / poetry / credit / mbti **不得**出现在默认清单。

## 3. 可选组合（可卸载）

`modes/profile.demo.yaml`：把现仓 JobFirst / DemoPeter / iii 登记为**接入样例**。内核 dispatch 不得 import 这些实现；只经 registry 绑定。卸画像 = 默认格契栈仍可启动（端口可 stub）。

## 4. 不变量（工程）

1. **契约是权威**；实现适配契约，不是反过来。价值层约束契约怎么变。
2. **JSON 是协议定义方**；Python / Rust / Go 都是复刻方。
3. **内部实现可替换**；外信封与一等端口语义不变。Tatha 可换。
4. **有扫描结果 / 有写入回执 ≠ 共识成功**；未双向确认禁止当作完成。
5. **数据是用户的**；记忆与知识库启动为空。
6. **JobFirst 意图表不是重构脊柱**。
7. **AI 可观察、不可替代承诺**；治理权不可买卖。
8. **v1 不依赖链**；链是远期可选层。

业务成功判据见 [vision.md](../vision.md)。机器可读注册表：`contracts/registry.v1.json`。
