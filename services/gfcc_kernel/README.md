# gfcc_kernel —— 格契内核

契约层（gfcc 仓库）的实现层。对齐 `contracts/ask.envelope.v1.json` 与 `registry.v1.json` 的
L1 内核 + L2 默认组合。

## 定位

| 层 | 内容 | 本服务 |
|---|---|---|
| L1 内核 | `POST /v1/ask` 信封 + ethos 验证 + 五槽 | ✅ |
| L2 默认组合 | kernel + 五个一等端口（circle/identity/memory/consensus/contribution） | ✅ stub 合法，空数据合法 |
| L3 可选画像 | profile.demo（demopeter/agentmemory/iii/job_match/poetry/credit/mbti） | 未注册（默认模式禁止） |

## 启动

```powershell
# 1) 安装依赖（ethos 走同级本地包）
cd services/gfcc_kernel
python -m venv .venv
.venv\Scripts\pip install -e ..\ethos -e .

# 2) 配置（可选；留空 = stub 联调，与现有 5210 一致）
copy .env.example .env

# 3) 启动（默认 5211 金丝雀端口）
.venv\Scripts\uvicorn gfcc_kernel.app:app --host 0.0.0.0 --port 5211
```

## 接口

- `GET /health` → 服务信息
- `POST /v1/ask` → `{ message, context? }` → `{ port, status, result, suggestions, confidence }`
- `POST /v1/signal-ingest` → 信号摄入（Step3 W1-W4，见下）

请求示例：

```bash
curl -X POST http://localhost:5211/v1/ask \
  -H "Authorization: Bearer " \
  -H "Content-Type: application/json" \
  -d '{"message":"记住：格契的共识阈值默认 85","context":{"session_id":"s1"}}'
```

## ethos 密钥语义

- `ETHOS_AUTH_SECRET` 留空 → `StubVerifier`（本地联调放行，与 5210 基线一致）。
- 配置后 → `HmacJwtVerifier`（HS256 严格模式），系统令牌跨服务互通。
- 审计：`ETHOS_AUDIT_DB` / `ETHOS_AUDIT_JSONL` 可选。

## 槽位实现（Step 1-2，对齐 docs/Phase2_Step1-2_实施建议.md）

### llm 槽：规则解析 → Ollama 语义分类（可选）

- `LLM_PROVIDER=stub`（默认）→ 规则解析 + stub llm，`/health` 显示 `llm=stub`。
- `LLM_PROVIDER=ollama` + `OLLAMA_BASE_URL` + `OLLAMA_MODEL` → `OllamaLLM`
  （`POST /api/chat`，`format=json` 强制结构化输出）。
- 解析优先级：`port_hint` → llm 槽 → 关键词规则兜底。**Ollama 离线/失败自动 fallback
  到关键词规则**，规则表不删除（CI 基准）。

```bash
# 前提：Ollama 已启动并 pull 模型
ollama pull qwen2.5:7b
# .env 里启用
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

### store 槽：内存 dict → SQLite 持久化（可选）

- `STORE_PROVIDER=stub`（默认）→ `StubStore` 内存（重启即空）。
- `STORE_PROVIDER=sqlite` → `SQLiteStore`，db 在 `STORE_DB_PATH`（默认 `data/memory.db`，
  与 `logs/audit.db` 同级，`data/` 已被 .gitignore 忽略）。重启不丢数据。
- 接口对齐 `memory.v1.json` store_slot：`put / get / query / supersede / count`。
- 契约红线：`supersede(observed_by="ai")` 直接拒绝（AI 只能 observe，不能静默改写）。

```bash
# .env 里启用
STORE_PROVIDER=sqlite
STORE_DB_PATH=data/memory.db
```

`/health` 会如实返回 `store=stub|sqlite` 与 `llm=stub|ollama`，便于确认当前装配。

## Step3 信号链路（W1-W4，对齐 Phase2_Step3 / contracts/signals/*.v1.json）

### 端点与语义
- `POST /v1/signal-ingest`：验签 → 严格信封 → 幂等落库（`signal_log`）→ 端口路由。
- 200 `stored|duplicate` + `signal_id` + `port`；401 `invalid_signature`；422 `invalid_envelope|unsupported_signal`。

### .env 键（信号链路专用，与 `ETHOS_AUTH_SECRET` 无关，**不混用**）
- `SIGNAL_INGEST_SECRET`：信号 HMAC 密钥（只读环境变量，发送脚本不写死）。
- `SIGNAL_LOG_DB`：signal_log 落库路径（Mac 约定 `data/signal_log.db`；未设回退 `STORE_DB_PATH`）。
- `STORE_PROVIDER=sqlite`：启用落库（stub = 内存，重启即空）。

### W4 发送器（全量 E2E 的"发送"一截，入库可复跑）
```powershell
# 1) 起 5211（见"启动"）+ .env 配好上述三个键
# 2) 全量 7 用例：PASS 全绿出口码 0，任一 FAIL 出口码 1
$env:SIGNAL_INGEST_SECRET = "<与 5211 相同>"
python scripts/mock_signal_sender.py --base http://127.0.0.1:5211
# 3) 杀进程持久化（两阶段，手动重启 5211）
python scripts/mock_signal_sender.py --case restart-persist-seed
#    ← 杀掉 5211 再启动
python scripts/mock_signal_sender.py --case restart-persist-verify
```

### 查库（官方固定 SQL，两侧同名防分叉）
```powershell
python scripts/query_signal_log.py                  # 最近 20 条
python scripts/query_signal_log.py --json --limit 5
# 固定 SQL：SELECT signal_id, signal_type, user_id_hash, nonce, created_at
#             FROM signal_log ORDER BY created_at DESC LIMIT ?;
```

## 入场机制（凭票入场 / 为什么不能自助领号）

围坐会场 `GET /circle/` 凭票进入：主持人（持 `ETHOS_AUTH_SECRET` 者）用
`scripts/issue_persona_tokens.py` 签发 HS256 JWT，一人一张，`sub` 即身份
（脚本拒绝重复 sub）。testers 用自己的票访问围坐页，旁观/入座/拍板/确认
各按角色放行。

**为什么不是"自主获取"？**

1. **技术本质**：当前无账号体系，JWT 的 `sub` 就是唯一身份凭据，票 = 身份。
   HS256 签名只有持密钥者能签——"自助获取"等于伪造，验签端必然拒绝。
   所以"主持人下发"是签名体系的必然结果，不是门卫姿态。
2. **设计原因（防 sybil）**：Step 1 的记忆体按 `sub` 隔离（A 记住的 B 问不到）。
   若放开自助取号，一人拿多个 sub 即可把记忆"搬运"到别的身份读，隔离名存实亡；
   还能开分身伪造"多人同意"。隔离安全 = 一人 ↔ 一 `sub` 的绑定，只能由
   "人-票一对一的签发环节"保证。
3. **透明 ≠ 身份自选**：票不拦"看"，只拦"说"。旁观（observer）对任何持票者开放，
   建圈 / 拍板 / 确认 / 结果全程留痕，轮询 `/circle/api/status` 即可围观。
   凭票的是入座 / propose / ack 这类"发言权"。

**何时放开自助**：引入账号体系（邮箱 / 微信 / 验证码登录）后，服务端注册即签发会话，
令牌降级为会话凭证，一人一号天然防 sybil（Loomio 模型），入场自然自助。
现阶段"主持人下发"是无账号体系的最小可行替代，不是永久闭环。
入场减负的下一步是**邀请深链**（一次性兑换码，JWT 不进 URL），不是页面自助领号。
开发对照：[`docs/围坐会场_邀请深链实施.md`](../../docs/围坐会场_邀请深链实施.md)。

## 设计约束

- 信封不可变；内部实现可替换。
- 加能力 = 注册适配器 + 模式清单，不增长 JobFirst intent 表。
- 五端口 stub：合法，空数据合法；不 import 任何命名厂商服务。
