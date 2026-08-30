# MVP 内测资源配置清单

> **地位**：产品 MVP（vision 五条判据）开工门禁，**不是**工程联调清单。  
> **对照**：[vision.md](vision.md) 五条成功判据 · [roles.v1.json](../contracts/roles.v1.json) · [consensus.v1.json](../contracts/consensus.v1.json) · [contribution.v1.json](../contracts/contribution.v1.json) · [G3 真端对接验收](reviews/G3_真端对接验收_2026-08-24.md)  
> **纪律**：G3 只证明管道通。MVP 内测必须让一个**真共同体**走完共议与兑现。本地双机互打、开发号互 ack、管理员拨角色，**一律不算内测开始**。迷茫时读 [围坐初心](reviews/围坐初心_不是聊天室_防自嗨_2026-08-30.md)。  
> **状态（2026-08-26；08-27 更新）**：清单已起草，**真实评估未做 → 不具备开工条件**。工程侧：局域网 G3（08-24）+ 天翼云双信号复现（08-26，[联邦方案 §8.5](联邦测试闭环方案.md)）+ P3 终端切流归档（08-27）已过；**不替代本页人齐门禁**。  
> **联邦硬化（另一条线）**：单机部署后的发件箱 / 密钥轮换等见 [`POST_DEPLOY_FEDERATION_HARDENING.md`](POST_DEPLOY_FEDERATION_HARDENING.md)，**不替代本页 G6**。部署已完成（2026-08-27 P3 归档），硬化项可排期实施。

---

## 0. 开工门禁（全部勾上才允许叫「MVP 内测」）

评估人填「是/否」与证据。任一项为否或空，**不得开测**。

| # | 条件 | 评估（是/否） | 证据 / 备注 |
|---|------|---------------|-------------|
| G0 | 工程 G3 已通过（5211 真信号落库） | 是（2026-08-24 局域网；2026-08-26 天翼云复现；P3 入口已切天翼） | [G3 验收](reviews/G3_真端对接验收_2026-08-24.md) · [联邦方案 §8.5](联邦测试闭环方案.md) · [P3 施工单](P3_终端机施工单.md) |
| G1 | 已指定**一个**真实 circle 名称与议题（不是「测试圈」空转） | | |
| G2 | 下表席位 A/B/C 已有**具名真人**承诺参加一场同步（不是开发账号） | | |
| G3 | 三人理解：ack 必须本人点；AI 不能代 ack；不能只为自己认定贡献 | | |
| G4 | 升级路径书面约定：C 从旁观升参与须带 Dual/CoCo 证据，禁止只拨 admin | | 书面约定已落：手册 §五.6 + 本节 §4.5（08-28）。工程侧已实现：`/circle/api/promote` → `identity.promote_role`，无证据 400（admin toggle 被拒），升级记录 `role_evidence_ids` + `role_changed_by` |
| G5 | 本场阈值已写下（默认 85 或 circle 自定），并约定 AI 证据不得作为唯一依据 | | 已写下（08-28）：手册 §五.3「本场阈值：默认 **85**（`CONSENSUS_THRESHOLD`，circle 可自定）；AI 证据只作辅证，不得作为唯一依据」+ 本节 §4.2「至多一条 AI 辅证」 |
| G6 | 内核侧：circle / consensus / contribution 能走完剧本（不仅 stub 记一笔）；密钥已按环境区分联调/内测。**现况（2026-08-28）**：圈/共识/地板已落库（`circle_flow.db`，天翼 `29ff821` 上云冒烟通过），重启不再清场；`signal_log`/`memory_records` 已 sqlite；**兑现入口已打通**（`/circle/api/attest` + `/circle/api/fulfill`，兑现自动 mint `contribution` evidence 轨迹到 B 画像）；**C 升级有证据记录**（`/circle/api/promote`，无证据 400）。identity/contribution 数据本身仍在内存（无兑现持久化表），但「兑现 → 升级」剧本链路已可走通 | | |

**评估结论**：□ 具备条件，可以开始　□ 不具备，继续等席位/议题  
**评估人 / 日期**：________________

---

## 1. 人力：共同体席位（内测主体）

契约下限 **3 个真人**。推荐 **4 个真人**（主理与圈主分开）。八角梯不必配齐 8 级。

| 席位 | 八角梯 | 人数 | 必须完成的动作 | 挡住的判据 | 具名人（评估时填） | 承诺场次 |
|------|--------|------|----------------|------------|---------------------|----------|
| **A 圈主** | proposer（可兼 steward） | 1 | 建圈、提议、写一条可被引用的记忆、认定他人贡献；若兼 D 则兑现 | 记得住、协商得了、兑得现 | | |
| **B 对端** | participant | 1 | 第二 party、对人 ack；被认定或反过来认定 A | 协商得了（`parties≥2` 且全员 ack） | | |
| **C 旁观样本** | 先 observer，再升 participant | 1 | 只读一场 `consensus_verified`；再留 Dual/CoCo 痕迹后升级 | 人往高处走 | | |
| **D 主理** | steward | 0 或 1 | `contribution.fulfill` → `identity.capability_trace`。空则由 A 兼任 | 贡献兑得现 | | |

合计：**3 人（A 兼 D）或 4 人（D 独立）**。跨 Mac / Windows / THOMAS 均可，但身份是**圈内成员**，不是联调机器人。

### 1.1 系统席（不算人头、必须有）

| 席位 | 说明 |
|------|------|
| AI 观察 | 一条 `score_evidence.observed_by=ai`，**不得**当唯一依据、**不得** ack、**不得**当 party（判据 5） |

### 1.2 明确不配

| 不配 | 原因 |
|------|------|
| organizer / actor / petitioner | 首轮不做申诉、解散、改规则 |
| 四类营造师各一人 | `builder_tags` 可多选，不加人 |
| 开发联调互打顶替 A/B/C | 计不了五条判据 |
| 再拉一桌 PlanetX/DemoPPI 真人 | 信号出站已有；内测要的是围坐动作 |

---

## 2. 人力：端侧值班（支撑，不是共同体）

不计入「3～4 人」编制。内测场次期间在线即可。

| 端 | 职责 | 人数 | 具名人 |
|----|------|------|--------|
| Windows | `gfcc_kernel` :5211 常驻；内测场次可查 `signal_log` / 端口记录；**不**改冻结契约 | 1 | |
| Mac | 契约真源；必要时 THOMAS fan-out 仍指向 5211；不把管理员开关当升级 | 1 | |

---

## 3. 工程与环境（内测前置，与 G3 区分）

G3 已满足「管道通」。下列是 **circle 剧本能跑完** 才需要的，评估时单独打勾。

| 项 | 最低要求 | 评估 |
|----|----------|------|
| circle 端口 | 能 create / join；成员 role 可解析。现实现：内存，重启丢 | |
| consensus 端口 | propose → 带 `score_evidence` 的 score → 全员 ack → `consensus_verified`；`consensus_math` 若用只进证据，**不能**跳过 ack。现实现：内存；录像/转写不得代替 ack | |
| contribution 端口 | 他认 attest + steward fulfill；拒绝「只为自己认定」。**现况（08-28）**：web 面 `/circle/api/attest` + `/circle/api/fulfill` 已实现（participant+ 认定、steward+ 兑现），fulfill 自动 mint evidence 轨迹 | |
| memory 端口 | 议题/行动可 `refs` 指向上一场共识或记忆（判据 1）。`memory_records` 已 sqlite | |
| identity | fulfill 后 `capability_trace` 可查；C 升级有证据记录。**现况（08-28）**：兑现后 B 画像出现 `contribution` evidence 轨迹；`/circle/api/promote` 升级记录 `role_evidence_ids` + `role_changed_by`，无证据拒绝。**Tatha `demo-token-*` 不算围坐身份**；每人一张主持人发放的令牌，`sub` 对报名表 | |
| 密钥 | 天翼 ingest 已换内测值（联邦 L5，≠ ETHOS、≠ 联调 `dev-signal-secret-*`）。双活轮换仍见硬化 R4，不挡本页人齐 | |

未勾完 **G6 + 本节**，即使人齐了也只做桌面演练，不开系统内测。

---

## 4. 一场最小剧本（条件齐了才跑）

一次同步会（建议 60–90 分钟）：

1. A 建圈，B 加入；C 旁观（只读）。  
2. A 提议（`parties = [A, B]`），证据 = 人证 + **至多一条** AI 辅证；A、B 本人 ack → `consensus_verified`。  
3. 新议题/行动 **引用** 步骤 2 的 id（记得住）。  
4. A 认定 B 的贡献；A 或 D 兑现 → 轨迹可查。  
5. 用步骤 2/4 的证据将 C 升为 participant（书面记录依据；禁止只改 JWT）。

**本场不做**：申诉、解散、改桌子（petitioner）、选项组 UI、链上锚定。

---

## 5. 内测通过口径（给人看，不是给 CI 看）

场次结束后，五条都要能指出**库里的 id**（人 ↔ `sub` ↔ 记录），否则本场失败、不算 MVP 内测通过。不回放腾讯会议验收。圈/共识/地板已落库（`circle_flow.db` 重启不丢）；identity/contribution 数据仍内存，**散会前抄 id**。

| 判据 | 本场最低证据 |
|------|----------------|
| 记得住 | 至少一条后续记录 `refs` 指向本场记忆或共识 |
| 协商得了 | 一条 `consensus_verified`；两条 ack 的 `sub` 都是真人；`score_evidence` 非空 |
| 贡献兑得现 | 一条 `fulfilled` 且 identity 上有对应 `capability_trace` |
| 人往高处走 | C 的 role 变更记录引用 Dual/CoCo，而非仅 `admin.role.set` |
| AI 不抢戏 | 若有 AI 证据，同时存在人证；verified 不在「仅 AI 一条证据」上成立 |

---

## 6. 资源总量（评估用）

| 类别 | 数量 | 说明 |
|------|------|------|
| 共同体真人 | **3（下限） / 4（推荐）** | A+B+C，D 可选独立 |
| 端侧值班 | 2（Mac 1 + Windows 1） | 场次在线 |
| 同步场次 | 1 场即可打底 | 升级若当场完不成，可加一场只做 C 的证据补齐 |
| 日历 | 人未齐则 **无限期等待** | 禁止用联调账号凑人头开测 |

第二轮（申诉/解散）再加 **1 名 organizer**，不在本清单强制范围内。

---

_起草：Mac 侧 2026-08-24。真实评估完成前，本文只作门禁，不作开工令。_
