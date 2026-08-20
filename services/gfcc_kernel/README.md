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

## 设计约束

- 信封不可变；内部实现可替换。
- 加能力 = 注册适配器 + 模式清单，不增长 JobFirst intent 表。
- 五端口 stub：合法，空数据合法；不 import 任何命名厂商服务。
