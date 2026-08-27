# Phase2 Step3 — 信号契约与多方协调方案

> **状态：已收口（2026-08-24 G3 通过）**——G1 契约冻结 → G2 mock 并行 → G3 真端对接全部完成，DoD 六条全勾选（见第九节）。本文为契约定稿 + 历史协调记录，不再有未执行动作。
> **文档定位**：Step3（THOMAS ↔ GFCC 信号层对接）的契约草案 + 双团队分工协调方案
> **读者**：Mac 侧（Jason：THOMAS 三仓 + 契约起草）、Windows 侧（gfcc_kernel 实施）
> **前置状态**：Step1-2 已验收（llm→Ollama 语义分类、store→SQLite 持久化）；SurfaceZervi L1-L5 已验收（信封+HMAC+幂等样板）
> **创建日期**：2026-08-20 · 契约版本草案 signal.envelope **v1.0.0-draft**

---

## 一、Step3 要打通什么（拓扑）

```
┌────────────────────────── THOMAS 生态（Mac 侧）──────────────────────────┐
│                                                                          │
│  DemoPPI (Next.js)                     PlanetX (Flask)                   │
│    │ reputation_events                   │ 8题人格测评完成                │
│    │ consensus_match 写入                │ personality_type 写入          │
│    ▼                                     ▼                               │
│  [T2] egress ──consensus_match──► [T1] /v1/game/signal-ingest            │
│    │                                （验签+幂等+mission-complete）        │
│    │                                [T3] egress ──personality_beacon──►  │
│    │                                     └──────────► [T4] DemoPPI       │
│    │                                                  /api/signal/ingest │
│    │  （链A：THOMAS 内部桥 = 指南 T1-T6，约 4.5 人天）                     │
│    │                                                                     │
│    └────────────── fan-out 第二目的地（链B：对外摄入）────────────────────┼──┐
└──────────────────────────────────────────────────────────────────────────┘  │
                                                                               ▼
                                              ┌─────────────────────────────────┐
                                              │  GFCC kernel :5211 (Windows 侧) │
                                              │  [W1] POST /v1/signal-ingest    │
                                              │   验签 → 信封校验 → 幂等 → 路由   │
                                              │   consensus_match → consensus端口│
                                              │   personality_beacon → identity端口│
                                              │  [W2] signal_log 表（SQLite）    │
                                              └─────────────────────────────────┘
```

**两条链，一套信封：**

| 链 | 路径 | 信号 | 种子期状态 |
|----|------|------|-----------|
| 链A（内部桥） | DemoPPI ⇄ PlanetX | consensus_match / personality_beacon | Mac 侧 T1-T6 |
| 链B（对外摄入） | DemoPPI / PlanetX → GFCC | 同两种信号，fan-out 第二目的地 | Windows 侧 W1-W4 + Mac 联调 |

**关键协调点（本方案的核心价值）**：契约冻结（G1 门）之后，**链A 与链B 完全并行、互不等待**——Windows 团队用 mock 发送器自测 `/v1/signal-ingest`，不需要 THOMAS 真端在线；Mac 侧跑 T1-T6 内部桥，不需要 GFCC 在线。最后 G3 门一次对接即可。

**种子期不做**：GFCC → THOMAS 回写（格契共议结果反向影响 THOMAS 匹配）留到升级触发条件满足后。

---

## 二、统一信封 signal.envelope.v1

### 2.1 命名统一对照表（三处历史差异 → 一个标准）

三份历史文档对同一事物用了不同名字。**THOMAS 侧目前是零代码，改文档不改代码，零成本对齐**；GFCC kernel 的 signal-ingest 是新端点，直接按标准实现：

| 事物 | THOMAS 指南草案（2026-08-12） | SurfaceZervi 已验证实现 | **本方案统一标准** |
|------|------|------|------|
| 用户关联键 | `user_email_hash` | `user_id_hash` | **`user_id_hash`**（对齐已验证样板） |
| 数据体字段 | `data` | `payload` | **`payload`** |
| 签名 header | `X-Signal-Signature` | `X-Signature` | **`X-Signature`** |
| 信封时间戳 | `timestamp`（必填） | 无（payload 内 `generated_at`） | **`timestamp` 可选**，幂等不依赖它 |
| 入口路径 | `/v1/game/signal-ingest`（PlanetX） | `/v1/skills/ingest`（Tatha） | GFCC：**`/v1/signal-ingest`**；PlanetX/DemoPPI 内部路径沿用各自指南 |
| 共享密钥 | `SIGNAL_BRIDGE_SECRET` | `SIGNAL_BRIDGE_SECRET` | THOMAS 内部：`SIGNAL_BRIDGE_SECRET`；THOMAS↔GFCC：**`SIGNAL_INGEST_SECRET`**（与 ethos 的 `ETHOS_AUTH_SECRET` 严格区分） |

> `user_id_hash` 语义不变：`sha256(email.lower().trim())`，64 位小写 hex。只传 hash 不传明文。

### 2.2 信封字段规范

```json
{
  "signal_type": "consensus_match",
  "user_id_hash": "<sha256 64位hex>",
  "nonce": "<uuid4 hex，客户端生成>",
  "timestamp": "2026-08-20T09:30:00Z",
  "payload": { "……signal 契约完整对象……" }
}
```

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `signal_type` | ✅ | string | `consensus_match` \| `personality_beacon`（种子期两种，JSON Schema enum） |
| `user_id_hash` | ✅ | string | 跨平台关联键，64 hex |
| `nonce` | ✅ | string | 幂等键成分，uuid4 |
| `timestamp` | ⬜ | string | ISO 8601 UTC，仅审计用途 |
| `payload` | ✅ | object | 由各自 signal 契约严格定义 |

**additionalProperties: false**（与 ask.envelope.v1 同等严格度）。

### 2.3 与 ask.envelope.v1 的关系（不是替代，是并列）

| | ask.envelope.v1 | signal.envelope.v1 |
|---|---|---|
| 入口 | `POST /v1/ask` | `POST /v1/signal-ingest` |
| 性质 | **人机**（成员对话） | **机机**（系统间事件） |
| 认证 | ethos JWT（`ETHOS_AUTH_SECRET`） | HMAC raw body（`SIGNAL_INGEST_SECRET`） |
| 计量 | ethos 配额/审计 | signal_log 落库即审计 |

信号**不走** `/v1/ask`：不污染对话语义、不占成员配额、不经过 llm 槽语义分类（signal_type 是确定性的，无需 LLM 猜）。

---

## 三、两种信号的 payload 契约（草案）

### 3.1 consensus_match.v1（DemoPPI 产生）

```json
{
  "match_score": 0.87,
  "shared_tags": ["growth_mindset", "remote_work", "startup"],
  "peer_id_hash": "<对端用户的 user_id_hash>",
  "source": "demoppi",
  "generated_at": "2026-08-20T09:30:00Z"
}
```

| 字段 | 必填 | 约束 |
|------|------|------|
| `match_score` | ✅ | number 0..1（Jaccard 相似度输出） |
| `shared_tags` | ✅ | string[]，1..10 项 |
| `peer_id_hash` | ✅ | 64 hex（原指南草案 `peer_email_hash` 更名） |
| `source` | ✅ | 固定 `"demoppi"` |
| `generated_at` | ⬜ | ISO 8601 |

### 3.2 personality_beacon.v1（PlanetX 产生）

```json
{
  "personality_type": "INTJ",
  "traits": [
    { "name": "energy_orientation", "score": 0.72 }
  ],
  "assessment_score": 95,
  "source": "planetx",
  "generated_at": "2026-08-20T09:30:00Z"
}
```

| 字段 | 必填 | 约束 |
|------|------|------|
| `personality_type` | ✅ | MBTI 16 型之一 |
| `traits` | ⬜ | `{name, score}[]`，原始维度分 |
| `assessment_score` | ⬜ | number（人格互补/同频评分输出） |
| `source` | ✅ | 固定 `"planetx"` |
| `generated_at` | ⬜ | ISO 8601 |

### 3.3 隐私与红线

- payload **只传 hash 与类型化结果**：不传明文 email、不传原始答题数据、不传对端身份信息
- **AI 红线延续**：信号必须源自**用户真实动作**（确认匹配、完成测评），不得由 AI 自证产生；`source` 字段用于追溯产生方

---

## 四、传输与安全规范（逐项对齐 Tatha 样板）

| 项 | 规范 | 样板出处 |
|----|------|---------|
| 签名算法 | `HMAC-SHA256(SIGNAL_INGEST_SECRET, raw_body)`，hex 小写 | Tatha `/v1/skills/ingest` |
| 签名传递 | header `X-Signature` | 同上 |
| 免签模式 | secret 未配置 → dev 免签 + 日志 WARNING（仅本地联调），生产必须配置 | 同上 |
| 幂等键 | `(signal_type, user_id_hash, nonce)` 数据库 UNIQUE 约束 | skills_evidence 表 |
| 验签失败 | `401 {"code": "invalid_signature"}`，不泄露原因 | 同上 |
| 信封不符 | `422 {"code": "invalid_envelope"}` | 同上 |
| 未知 signal_type | `422 {"code": "unsupported_signal"}` | 同上 |
| 首次成功 | `200 {"status": "stored", "signal_id", "port"}` | 参照 stored 语义 |
| 重复摄入 | `200 {"status": "duplicate", "signal_id"}`（返回已有 id，不重复处理） | 同上 |
| 限流 | 建议 10 req/min per user_id_hash | THOMAS 指南 |
| best-effort egress | 失败重试 3 次指数退避（1s/2s/4s），最终失败记日志不阻塞主流程 | THOMAS 指南 T2 |

---

## 五、分工对照表（核心）

### 5.1 Windows 侧（gfcc_kernel，编号 W1-W4）

| 编号 | 任务 | 验收标准 | 依赖 |
|------|------|---------|------|
| W1 | 新增 `POST /v1/signal-ingest`：验签（`SIGNAL_INGEST_SECRET`，留空=dev 免签+WARNING）→ Pydantic 严格信封校验 → 幂等 → 按 signal_type 路由 | 单测覆盖：合法信封 200 stored；缺字段/多余字段 422；验签失败 401；免签模式 WARNING | 本文档 G1 冻结 |
| W2 | `signal_log` 表（SQLite，经 store 槽）：参照 Tatha `skills_evidence` 结构（signal_type / user_id_hash / nonce / payload / signal_id / created_at），UNIQUE 三元组 | 重启进程后历史信号可查；重复 nonce 返回 duplicate | W1 |
| W3 | 端口路由：`consensus_match` → consensus 端口（作为共议 score 证据）；`personality_beacon` → identity 端口（画像输入）。端口仍是 stub 也先落 signal_log | 响应含正确 `port` 字段；两端口 stub 收到调用记录 | W1 |
| W4 | mock 发送器 + E2E：`scripts/mock_signal_sender.py`（构造信封+HMAC 签名，发 5211），覆盖 stored/duplicate/401/422/重启存活 | E2E 全绿，脚本入库可复跑（对标 SurfaceZervi `eval_skill_proof.py` 的可复跑证据风格） | W1-W3 |

**样板文件**（Mac 侧已验证，Windows 直接对照）：
- 信封+验签+幂等实现：`SurfaceZervi/GitHub/Tatha/src/tatha/api/app.py` 的 `/v1/skills/ingest`（约 300-368 行）
- 契约防漂移三约定：`SurfaceZervi/GitHub/Tatha/docs/skill_evidence_ingest.md`

### 5.2 Mac 侧（THOMAS 三仓，编号 M1-M3，含指南 T1-T6）

| 编号 | 任务 | 验收标准 | 依赖 |
|------|------|---------|------|
| M1 | 契约入库：本方案附录三份 JSON Schema 起草为 `contracts/signal.envelope.v1.json` + `contracts/signals/consensus_match.v1.json` + `contracts/signals/personality_beacon.v1.json`（v1.0.0，不影响现有八份 1.1.0 契约） | 双方 review 通过后入库；THOMAS 指南补一节"命名统一勘误" | 本文档 G1 冻结 |
| M2 | mock 接收端：复用 `Tractor/scripts/mock_signal_ingest.py` 模式，Mac 本地验证 DemoPPI/PlanetX egress 格式 | 本地自测闭环（指南 T5） | M1 |
| M3 | 指南 T1-T6 原样实施 + egress fan-out 扩展：T2（DemoPPI consensus_match egress）、T3（PlanetX personality_beacon egress）增加第二目的地 `GFCC_SIGNAL_INGEST_URL`；T1/T4 ingress 按统一信封命名 | 指南 T5/T6 验收口径；fan-out 两目的地都收到 | M1、M2 |

### 5.3 依赖与并行关系

```
G1 契约冻结（双方 review 本文档）
 ├──► Windows W1→W2→W3→W4（mock 自测，不等 THOMAS）
 └──► Mac M2→M3（内部桥 + fan-out，不等 GFCC）
G3 真端对接：DemoPPI/PlanetX egress 切到 5211 真端 → signal_log 落库 → 双方验收记录入库
```

**总计约 8 人天**：Windows ~2.5 人天（W1-W4），Mac ~5.5 人天（M1-M3，含 T1-T6 的 4.5 人天）。并行推进，日历时间约 2 周。

---

## 六、节奏与验收门

| 门 | 内容 | 通过标准 |
|----|------|---------|
| **G1 契约冻结** | 双方 review 本方案第二~四节；Mac 入库三份契约 JSON | Windows 团队书面确认（gitee issue 或群里回复"契约无异议"）；此后字段变更走版本号，不许悄悄改 |
| **G2 mock 并行** | Windows W4 E2E 全绿；Mac M2/M3 本地自测闭环 | 各自提交可复跑脚本 + 测试记录 |
| **G3 真端对接** | egress 切 5211 真端，跑通两种信号各一条 | signal_log 有真记录；重放同 nonce 返回 duplicate；错误签名 401。对标 SurfaceZervi L4-L5 |

---

## 七、密钥矩阵与环境变量

| 密钥/变量 | 配置在 | 用途 |
|-----------|-------|------|
| `SIGNAL_BRIDGE_SECRET` | DemoPPI + PlanetX | 链A 内部桥 HMAC |
| `SIGNAL_INGEST_SECRET` | DemoPPI + PlanetX + gfcc_kernel | 链B 对外摄入 HMAC（与 `ETHOS_AUTH_SECRET` 是两把不同的钥匙） |
| `GFCC_SIGNAL_INGEST_URL` | DemoPPI、PlanetX | fan-out 第二目的地，如 `http://<host>:5211/v1/signal-ingest` |
| `PLANETX_SIGNAL_INGEST_URL` | DemoPPI | 指南原有，链A |
| `DEMOPPI_SIGNAL_INGEST_URL` | PlanetX | 指南原有，链A |

密钥管理沿用现有纪律：不进仓库、`.env` + `.gitignore`、生产环境变量注入。

---

## 八、种子期明确不做（防止协调范围膨胀）

| 不做 | 原因 |
|------|------|
| GFCC → THOMAS 回写信号 | 单向摄入已够验证价值；回写等升级触发 |
| 信号路由中间件 / 总线 | 两种信号、三个入口，点对点 webhook 够用 |
| signal_type 枚举扩展 | 等 > 5 种再议 |
| 链上锚定 / SBT | 用户量不够，纯成本 |
| 统一身份层 | email hash 一行代码够用（> 500 重叠用户再议） |

---

## 九、Step3 完成定义（DoD）

- [x] 三份契约 JSON 入库 `contracts/`（v1.0.0），双方确认
- [x] gfcc_kernel `/v1/signal-ingest` 上线 5211，W4 E2E 全绿
- [x] THOMAS 内部桥 T1-T6 联调通过（指南 T6 口径；2026-08-14 Mac 链 A）
- [x] 真信号从 DemoPPI（consensus_match）和 PlanetX（personality_beacon）到达 5211，`signal_log` 落库可查
- [x] 三个安全用例通过：重放 duplicate / 错误签名 401 / 免签模式 WARNING（W4 + 联调探活）
- [x] 双方验收记录入库 `docs/`（G3：[`docs/reviews/G3_真端对接验收_2026-08-24.md`](reviews/G3_真端对接验收_2026-08-24.md)）

---

## 附录 A：信封 JSON Schema（草案全文，G1 冻结后入库）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GFCC Signal Envelope v1",
  "version": "1.0.0",
  "description": "Machine-to-machine signal entry. Sibling of ask.envelope.v1 (human dialogue). Signals are user-action-generated facts, never AI self-attestation.",
  "entry": "POST /v1/signal-ingest",
  "auth": {
    "verifier": "hmac_raw_body",
    "header": "X-Signature",
    "secret_env": "SIGNAL_INGEST_SECRET",
    "unauthenticated": 401
  },
  "request": {
    "type": "object",
    "required": ["signal_type", "user_id_hash", "nonce", "payload"],
    "additionalProperties": false,
    "properties": {
      "signal_type": {
        "type": "string",
        "enum": ["consensus_match", "personality_beacon"]
      },
      "user_id_hash": {
        "type": "string",
        "pattern": "^[a-f0-9]{64}$",
        "description": "sha256(email.lower().trim())"
      },
      "nonce": {
        "type": "string",
        "minLength": 8,
        "description": "client-generated unique value, uuid4 hex; idempotency key component"
      },
      "timestamp": {
        "type": "string",
        "format": "date-time"
      },
      "payload": { "type": "object" }
    }
  },
  "idempotency": {
    "unique_key": ["signal_type", "user_id_hash", "nonce"],
    "duplicate": "200 {status: duplicate, signal_id}"
  },
  "errors": {
    "401": "invalid_signature",
    "422": "invalid_envelope | unsupported_signal | user_id_mismatch"
  }
}
```

## 附录 B：与 SurfaceZervi 样板的逐项对照

| 项 | SurfaceZervi（Guibu↔Tatha） | 本方案（THOMAS↔GFCC） | 复用/变化 |
|----|------|------|------|
| 信封字段 | signal_type / user_id_hash / nonce / payload | 相同 + 可选 timestamp | 复用 |
| HMAC | X-Signature, raw body, hex 小写 | 相同 | 复用 |
| 免签模式 | 未配置 secret → dev 免签 | 相同 | 复用 |
| 幂等 | SQLite UNIQUE 三元组 | 相同（signal_log 表） | 复用 |
| 错误码 | 401/422 语义表 | 相同 | 复用 |
| 信号类型 | skill_proof | consensus_match / personality_beacon | 新增（产品域不同） |
| 契约治理 | Guibu 真源 + 副本 + 防漂移三约定 | gfcc `contracts/` 真源（Mac 起草、双方 review） | 模式复用 |
| 验收节奏 | L1-L5（mock 先行再切真端） | G1-G3（契约冻结→mock 并行→真端对接） | 模式复用 |

---

_本方案由 Mac 侧起草（2026-08-20）。**G1 已冻结**（2026-08-24，见 [`docs/reviews/G1_契约确认_2026-08-24.md`](reviews/G1_契约确认_2026-08-24.md)）；此后字段变更走契约版本号。_
