# 格契端口真源提纲

> **地位**：本页 + `contracts/*.v1.json` 是 GFCC / 格契对外能力的**契约真源**。实现向它适配；改能力先改契约，再改代码。  
> **方法**（学自四份，不抄产品字段）：Steedar CONTRACT（契约权威、先改真源）；ethos 网关协议（定义方 vs 复刻方、`sub` 为 uid、deny-by-default）；Tatha 单入口（一个 Ask 信封、内部可换）；Agent Runtime 槽位（`llm/tools/session/policy/store`，模式 = 插件清单）。共识课：阈值 + **双向确认**，「有结果」不是成功。  
> **产品轴**：Genesis · Fellowship · Consensus · Circle。交付**体系与能力**；数据是使用方的，首次为空。

## 0. 权威层级

| 层 | 路径 | 服从关系 |
|---|---|---|
| **L0 真源** | 本页 · `contracts/*.v1.json` | 实现、演示栈、文档示例都向它适配 |
| **L1 内核** | ethos 验证 · `POST /v1/ask` 信封 · 五槽 | 只认端口接口，不认服务名 |
| **L2 默认组合** | kernel + 四个一等端口（stub 合法） | 空数据合法 |
| **L3 可选画像** | `modes/profile.demo.yaml` | 可卸载；**不得**进入 L0 必选项 |

**变更顺序**：改 JSON → 改本页 → 改分发/适配器 → 改调用方。禁止为迁就现有 JobFirst intent 表改契约。

## 1. 内核（默认常开）

- **单入口**：`POST /v1/ask`。用户只交需求；解析与分发是内部事。信封见 `contracts/ask.envelope.v1.json`。
- **信封稳定**：`AskRequest { message, context }` → `AskResponse { port, status, result, suggestions }`。内部换实现不换信封。`intent` 仅作弃用别名，映射到 `port`。
- **ethos 纯验证者**：验签 / 鉴权 / 配额 / 审计，**不签发**。`sub` 是唯一 uid 桥梁。未认证、uid 空、scope 未列、配额后端不可达 → 拒绝（401 / 403 / 429）。档位 `free/basic/pro/admin` 只管配额，不替代身份。
- **八角梯**（JWT `roles` + `permissions`，**不是**八个微服务）：`observer → participant → experimenter → proposer → steward → organizer → actor → petitioner`（旁观 → 参与 → 尝试 → 提议 → 主理 → 组织 → 行动 → 提案）。升降应有 Dual / CoCo 证据；管理员开关只作运维例外。契约：`contracts/roles.v1.json`。
- **五槽**：`llm | tools | session | policy | store`。模式 = 槽位上的插件清单。`tools ≠ 某家 RAG`；`store ≠ 某家记忆引擎`。

## 2. 一等端口（格契默认，分发只认接口）

| 端口 | 契约 | 语义 | 明确不是 |
|---|---|---|---|
| **identity** | `identity.v1.json` | PPI：价值观、能力轨迹、承诺随贡献长；`sub` 绑档案 | 不是付费档；简历/MBTI 最多作材料插件 |
| **memory** | `memory.v1.json` | Dual 七库：**议题 / 行动 / 事件 / 方法 / 人 / 组织 / 资源** | 不是个人备忘；iii / Mem0 / Zep 都是 `store` 适配器 |
| **consensus** | `consensus.v1.json` | 共议：分数 ≥ 阈值 **且** 双向确认才 `verified` | 不是求职/相亲匹配；失败不得自动成功 |
| **contribution** | `contribution.v1.json` | CoCo：认定 → 兑现 → 可申诉 | 不是积分主叙事；不先上链 |

默认 `tools` 清单 = 上表四端口。DemoPeter、agentmemory/iii、job / poetry / credit / mbti **不得**出现在默认清单。

## 3. 可选组合（可卸载）

`modes/profile.demo.yaml`：把现仓 JobFirst / DemoPeter / iii 登记为**接入样例**。内核 dispatch 不得 import 这些实现；只经 registry 绑定。卸画像 = 默认格契栈仍可启动（端口可 stub）。

## 4. 不变量

1. **契约是权威**；实现适配契约，不是反过来。
2. **JSON 是协议定义方**；Python / Rust / Go 都是复刻方。
3. **内部实现可替换**；外信封与四端口语义不变。
4. **有扫描结果 / 有写入回执 ≠ 共识成功**；未双向确认禁止当作完成。
5. **数据是用户的**；记忆与知识库启动为空。
6. **JobFirst 意图表不是重构脊柱**。

机器可读注册表：`contracts/registry.v1.json`。
