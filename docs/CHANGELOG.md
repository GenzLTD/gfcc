# Changelog

## Unreleased（实现层 / 工程基建）

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
