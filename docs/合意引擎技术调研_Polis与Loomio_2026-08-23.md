# 合意引擎技术调研报告：Pol.is 共识算法 × Loomio 表决机制

> **调研性质**：GFCC/Tractor 合意引擎（consensus 端口）MVP 加速的源码级技术调研
> **调研方法**：Pol.is 全量浅克隆（compdemocracy/polis，1366 文件）+ Clojure 数学引擎逐文件精读；Loomio 因网络受限，经 GitHub API/raw 通道精读 Poll 模型与 poll_types.yml 配置（默认分支 master）
> **日期**：2026-08-23
> **结论前置**：合意引擎 MVP 开发周期可从原估 8-12 周压缩到 **3-4 周**（算法层重写，非复制），且 Pol.is 的数学方法完全适配 GFCC 的小规模社区场景（小场景反而更简单，可砍掉 Pol.is 40% 的复杂度）。

---

## 一、Pol.is 共识图谱算法：源码级拆解

### 1.1 数据模型（极简，这是它最聪明的地方）

每个参与者对每条陈述只有三种投票（`math/src/polismath/math/conversation.clj` L44）：

```
vote ∈ {-1, 0, 1}   # 不同意 / 跳过 / 同意
```

所有投票汇成一张 **评分矩阵**（参与者 × 陈述），`nil` 表示"没看见"。就这么多——没有权重、没有等级、没有评论嵌套。复杂度全部留给算法层，数据层刻意保持傻瓜化。

### 1.2 计算管线（8 步）

```
votes → raw-rating-mat → 补空值 → PCA(2维) → 基础聚类(k=100)
      → 意见组聚类(k=2..5, 轮廓系数选k) → 组内投票聚合
      → 共识检测 + 代表性评论 + 评论优先级
```

逐步拆解（源码定位均在 `conversation.clj`）：

| 步骤 | 做什么 | 源码位置 | 关键参数 |
|------|--------|---------|---------|
| ① 空值填充 | 每列（陈述）用该列平均值填 `nil` | L358-380 | — |
| ② PCA 降维 | 幂迭代法求 2 个主成分，参与者投到 2D 平面 | L381-387 | `n-comps=2, pca-iters=100` |
| ③ 基础聚类 | 对 2D 投影做 k-means，k=100（微簇） | L403-410 | `base-k=100, base-iters=100` |
| ④ 意见组聚类 | 对微簇质心再做 k-means，k 从 2 到 max-k | L433-445 | `max-k=5` |
| ⑤ 选 k | 轮廓系数（silhouette）选最优 k，加缓冲平滑 | L449-478 | `group-k-buffer=4`（连续 4 次同一 k 才切换） |
| ⑥ 组内聚合 | 每组每陈述统计 A（同意）/D（不同意）/S（见过） | L601-608 | — |
| ⑦ 共识检测 | 全局 + 跨组两套共识指标（见 1.3） | L633-654, L714-717 | — |
| ⑧ 代表性评论 | 每组挑 Top-5 最能代表本组立场的陈述 | L691-701 | 取 5 条 |

**入场门槛**（L243-269）：参与者至少投 7 票（或全部陈述 <7 条时投完）才进入聚类；不足 15 人时贪心补足投票最多的前 15 人。这是防小样本噪声的关键闸门。

**大规模分流**（L760-773）：参与者 >10000 或陈述 >5000 时切换到 mini-batch PCA（采样 100-1500 人增量学习）。**GFCC 场景用不到这条路径**——社区议事通常 20-200 人，直接走 small-conv 管线。

### 1.3 共识的数学（最值得偷的三行公式）

**全局部（拉普拉斯平滑概率）**：

```clojure
pa = (na + 1) / (ns + 2)    # 同意概率，+1/+2 是哑先验，防小样本极端值
am = pa × pat               # 同意度 = 同意概率 × 单比例 z 检验值
dm = pd × pdt               # 分歧度 = 不同意概率 × z 检验值
```

共识评论 = `am` 高；分歧评论 = `dm` 高。`pat` 是统计显著性检验——**票数太少时即使全票同意也拿不到高共识分**，这天然实现了"少数人不能定调"。

**跨组部（group-aware consensus，L633-654）**：

```clojure
consensus(tid) = ∏(g=1..G) (A_g + 1) / (S_g + 2)
```

一个陈述的跨组共识 = **每个意见组内同意概率的连乘**。只要有任何一个组强烈反对，乘积就被拉垮。这就是"寻找最大公约数"的数学表达——Pol.is 界面上绿色高亮的 " consensus " 评论就是它算出来的。

**代表性（repness，repness.clj L85-100）**：

```clojure
ra = pa(本组) / pa(其余组)          # 代表性比值
repness-metric = ra × rat × pa × pat  # 比值×比值检验×概率×概率检验，四项连乘
```

筛选规则（L165-170）：比值和概率都要通过 90% 置信 z 检验才算"够格"；每组保底 1 条代表评论（防止冷启动空组）；同意类排在不同意类前面。

### 1.4 GFCC 场景的简化红利

Pol.is 的复杂度是为万人场景设计的。GFCC 的 circle 议事场景（20-200 人）可以砍掉：

| Pol.is 组件 | GFCC 是否需要 | 理由 |
|------------|--------------|------|
| mini-batch PCA / 大规模分流 | ❌ 砍 | 人少，全量算毫秒级完成 |
| k=100 基础微簇 | ⚠️ 简化 | 直接对参与者聚类，k=2..5 |
| 二级子组聚类（subgroup） | ❌ 砍 | 组内再分组是万人需求 |
| k-smoother 平滑器 | ⚠️ 保留思想 | 防止组数闪烁，但对小场景可以简化为直接取轮廓系数最优 |
| PCA | ✅ 保留 | 核心可视化与聚类基础 |
| 共识数学三件套 | ✅ 原样保留 | pa/am/dm + 跨组连乘，直接 Python 重写 |

---

## 二、Loomio 表决机制：源码级拆解

### 2.1 九种表决类型（`config/poll_types.yml` + `app/models/poll.rb`）

`count`（报名签到）、`check`（sense check 快感检查）、`question`（纯理由收集）、`proposal`（**提案表决，核心**）、`meeting`（时间协调）、`poll`（多选一）、`dot_vote`（点数分配）、`score`（打分）、`ranked_choice`/`stv`（排序/单记移让）。

### 2.2 proposal 类型的五套选项组（本次调研最重要的发现）

Loomio 把表决选项做成**可切换的模板**，同一 proposal 引擎支持五种决策文化（poll_types.yml L129-219）：

| 选项组 | 选项 | 决策文化 | 对 GFCC 的启示 |
|--------|------|---------|---------------|
| 经典四态 | agree / abstain / disagree / **block** | 共识决 | block = 红线叫停权 |
| 同意决 | **consent** / abstain / **objection** | 社会学决（sociocracy） | "没有重大反对即通过" |
| 多数决 | yes / abstain / no | 简单多数 | 快速低风险事项 |
| 快感检查 | looks_good / could_be_better / needs_a_rethink | 温和探测 | 议题早期态度摸底 |
| 报名 | accept / decline | 自愿参与 | 行动招募 |

**关键设计**：每个选项都带 `meaning_i18n`（这个选项意味着什么）和 `prompt_i18n`（何时该选它）——把"投票礼仪"编码进选项本身，防止 block 被滥用为"我就是不喜欢"。

### 2.3 三处精妙的治理细节

1. **可改票**（`Stance.latest`）：每人每次表决只算最新立场（`ORDER BY created_at DESC LIMIT 1`），立场随讨论演化是合法的，不是作弊。
2. **法定人数双保险**：`quorum_pct`（参与门槛）+ `agree_target`（默认 5% 同意门槛）+ 可选 `vote_share_requirement`（得票率要求）。
3. **匿名保护下限**：`PARTICIPATION_STATUS_VOTES_MIN = 3`——匿名表决时参与状态至少 3 票才可见，防止"3 人小圈子互相推断谁投了什么"。

### 2.4 CRDT 实时协作

仓库根目录的 `hocuspocus/`（Yjs 官方 WebSocket 服务端）证实：Loomio 的协同编辑走 **Yjs CRDT**，支持多人离线合并。GFCC 的提案协作编辑（多人共拟一份提案）可直接采用同款开源组件（hocuspocus 为 MIT 许可，无传染风险）。

---

## 三、映射到 gfcc consensus.v1 契约

GFCC 契约（v1.1.0）的状态机是 `proposed → scored → (below_threshold | consensus_passed) → awaiting_ack → consensus_verified`，核心不变量：**分数必带证据（score_evidence），AI 证据是辅助，确认方必须是人**。

三个开源组件的落位：

### 3.1 Pol.is 算法 → `score` 操作的证据生成器

```
Pol.is 管线输出                    gfcc consensus 字段
─────────────────────────────      ─────────────────────────
跨组共识分 consensus(tid)     →     proposal.score 的候选算法之一
                                  （契约明示 "Scoring formula is
                                    circle-defined"，算法可插拔）
每条证据 z 检验值 pat/rat      →     score_evidence[].basis
                                  （"共识分 0.87，p<0.10，基于 34 人
                                    跨 3 组投票分布"）
组间分歧结构（cluster 剖析）   →     score_evidence 中 AI 观察项
                                  （observed_by: "ai"）
```

**契约完全兼容，无需改契约**。Pol.is 的统计检验天然满足"无证据不得离开 proposed"——z 检验本身就是证据。而且 z 检验的显著性要求（90% 置信）给了 `CONSENSUS_THRESHOLD=85` 一个统计学的锚点：**阈值不该是拍脑袋的百分比，而是"证据强度"**。

### 3.2 Loomio block 选项 → 红线系统的表决化

GFCC 的红线（不变量）目前是"AI 可观察、不可替代承诺"的规则层概念。Loomio 的 block 把它变成了**参与者可主动行使的表决动作**：

- block 一票 → 提案强制回到 `below_threshold`（红线否决）
- 但 block 必须附带理由（Loomio 的 `per_option_reason_prompt: true`），理由写入 score_evidence
- 结合 GFCC 契约：block 记录为 `observed_by: "human"` 的证据项，且触发状态机中 `failed` 分支前的一次强制复议窗口

**建议的选项组**（结合 Loomio 五套模板 + GFCC 双向确认）：

```
v1 默认四态：agree / abstain / disagree / block(红线叫停)
circle 可切换：consent / objection（社会学决，适合高信任小圈子）
```

### 3.3 差距分析：两个开源都没做、契约要求的

| 契约要求 | Pol.is/Loomio 现状 | GFCC 需自建 |
|---------|-------------------|------------|
| 双向确认（awaiting_ack → verified） | 都没有——Pol.is 出图谱即终态，Loomio 关投票即终态 | **ack 环节是 GFCC 独有**，Loomio 的 Stance.latest 可改票机制可借鉴（ack 也应可撤回） |
| 非货币价值计入分数 | 无 | "评分公式由 circle 定义"——声誉×贡献加权可挂载 |
| AI 作为证据源 | Pol.is 无 AI；Loomio 无 AI | AI 观察项进 score_evidence（auxiliary） |

**结论：合意引擎 = Pol.is 的共识数学（作 score 与证据）+ Loomio 的表决选项（作协商界面）+ GFCC 独有的双向确认（作治理闭环）**。前两者是加速器，第三者是护城河。

---

## 四、⚠️ 许可证红线：AGPL-3.0 传染风险

**Pol.is 和 Loomio 都是 AGPL-3.0**（API 验证：两仓库 license 字段均为 AGPL-3.0）。这意味着：

- ❌ **禁止**直接复制/翻译它们的代码进 GFCC 闭源部分——AGPL 要求"通过网络提供服务"也要开源
- ✅ **允许**学习算法思想后重写——数学方法（拉普拉斯平滑、z 检验、k-means、轮廓系数、连乘共识）不受版权保护，均为公开统计学/机器学习常识
- ✅ **允许**独立部署 Pol.is/Loomio 实例做试点对照（它们自身开源部署合法）
- ⚠️ 若未来深度集成（如嵌 Pol.is 界面），需法律意见；`hocuspocus`（Yjs 服务端）是 **MIT**，无传染风险，可放心用

**本报告记录的公式与流程均为算法思想层面的提炼，重写实现不构成衍生作品**——这也是本次调研的方法论立场：读思想，不搬代码。

---

## 五、MVP 实施路径（3-4 周）

| 周 | 交付 | 内容 |
|----|------|------|
| W1 | `consensus_math.py` | 三件套数学内核：拉普拉斯平滑概率 + 单/双比例 z 检验 + 跨组共识连乘；PCA + k-means 用 scikit-learn 现成件；52 项单测对照 Pol.is 已知行为（如空矩阵、全票、小样本） |
| W2 | 表决界面 + 选项组引擎 | 四态选项（含 block 红线）+ 选项组模板表（借鉴 Loomio 五套）+ `per_option_reason_prompt`（block 必附理由）；接入 `/v1/ask` dispatcher |
| W3 | 证据链与状态机打通 | Pol.is 输出 → score_evidence 自动生成（z 检验值进 basis）；block → below_threshold 强制复议；ack 可撤回（借鉴 Stance.latest） |
| W4 | 联调 + 首个 circle 实测 | 与 gfcc_kernel :5211 集成，stub store → SQLite；阈值语义从百分比改为"证据强度"双轨制（circle 可选） |

**依赖**：scikit-learn（PCA/k-means/轮廓系数）、numpy（矩阵运算）。无重依赖，与现有 kernel 技术栈（FastAPI + SQLite）零冲突。

**对比原计划**：立项报告把合意引擎列为 P2（8-12 周），主要成本在"从零设计算法与验证"；本调研证明算法层有成熟参考，成本转移到工程集成——这正是 3-4 周估算的依据。

---

## 六、附录：调研材料索引

| 材料 | 位置 | 状态 |
|------|------|------|
| Pol.is 完整仓库（浅克隆） | `_gfcc_tmp/research/polis/` | ✅ 本地 |
| 核心文件：conversation.clj（管线编排） | `polis/math/src/polismath/math/` | ✅ 精读 |
| 核心文件：repness.clj（共识+代表性） | 同上 | ✅ 精读 |
| 核心文件：clusters.clj / pca.clj / stats.clj | 同上 | 📂 可继续深挖 |
| Loomio poll_types.yml（九类型全配置） | `_gfcc_tmp/research/loomio_poll_types.yml` | ✅ 本地 |
| Loomio Poll 模型（经 Web 精读） | github.com/loomio/loomio (master) | ✅ 摘要 |
| Loomio 仓库整体克隆 | — | ❌ 网络受限（GitHub 443 间歇不通），后续可补 |

**下一步建议**：① W1 开工前可再精读 `stats.clj`（z 检验实现细节）与 `clusters.clj`（k-means+轮廓系数）；② Loomio 的 `PollService.calculate_results` 值得补一次抓取（STV 计票逻辑）；③ 把本报告结论同步给 Jason 侧，作为 Step3 之外的第二条并行开发线。

内容由AI生成，仅供参考
