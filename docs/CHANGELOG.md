# Changelog

## Unreleased（实现层 / 工程基建）

- `feat(contracts)` 契约 **1.4.0** / 信号线 **1.1.0**（2026-10-25）：L0 家族锁步升次版本。`identity.profile` 增加可选 `value_axes`（`survival` 钱多 / `freedom` 事少 / `belonging` 离家近），唯一写入是新信号 `value_axis_choice`（人选自己的轴，1–5 点，导航六域）。`job_match` 在轴存在时必须按这三项读，禁止把 `salary_match` / `location_match` / `culture_workload_match` / `overall` 写回身份。其余六项子分仍只描述一份职位。`values` 仍是声明字符串。Ask、circle、memory、consensus、contribution、roles 只改版本号。
- `feat(contracts)` 契约 **1.3.0**（2026-10-17）：L0 家族锁步升次版本。Ask 增加过渡校验者 `zervi-auth`（claims `{sub, role, name, phone}`，`role` 为市场角色，本版不改为 `roles[]`；缺 `sub` 仍 401）。registry 增加模式 `gfcc.terminal`（必选 identity + memory；`gfcc.default` 五端口不变）。`ctx.store` 增加适配器 `cortex-mcp` 与 pgvector 库 `gfcc`，只通过 `actor_sub` 关联；`empty_on_boot` 仍为真。`memory.recall` 仍要 observer，`remember` 仍要 participant。简历 / 职位 / mbti 仍在 demo，不进默认工具。信号线仍 **1.0.0**。
- `fix(demopeter)` 中文 RAG 嵌入治本（2026-09-01）：全库 25242 分块从 nomic-embed-text 重嵌入为 `shibing624/text2vec-base-chinese`（768 维）。查询走 `STEmbeddingFunction` + `query_embeddings`（chroma 1.5.9 不传 embedding_function 以免 conflict）；默认阈值 0.5→0.7。重建脚本 `scripts/reindex_embeddings.py` 三步式，write 阶段无改名 API 时自动复制迁移。启动默认 `HF_ENDPOINT=https://hf-mirror.com`。验收：「数理化通俗演义」唯一命中 95%（此前 top 被化妆品法规污染）。「什么是微服务」命中 Python 书属语料覆盖，非嵌入质量。
- `feat(kernel)` Bolent 入驻预埋（2026-08-31）：生态号 = `sha256(email.lower().strip())` 64 位小写 hex；`signal.email_to_user_id_hash`（空串 ValueError）；`issue_persona_tokens.py --emails`（与 `--subs` 互斥，sub=生态号，`--out` 禁止 email 键）；户口本 fixture [`experiments/bolent_membership.fixture.json`](experiments/bolent_membership.fixture.json)（schema `bolent.membership.v0`）。pytest **241 passed**（新增 19）。**未 bump 契约**：L0 1.2.0 / 信号 1.0.0，`contracts/` 零 diff。见 [`experiments/Bolent入驻预埋_Windows行动方案.md`](experiments/Bolent入驻预埋_Windows行动方案.md)。
- `feat(consensus)` 契约 **1.2.0**（2026-08-30）：L0 家族锁步升次版本（`validate_contracts` 要求同族同号）。`consensus.v1.json` 加 `rejected`/`withdrawn` 状态、`reject`/`withdraw`/`expire` operations、异议/撤回字段；`roles.v1.json` participant 补 `consensus.reject`/`withdraw`。不改全员 ack、不升主版本。见 [`围坐会场_D1-D5缺陷修复施工单.md`](围坐会场_D1-D5缺陷修复施工单.md) §0.3。
- `fix(circle)` D1–D5 缺陷修复（2026-08-30 本机 / **2026-08-31 天翼冒烟 16/16**）：D4 入场剥空白 + 401 文案；D1 proposer 确认提示（不自动 ack）；D2 `POST /circle/api/reject`；D3 withdraw + 惰性 TTL；D5 `POST /circle/api/dissolve`（非建圈者 403）；pending 闸改 `TERMINAL`。本机 pytest **201 passed**（新增 29）。天翼 `833ee54`：圈 `8640321b-…`，提议 `acks=0` → 异议 `rejected` → 撤回 → 解散 403/200 → 解散后写操作 400。冒烟圈勿当真场。施工单 [`围坐会场_D1-D5缺陷修复施工单.md`](围坐会场_D1-D5缺陷修复施工单.md)。

- `feat(kernel)` 品牌门页（2026-08-30）：`GET /` 返回静态品牌门页（定位、四轴、五条判据、围坐入口）；`/static/*` 挂载品牌 LOGO（216/1024）。不动契约（`/v1/ask` · `/v1/signal-ingest` · `/circle/*` · `/health` 行为不变）。pytest 172 passed（新增 7）。
- `docs` 围坐初心备忘（2026-08-30）：不是聊天室（地板 + 本人 ack + 可追溯）；防自嗨三条硬指标；Git「merge 才是事实」。迷茫时重读。见 [`reviews/围坐初心_不是聊天室_防自嗨_2026-08-30.md`](reviews/围坐初心_不是聊天室_防自嗨_2026-08-30.md)。
- `feat(circle)` 旁观在场可见（2026-08-30）：本机完成施工单 §0–§9。`POST /circle/api/observe` · `unobserve`；`status.watchers`；`circle_watchers` 落库；A/B 同名单；旁观不进 parties。pytest 165 passed。**待天翼场次间上云**。见 [`围坐会场_旁观在场可见实施.md`](围坐会场_旁观在场可见实施.md)。
- `docs` 旁观在场可见施工单（2026-08-29）：今晚圈实测 A/B 看不见 tester-c；根因是旁观无服务端登记。修复 = `POST /observe` + `status.watchers` + `circle_watchers`，不进 parties。本机已完成（08-30），天翼未上云。见 [`围坐会场_旁观在场可见实施.md`](围坐会场_旁观在场可见实施.md)。
- `docs` 决策备忘 **v0.8**（2026-08-29）：挂上旁观在场缺口与施工单；今晚不热修内核。见 [`reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md`](reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md)。
- `docs` 决策备忘 **v0.7**（2026-08-29）：云端冒烟全链路 10/10（建圈→入座→提议→双确认→共识→地板轮转→离场）；圈 `51af7529-…` / 提案 `629ee374-…` 已落库；席位已空。同日 tester-c 单把公网补测：`/me` 200、建圈 `f3394d1c-…`、单人 propose 400、离场席位空。下一步今晚真场，散会后补丁 5。不勾 G1–G6。见 [`reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md`](reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md)。
- `docs` 决策备忘 **v0.6**（2026-08-29）：本地/云端签发无实质差异但守则 6 仍云机签；昨晚 401 为 JWT 粘贴断行；SOP = 自验 200 + 长度核对后私发。见 [`reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md`](reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md)。
- `docs` 决策备忘 **v0.5**（2026-08-29）：更正 v0.4「无 systemd EnvironmentFile → stub」误判；密钥通道为 `load_dotenv()`；开场前定案 `journalctl … grep ethos` 见 HS256。见 [`reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md`](reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md)。
- `docs` 决策备忘 **v0.3**（2026-08-29）：补丁 3 闭环，状态改为可开闭门冒烟场；开场值守清单 6 条；发令牌前核 systemd `ETHOS_AUTH_SECRET` 来源。见 [`reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md`](reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md)。
- `docs` 补丁 3 **已通过**（2026-08-29）：公网 `:5210/:5220/:3210` timeout/`000`，`/circle/` 仍 200。见施工单勾选记录。
- `docs` 补丁 3 施工单（2026-08-29）：天翼安全组收回公网 `:5210/:5220/:3210`，保留 22/80、不开放 5211。见 [`补丁3_天翼安全组收回演示栈端口.md`](补丁3_天翼安全组收回演示栈端口.md)。
- `docs` 本机 ServBay 仿真与天翼边内测迭代决策备忘 **v0.2**（2026-08-29）：状态改为可实施（工程建议口径）；闭门冒烟场可开、不是 MVP 验收开工；开门硬条件固化为补丁 3（收回 `:5210/:5220/:3210`）；P1 闭门 IP 明文 / P2 缓办。见 [`reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md`](reviews/本机ServBay仿真与天翼边内测迭代_决策备忘_2026-08-29.md)。
- `docs` 围坐元服务薄壳技术可行性预研（2026-08-28）：独立预研稿，非开工。门禁 = D1 绿 + 账号立项；短链不能把 `?i=` 交给 Web 组件。见 [`reviews/围坐元服务薄壳_技术可行性预研_2026-08-28.md`](reviews/围坐元服务薄壳_技术可行性预研_2026-08-28.md)。
- `docs` 围坐上架路径内部决策备忘（2026-08-28）：商业价值 / Discord 对照 / 最短接法（HTTPS PWA）/ `circle.genz.ltd` / 账号倒逼 / 元服务支线。**夜复核**：D1 绿四条、ICP 硬门禁、R1 兑换码脱敏、华为登录单列、鸿蒙 NEXT 无加到主屏幕、元服务 EnhancedWeb/2MB/两套备案；`MyApplication` 标明为 PlanetX 元服务非围坐。见 [`reviews/围坐上架路径_内部决策备忘_2026-08-28.md`](reviews/围坐上架路径_内部决策备忘_2026-08-28.md)；子域操作见 [`围坐会场_circle.genz.ltd上线施工单.md`](围坐会场_circle.genz.ltd上线施工单.md)。
- `feat(circle)` G6 兑现与升级（2026-08-28）：**兑现入口打通**——`contribution.fulfill` 真调 `identity.append_trace`（`source_port=contribution` / `weight=evidence`），兑现成功后 B 画像 mint `contribution` evidence 轨迹（此前仅返回 `may_mint_trace=True` 不落画像）；**C 升级有证据记录**——新增 `identity.promote_role(sub, new_role, evidence_ids, changed_by)`，`new_role` 须在八角梯 `ROLE_ENUM`、`evidence_ids` 非空（无证据 400，禁止只拨 admin），画像记 `role_evidence_ids` + `role_changed_at` + `role_changed_by`；web 面新增 `POST /circle/api/attest`（participant+ 认定，拒绝只为自己）· `POST /circle/api/fulfill`（steward+ 兑现，校验记录属圈，返回 `minted_trace_id`）· `POST /circle/api/promote`（organizer+ 执行升级）。`registry` 注入 `ContributionAdapter(identity=...)`。本地 pytest 155 passed（新增 5：兑现 mint 轨迹 / 自证拒绝 / 非成员认定 403 / 无证据升级 400 / 非 organizer 403）。对齐 roles.v1 transitions（升级 driven_by 证据）与 EVIDENCE_SOURCES 白名单。**本地 ServBay 真实环境已验证（重启内核 + 真令牌走 5211 与 `gfcc.servbay.host`，11/11 通过）**，期间修一处真实回归：`identity.append_trace` 原返回 `id=sub`（`minted_trace_id` 变成 `tester-b`），现 trace 条目带 `id`（uuid4）并返回之（`ingest_signal.trace_id` 同步修正），测试断言补强为 uuid 格式 + 与画像轨迹条目 id 对应。**数据本身仍内存**（无兑现持久化表，待下一步贡献落库）。
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
