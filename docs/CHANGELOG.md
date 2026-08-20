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

## 1.1.0 — 2026-08-20

对照 [`docs/reviews/格契评审与修改建议_2026-08-20.md`](reviews/格契评审与修改建议_2026-08-20.md)。

- 新增 L-1 [`docs/vision.md`](vision.md)：定位句、五条成功判据、营造师维、AI 成员红线。
- P0：identity 营造师标签；memory 恢复方法论价值 + AI 观察；consensus `score_evidence`。
- P1：新增 `circle.v1.json`；roles `ladder_logic`；证据源白名单（去掉 `optional`）；信封 `dialog_mode`。
- P2：README 电梯陈述；VERSIONING；信封 `partial`；明确 gfcc=契约层、Tatha=实现层；v1 不依赖链。

## 1.0.0 — 2026-08-20

首版端口真源：Ask 信封 + identity / memory / consensus / contribution + 八角梯 + 默认/演示模式。
