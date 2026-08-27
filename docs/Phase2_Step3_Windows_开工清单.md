# Phase2 Step3 · Windows 侧开工清单

> **状态：已收口（2026-08-24 G3 通过）**——W1–W4 已全部交付（`/v1/signal-ingest` + `signal_log` + 端口路由 + mock 发送器，98 项测试全绿），G1 契约已冻结、G3 真端对接已通过。本文为历史动员记录，不再有未执行动作。
> **致**：Windows 端 gfcc_kernel 实施方（W1-W4）
> **写**：评审/基建方（Windows，2026-08-21）
> **依据**：[`Phase2_Step3_信号契约与协调方案.md`](Phase2_Step3_信号契约与协调方案.md)（Mac 侧起草）· [`GITHUB_MIRROR.md`](GITHUB_MIRROR.md) · [`DEPLOY.md`](DEPLOY.md)
> **性质**：开工动员与顺序指引，不新增任何要求——任务定义、验收标准、样板文件以 Step3 方案 §5.1 为准。

---

## 0. 背景（一分钟版）

- 工程基建已闭环：GitHub Actions 四 job（test-libs / test-kernel / test-contracts / build-images）全绿（run #5，5m23s）。
- GitHub 镜像已就绪：`github.com/szpeter2026/gfcc`（Private），Gitee 仍是唯一真源，双推纪律见 `GITHUB_MIRROR.md` §4。
- Step3 联调方案已由 Mac 侧起草完成，等 Windows 侧确认契约后即可冻结开工。

## 1. 开工前三步（按序，半天内完成第 1 步）

| 序 | 事项 | 对应文档 | 完成标志 |
|---|---|---|---|
| 0 | 同步代码到 `ecbb15c` 及之后，通读三份文档 | GITHUB_MIRROR.md / Step3 方案 / DEPLOY.md | — |
| **1** | **G1 契约确认（最优先）**：Review Step3 方案第二~四节——信封结构、两类信号（consensus_match / personality_beacon）、端口路由 | Step3 方案 §2-4 | Gitee issue 或群内回复"契约无异议"→ 契约冻结，Mac 侧入库三份契约 JSON |
| 2 | W1→W2→W3→W4 顺序开发（见下表） | Step3 方案 §5.1 | W4 E2E 全绿 + 可复跑脚本入库 |

**为什么 G1 最优先**：这是当前唯一卡点。Mac 侧在等你的"无异议"确认才能冻结契约、入库 JSON；这条不回，两边都动不了。

## 2. W1-W4 任务速览

详细定义、验收标准、样板文件路径见 Step3 方案 §5.1，此处只列顺序与依赖：

| 编号 | 任务 | 依赖 |
|---|---|---|
| W1 | `POST /v1/signal-ingest`：验签（`SIGNAL_INGEST_SECRET`，留空=dev 免签+WARNING）→ Pydantic 严格信封校验 → 幂等 → 按 signal_type 路由 | 契约冻结（G1） |
| W2 | `signal_log` 表（SQLite，经 store 槽）：参照 Tatha `skills_evidence` 结构，UNIQUE 三元组防重 | W1 |
| W3 | 端口路由：`consensus_match` → consensus 端口；`personality_beacon` → identity 端口。端口仍是 stub 也先落 signal_log | W1 |
| W4 | mock 发送器 + E2E：`scripts/mock_signal_sender.py`（构造信封+HMAC 签名，发 5211），覆盖 stored / duplicate / 401 / 422 / 重启存活 | W1-W3 |

## 3. 三条纪律

1. **每完成一步就双推**（Gitee + GitHub），别攒大 commit——CI 三个测试 job 自动回归，红了先修再继续。
2. **测试只增不减**：现有 52 项 kernel 测试是基线；W1-W4 每项任务按方案要求配套单测。
3. **G1 冻结后字段不许悄悄改**：契约字段变更走版本号（见 [`VERSIONING.md`](VERSIONING.md)）。

## 4. 你不需要等 Mac 侧

G1 确认后，链A（THOMAS 内部桥）与链B（对外摄入，你的 W1-W4）**完全并行**：

- 你用 mock 发送器自测 `/v1/signal-ingest`，不需要 THOMAS 真端在线；
- 最后 G3 门一次对接即可。

预计 Windows 侧工作量约 **2.5 人天**（方案 §5.4 估算）。

---

*本清单由 Windows 侧基建/评审方整理（2026-08-21）。与 Step3 方案有任何冲突，以 Step3 方案为准。*
