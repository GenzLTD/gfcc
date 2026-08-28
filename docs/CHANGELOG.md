# Changelog

## Unreleased（实现层 / 工程基建）

- `feat(circle)` G6 圈态落库（2026-08-28）：圈/共识/地板从内存进 SQLite，独立库 `data/circle_flow.db`（`circles`+`circle_members`+`proposals`+`proposal_acks`；`CIRCLE_FLOW_DB` 可覆盖、`CIRCLE_FLOW_PROVIDER` 跟随 `STORE_PROVIDER`，stub=内存）。ack 达成 + 地板轮转同事务（`verify_and_advance_floor`）；leave 删成员 + 地板交接同事务；dissolve 留行；hydrate 重启恢复，`verified_at` 不进 API 形状；HTTP 契约未加路径。本地 pytest 150 passed（含落库 6），**已上云（`29ff821`，2026-08-28 14:09 restart）**：`circle_flow.db` 新建、四表齐全，冒烟建圈→入座→拍板→双 ack→verified+地板轮转→restart→status 恢复（成员/地板/verified/acks=2）全通过。**重启不再清场**。施工单 [`围坐会场_G6圈态落库实施.md`](围坐会场_G6圈态落库实施.md)。已知边界（不挡场次）：①进程缓存先改、库后写，`verify_and_advance_floor` 若 500 库干净而缓存已 verified——值班处置=不接着打同一场，kickstart 一次从库纠偏；②末人持地板 leave 不更新 `floor_sub`（两人圈碰不到）；③CREATE 未写 REFERENCES（靠 `PRAGMA foreign_keys=ON`）。
- `docs` 发布环 = 开发环口径收口（2026-08-28）：天翼 `/data/gfcc` 与本地 LaunchAgent 均跑 `2c86252`（天翼 13:28 restart、本机 14:40 kickstart，`/circle/` 均 200）。轮询 / 深链由「待上云」改「**已上云 / 待真人令牌冒烟**」（下一场真人入座才算轮询冒烟）；部署手册 SHA `079bb6c` → `2c86252`，`propose` 改地板闸 `not your floor`（仅 `floor_sub` 可提交）。施工单同步收口：[发言权轮询实施](围坐会场_发言权轮询实施.md) · [邀请深链实施](围坐会场_邀请深链实施.md)。
- `docs` 围坐规模化笔记（2026-08-28）：联合国大会「辩论≠表决、发言名单可截止、答辩权」与 4 人轮询 / 百人场切分。探索非施工。见 [`docs/reviews/围坐规模化_联合国会议模式_2026-08-28.md`](reviews/围坐规模化_联合国会议模式_2026-08-28.md)。
- `feat(circle)` 发言权轮询（2026-08-28）：入座者按顺序轮流持有地板，仅地板可提交下一条拍板句（非地板 403 `not your floor`）；全员 ack 达成后按 members 入座顺序轮转（两人 A→B→A）；一次一条，pending 时后端同样拒绝（`pending proposal exists`）；提议人中途 leave 地板已在交接时不双跳；`status` 带 `floor_sub`/`floor_next_sub`；页面拍板卡仅地板且无 pending 显示，非地板见「当前发言权在 X，本条达成后交给 Y」。本地已验收（圈测 21、全量 144、`:5211` 冒烟 8/8、ServBay 页面含轮询文案），**已上云（`2c86252`，2026-08-28 13:28 restart），待真人令牌冒烟**。施工单 [`docs/围坐会场_发言权轮询实施.md`](围坐会场_发言权轮询实施.md)。
- `feat(circle)` 邀请深链入场（2026-08-28）：一次性兑换码 `POST /circle/api/redeem`（码走 body），CLI `--invite-base` 只发 URL、`--out` 不含密钥；页面 `?i=` 自动兑换后 `replaceState` 去码。本地已验收（pytest 135、`:5211` 四态 + 浏览器 410），**已上云（`2c86252`，2026-08-28 13:28 restart），待真人令牌冒烟**。非自助注册。施工单 [`docs/围坐会场_邀请深链实施.md`](围坐会场_邀请深链实施.md)。
- `feat(circle)` 围坐会场首场内测（2026-08-28）：`/circle/` 单页公网入口，jason / tester-b / tester-c 三令牌实测本人确认链路（建圈→入座→旁观→拍板→本人确认→达成→连续推进→换人当组织者）。修复 3 问题：①组织者视角大字展示圈号本体（UUID 可复制）+ 分享链接（建圈成功时同样展示）；②入座失败根因=议题名当圈号，md5 核对排除代码问题后同处 UI 根治；③旁观提示「只旁观·先只看」「只能看不能确认」，旁观不显示确认按钮，一次只推进一条共识。**验的是本人确认链路**，兑现 / C 升级 / 记忆引用未做；圈与共识仍在内存，远程无 JWT 无法复验账本 id。纪要见 [`docs/reviews/围坐会场内测纪要_2026-08-28.md`](reviews/围坐会场内测纪要_2026-08-28.md)。
- `feat(kernel)` Step 1 记忆体按人隔离（2026-08-27）：`query`/`get`/`recall` 必带 `actor_sub`；无 sub 不落 `"system"`；HS256 无 token / 坏 token → 401。签发脚本 `scripts/issue_persona_tokens.py`。验收见 [`docs/reviews/Step1_每人一个sub记忆体隔离_验收_2026-08-27.md`](reviews/Step1_每人一个sub记忆体隔离_验收_2026-08-27.md)。运行树 `~/Projects/gfcc`。
- `docs` 2026-08-27 按现况修订：[`VERSIONING.md`](VERSIONING.md)（P3 已完、硬化可排期、实现债≠契约 bump、ack 不得被录像代替）；testers 须知 / MVP 内测手册（会场 ≠ PlanetX；令牌 ≠ Tatha 演示桩；验证 = 人↔sub↔id）；MVP 清单 G6 写明圈/共识仍内存；联邦方案标题与 §8.4 边界 2 关闭 P3；硬化 R4 与 L5 对账。
- `docs` 环 2 信号段通过（2026-08-26 夜）：天翼 `signal_log` 3 行 `consensus_match`（nonce 已记）；G3 双信号云上复现完成。见 [`docs/联邦测试闭环方案.md`](联邦测试闭环方案.md) §8.5。下一层 P3（已于 2026-08-27 归档）；不合 `main`。
- `docs` **P3 终端切流全部完成并归档（2026-08-27）**：A 浏览器验收 / B 阿里 API 指向迁移天翼 / C Vultr 空钥匙确认 / D 入口文案统一。腾讯原地冻结冷备、入口唯一 = 天翼 `http://14.29.216.219/`。施工单 [`P3_终端机施工单.md`](P3_终端机施工单.md) 已标注已归档。
- `docs` P3 施工单 + 围坐 testers 须知：[`P3_终端机施工单.md`](P3_终端机施工单.md)（机上切流）· [`围坐testers须知.md`](围坐testers须知.md)（席位/时间/场次/不要付费）。
- `docs` 新增 [`docs/POST_DEPLOY_FEDERATION_HARDENING.md`](POST_DEPLOY_FEDERATION_HARDENING.md)：单机云端部署完成后的联邦硬化摘录（ingest 快回、密钥轮换、signal_log 只追加）；完整待办在 THOMAS `docs/POST_DEPLOY_RESILIENCE_BACKLOG.md`。部署完成前不实施。

- `feat(kernel)` gfcc_kernel 1.1.0 上线：`POST /v1/ask` 单入口信封 + 五槽（llm/tools/session/policy/store）+ 五端口默认 stub 组合（gfcc.default）。
- `feat(kernel)` Step1-2：llm 槽接 Ollama（语义意图分类 + 关键词规则兜底）；store 槽接 SQLite（持久化、重启不丢）。
- `fix(kernel)` StubStore 对齐 SQLiteStore 契约红线：`supersede(observed_by="ai")` 拒绝；`count()/query()` 只统计活跃记录（评审 F1/F2）。
- `test(kernel)` 新增 `services/gfcc_kernel/tests/`：信封严格性、端口解析、store 槽双实现语义一致、consensus 状态机、API 集成（52 项）。
- `ci` 新增 test-kernel job（含 ethos 本地依赖联合安装）与 test-contracts job（contracts JSON 合法性 + 版本一致性校验）。
- `docs` .env.example 补 kernel 五变量；DEPLOY.md 架构表补 gfcc_kernel(:5211)。
- `fix(tenet)` resolver 测试平台适配（linux CI）。
- `fix(ci)` test-libs 补装 pytest。
- `[验收]` 工程基建补齐：GitHub Actions 四 job（test-libs / test-kernel / test-contracts / build-images）全绿通过（#5, 5m23s）。
- `docs` 新增 `docs/GITHUB_MIRROR.md`：GitHub 镜像使用指南（给 Mac 侧团队）——双托管架构、CI 四 job 说明、协作者接入与 PR 预检流程、GHCR 镜像拉取、同步纪律三条、Step3 三门用法。
- `docs` 新增 `docs/Phase2_Step3_Windows_开工清单.md`：Windows 侧 W1-W4 开工动员——G1 契约确认为当前唯一卡点、任务顺序与依赖、三条纪律，任务定义以 Step3 方案 §5.1 为准。
- `feat(kernel)` Step3 W1：新增 `POST /v1/signal-ingest`（signal.envelope.v1）——HMAC 验签（`SIGNAL_INGEST_SECRET` 留空=dev 免签+WARNING）、Pydantic 严格信封（additionalProperties=false，缺/多余字段 422）、幂等键 `(signal_type, user_id_hash, nonce)`、错误码 `401 invalid_signature / 422 invalid_envelope`。
- `feat(kernel)` Step3 W2：store 槽新增 `signal_log` 表（SQLite/Stub 双实现语义一致，UNIQUE 三元组防重，重启不丢）。
- `feat(kernel)` Step3 W3：确定性端口路由 `consensus_match→consensus` / `personality_beacon→identity`；两端口新增 `ingest_signal`（共识 match 落 score 证据 / 人格 beacon mint MBTI auxiliary trace）。
- `feat(scripts)` Step3 W4：新增 `scripts/mock_signal_sender.py` 信号发送端模拟器（demoppi/planetx，覆盖 stored/duplicate/401/422 场景）。
- `test(kernel)` 新增 `tests/test_signal.py` 16 项：W1 验收全场景（合法 200 stored、缺/多余字段 422、验签失败 401、免签 WARNING、幂等重放同 signal_id）、W3 端口调用记录与画像 trace、W2 双实现语义一致 + SQLite 重启不丢。
- `docs` .env.example 补 `SIGNAL_INGEST_SECRET` 说明（留空=dev 免签）。
- `docs` G1 冻结：Mac 确认「契约无异议」；入库 `signal.envelope.v1.json` + `signals/consensus_match.v1.json` + `signals/personality_beacon.v1.json`（v1.0.0，与八份 1.1.0 分家族）。见 `docs/reviews/G1_契约确认_2026-08-24.md`。
- `ci` `test-contracts` 按家族校验 version，并解析跨目录 `$ref`（envelope → `signals/*.json`）。
- `feat(kernel)` G1 对齐：`validate_payload` 收紧到与冻结 Schema 一致——payload 顶层 `additionalProperties=false`（未列字段 422）、`traits[{name,score}]` 严格结构、`assessment_score` 类型校验；`test_signal.py` 增补 3 项（71 项全绿）。
- `docs` 新增 `docs/reviews/合意引擎吸收_Windows侧确认_2026-08-24.md`：书面确认 Mac 评审（W1 并行、sklearn 走 extras、block≠below_threshold、ack 不可被算法跳过），承诺 W1 独立模块、Step3 主线继续、W2 等 G3。
- `feat(scripts)` Step3 W4 交付（Mac 交件清单）：`mock_signal_sender.py` 迁至 `services/gfcc_kernel/scripts/`，覆盖 7 用例（valid-beacon / valid-match / duplicate / bad-signature / missing-field / extra-field / unknown-type）+ 杀进程重启两阶段持久化验证；密钥只读 `SIGNAL_INGEST_SECRET`（不写进脚本）；新增 `scripts/query_signal_log.py`（官方固定 SQL，两侧同名防分叉）。
- `feat(kernel)` 契约对齐：未知 `signal_type` → `422 unsupported_signal`（区别于 `invalid_envelope`），对齐方案 §3.3 语义。
- `feat(kernel)` `SIGNAL_LOG_DB` 支持：store 槽落库路径读取顺序 `SIGNAL_LOG_DB` → `STORE_DB_PATH`（Mac/Windows 同名键防分叉）。
- `docs` G1 Windows 侧书面确认（契约无异议）追加至 `docs/reviews/G1_契约确认_2026-08-24.md`；kernel README 补 Step3 信号链路（起 5211 / 跑 W4 / .env 键名 / 查库 SQL）。
- `test(kernel)` 98 项全绿（含 `unsupported_signal` 断言）；`test(tenet)` 20 项全绿（resolver 已含 darwin/linux 平台路径）。
- `docs` 清理吸收建议/技术调研文档末尾「内容由AI生成」水印。
- `feat(consensus-math)` 合意引擎 W1 启动：`consensus_math.py` 纯函数库（拉普拉斯平滑同意概率、单/双比例 z 检验 90% 置信、同意度/分歧度、跨组共识连乘、代表性 repness、consensus_report 汇入 score_evidence）；零第三方依赖，scikit-learn 组件留 extras 后续挂载；27 项单测全绿（自造矩阵）。
- `docs` 确认文档追加分工澄清：W1 归 Windows、M2/M3 归 Mac（Mac 侧推进）、并行互不等待；GitHub 镜像仍不推送。
- `docs` G3 通过：PlanetX `personality_beacon` 与 DemoPPI `consensus_match` 真信号落 Windows `signal_log`（nonce 对账）。见 [`docs/reviews/G3_真端对接验收_2026-08-24.md`](reviews/G3_真端对接验收_2026-08-24.md)。
- `docs` 新增 [`docs/MVP_资源配置清单.md`](MVP_资源配置清单.md)：产品 MVP 内测门禁（3～4 真人席位 + 评估勾选）；未评估齐人不得开测。

## 1.1.0 — 2026-08-20

对照 [`docs/reviews/格契评审与修改建议_2026-08-20.md`](reviews/格契评审与修改建议_2026-08-20.md)。

- 新增 L-1 [`docs/vision.md`](vision.md)：定位句、五条成功判据、营造师维、AI 成员红线。
- P0：identity 营造师标签；memory 恢复方法论价值 + AI 观察；consensus `score_evidence`。
- P1：新增 `circle.v1.json`；roles `ladder_logic`；证据源白名单（去掉 `optional`）；信封 `dialog_mode`。
- P2：README 电梯陈述；VERSIONING；信封 `partial`；明确 gfcc=契约层、Tatha=实现层；v1 不依赖链。

## 1.0.0 — 2026-08-20

首版端口真源：Ask 信封 + identity / memory / consensus / contribution + 八角梯 + 默认/演示模式。
