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
- `docs` 清理吸收建议/技术调研文档末尾「内容由AI生成」水印。

## 1.1.0 — 2026-08-20

对照 [`docs/reviews/格契评审与修改建议_2026-08-20.md`](reviews/格契评审与修改建议_2026-08-20.md)。

- 新增 L-1 [`docs/vision.md`](vision.md)：定位句、五条成功判据、营造师维、AI 成员红线。
- P0：identity 营造师标签；memory 恢复方法论价值 + AI 观察；consensus `score_evidence`。
- P1：新增 `circle.v1.json`；roles `ladder_logic`；证据源白名单（去掉 `optional`）；信封 `dialog_mode`。
- P2：README 电梯陈述；VERSIONING；信封 `partial`；明确 gfcc=契约层、Tatha=实现层；v1 不依赖链。

## 1.0.0 — 2026-08-20

首版端口真源：Ask 信封 + identity / memory / consensus / contribution + 八角梯 + 默认/演示模式。
