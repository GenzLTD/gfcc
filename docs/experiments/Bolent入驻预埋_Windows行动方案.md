# Bolent 入驻预埋 · Windows 侧行动方案

> **致**：Windows 端（Gitee `szbenyx`，gfcc_kernel + 若你同时管 `szbolent-portal`）  
> **写**：Mac 侧研讨收口（2026-08-31）  
> **性质**：可勾选、可对账的实施单。**不是** L0 契约变更，**不是**第一场围坐开门条件。  
> **对照**：同日研讨收口（生态号 = email hash + 站点 id；不 bump L0）· [`VERSIONING.md`](../VERSIONING.md) · [`contracts/signal.envelope.v1.json`](../../contracts/signal.envelope.v1.json) · [`ports/identity.py` ingest_signal](../../services/gfcc_kernel/src/gfcc_kernel/ports/identity.py) · 签发 [`issue_persona_tokens.py`](../../services/gfcc_kernel/scripts/issue_persona_tokens.py)

---

## 0. 一分钟

入驻主语是**生态号**（花粉 / QQ 式松绑定），不是网证、不是五套登录打通。

```
生态号     = sha256(email.lower().strip())     → 64 位小写 hex（= 信号信封 user_id_hash）
入驻资格   = (email_hash, bolent_site_id, 状态)  → 户口本，真源在 Bolent/genz 社区壳
格契怎么用 = 社区成员的围坐 JWT.sub 等于该 hex；personality_beacon 已经这样用了
```

本单只把「号」在 gfcc 仓里**可验证地对齐**；户口本真源不进格契 SQLite，也不改 1.2.0 / 信号 1.0.0。

## 1. 明确不做

| 不要 | 为什么 |
|---|---|
| 改 `contracts/*.json`、升 1.2.0 / 1.0.0 | 家族锁步；成员资格是关系，不是画像字段 |
| `identity.profile` 加 `site_id` | 一个号可入驻多个站点，塞进画像变成 1:1 |
| 新 `signal_type=node_joined` | 等真有一条入驻再冻信号次版本 |
| Ask `context` 走私 `site_id` | `additionalProperties: true` 不是契约 |
| 国家网络身份、统一 SSO、FlexJob | 研讨已关 |
| 把 tester-a / jason 占位令牌废掉 | 冒烟场仍可用；本单只**新增**邮箱签发路径 |
| 天翼当场重启为了本单 | 无活跃场次才能上；本单不挡第一场围坐 |

## 2. 分工与仓库

| 块 | 仓 | 谁做 | 本单要不要交件 |
|---|---|---|---|
| A. hash 函数 + 邮箱签发 + 单测 | `gfcc`（Gitee 真源） | **Windows** | **要**，本仓 CI 可验 |
| B. 户口本 fixture（schema 样例） | 同仓 `docs/experiments/` | **Windows** | **要**，无数据库也能对账 |
| C. 户口本真表（申请/在网/退出） | `szbolent-portal` 或 genz 社区壳，**不是** `gfcc_kernel` | 管门户的一侧 | 本单只钉 schema，不强制本周建表 |
| D. www.genz.ltd 从营销壳切社区面 | 产品/域名，另单 | 不在本单 | — |

A+B 做完即可勾「Windows 预埋通过」。C 有表之后再谈信号 `node_joined`。

## 3. 算法钉死（与现网测试向量一致）

与 [`signal.envelope.v1.json`](../../contracts/signal.envelope.v1.json) 及 `tests/test_signal.py` 同款：

```text
user_id_hash = sha256( utf-8( email.lower().strip() ) ) 的 64 位小写 hex
```

**标准向量**（必须写进单测，禁止「我以为」）：

| 输入 | 输出 |
|---|---|
| `alice@example.com` | `ff8d9819fc0e12bf0d24892e45987e249a28dce836a85cad60e28eaaa8c6d976` |
| `Alice@Example.COM` | **同上**（大小写折叠） |
| ` alice@example.com ` | **同上**（strip） |
| `bob@example.com` | `test_signal.py` 的 `HASH_B`（与现文件逐字节相同） |

明文邮箱**不进** JWT、不进 `signal_log`、不进 `--out` JSON。

## 4. 任务（按序，每步有对账命令）

### W0 · 同步与基线（0.5h）

```bash
git fetch origin && git checkout main && git pull --ff-only origin main
git log -1 --oneline
# 期望：含 a06dd69 或其后（L3 + 实验清单已在 main）
cd services/gfcc_kernel && .venv/bin/pytest -q
python3 tools/validate_contracts.py   # 仓库根；L0 仍 1.2.0，信号仍 1.0.0
```

勾选：

- [ ] `HEAD` 已快进到 Gitee `main`
- [ ] 本机 pytest 全绿（项数 ≥ 开工前，只增不减）
- [ ] `validate_contracts.py` 退出 0；**本单全程禁止改 `contracts/`**

### W1 · 抽出 hash 函数（内核可 import，签发脚本可复用）

**做**：在 `gfcc_kernel` 里放一个纯函数（建议 `signal.py` 旁或 `identity` 小工具，**不要**新端口），例如 `email_to_user_id_hash(email: str) -> str`，实现 §3，非法邮箱（空串）抛 `ValueError`。

**验**：

```bash
cd services/gfcc_kernel
.venv/bin/pytest -q tests/test_email_hash.py
```

`test_email_hash.py` 至少覆盖 §3 四行向量 + 空串失败。`HASH_A` 与 `test_signal.py` 必须同一常量来源或同一表达式，禁止两套算法。

勾选：

- [ ] 单测绿
- [ ] `git diff contracts/` 为空

### W2 · 签发脚本增加「从邮箱出号」（additive）

**做**：`scripts/issue_persona_tokens.py` 增加 `--emails`（与 `--subs` **互斥**）。

- `--emails a@x b@y` → 每人 `sub = email_to_user_id_hash(email)`，JWT 只含该 hex
- `--out` JSON 每项形状：`{"sub": "<64 hex>", "token": "..."}`（**禁止**出现 `email` 键）
- 终端：只打 `sub` 与邀请列（现有纪律不变）
- 默认 `--subs tester-a …` **保持**，冒烟场不回归

**验**（本机 `.env` 的 `ETHOS_AUTH_SECRET`，与内核同一把）：

```bash
cd services/gfcc_kernel
.venv/bin/python scripts/issue_persona_tokens.py \
  --emails alice@example.com \
  --out /tmp/bolent_prebind_tokens.json

# sub 必须是标准向量
python3 - <<'PY'
import json
from pathlib import Path
row = json.loads(Path("/tmp/bolent_prebind_tokens.json").read_text())["tokens"][0]
assert row["sub"] == "ff8d9819fc0e12bf0d24892e45987e249a28dce836a85cad60e28eaaa8c6d976"
assert "email" not in row
print("W2 shape OK", row["sub"][:12], "…")
PY
```

内核若在跑：

```bash
TOKEN=$(python3 -c 'import json; print(json.load(open("/tmp/bolent_prebind_tokens.json"))["tokens"][0]["token"])')
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:5211/circle/api/me
# 期望 200，body.sub == ff8d9819… 全 64 位
```

再发一条 `personality_beacon`（`mock_signal_sender` 或手拼信封），`user_id_hash` 用同一 hex：

```bash
# 期望：identity 画像 get_profile(该 hex) 能读到 beacon 留下的 auxiliary trace
# 即：会场 me.sub == 信号 user_id_hash == 画像 sub
```

勾选：

- [ ] `--subs` 旧路径单测仍绿（`test_issue_persona_tokens.py`）
- [ ] `--emails` 新单测：向量、互斥、`--out` 无 email
- [ ] `/circle/api/me` 的 `sub` 与 beacon 的 `user_id_hash` 逐字节相同

### W3 · 户口本 fixture（本仓可验 schema，不是生产库）

**做**：新增 `docs/experiments/bolent_membership.fixture.json`（或 `services/gfcc_kernel/data/` 下 **不入库密钥** 的样例）。一行一个节点，字段**只准**这些：

```json
{
  "schema": "bolent.membership.v0",
  "hash_alg": "sha256(email.lower().strip()) utf-8 hex",
  "note": "真源将在 Bolent/genz 社区壳；本文件只作预埋样例。status: applied | active | left",
  "members": [
    {
      "email_hash": "ff8d9819fc0e12bf0d24892e45987e249a28dce836a85cad60e28eaaa8c6d976",
      "bolent_site_id": "site_bolent_demo_1",
      "status": "active"
    }
  ]
}
```

**禁止**：fixture 里写明文邮箱、token、ETHOS 密钥。

**验**：一段 ≤30 行的测试或脚本（可放 `tests/test_bolent_membership_fixture.py`）：

1. JSON 可解析；`members[]` 每项恰有 `email_hash` / `bolent_site_id` / `status`
2. `email_hash` 匹配 `^[a-f0-9]{64}$`
3. `status ∈ {applied, active, left}`
4. `alice` 那行的 hash = §3 向量
5. **不** import 生产 DB

勾选：

- [ ] fixture 入库且测试绿
- [ ] 仍无 `contracts/` 变更

### W4 · 门户户口本（可选，本周不卡 A+B）

若 Windows 同时改 `szbolent-portal`：按同一 schema 建表或 JSON 文件即可，**不要**在 Looma 用户表上加 `site_id` 冒充 1:1。有第一条真实 `status=active` 之后，另开信号单加 `node_joined`（次版本），**不要**提前改信封枚举。

勾选（有则勾，无则写「缓办」）：

- [ ] 缓办 / 已建表（圈选）
- [ ] 建表的话：至少 1 行 hash 能与 W2 签发的 `sub` 对上

### W5 · 双推与回归门

```bash
# 仓库根
python3 tools/validate_contracts.py
cd services/gfcc_kernel && .venv/bin/pytest -q
git diff --stat contracts/    # 必须空
# 先 Gitee 再 GitHub，见 GITHUB_MIRROR.md §4
```

勾选：

- [ ] Gitee `main` 已含本单提交
- [ ] GitHub 镜像同一 SHA
- [ ] CI `test-kernel` + `test-contracts` 绿
- [ ] CHANGELOG 一行：预埋邮箱签发 + fixture，**未** bump 契约

## 5. 总验收（Windows 交件口径）

**预埋通过** = 下列全部为真：

1. `alice@example.com` → JWT `sub` = `ff8d9819…c6d976`，`/circle/api/me` 同值。  
2. 对该 `sub` 发 `personality_beacon`，画像 `sub` 同值（已有 ingest 路径）。  
3. fixture 一行能指回该 hash + 一个 `bolent_site_id`。  
4. `contracts/` 无 diff；L0 1.2.0、信号 1.0.0。  
5. `tester-a` 旧签发路径未坏。

**不叫通过**：只写了文档没有单测；`--out` 里出现邮箱；把 `site_id` 写进 identity 契约。

## 6. 和第一场真人会

本单**不改** testers 须知入口，不挡 IP `/circle/` 占位令牌场。社区作者入场时再改用 `--emails`。主持人认领席位仍是场务（知道对面是谁），协议只认这个号点了头。

## 7. 回报格式（群里可粘贴）

```
Bolent 预埋 Windows
HEAD: <sha>
W1 pytest: pass/fail
W2 me.sub == HASH_A: pass/fail
W3 fixture: pass/fail
contracts diff: empty / NOT empty
Gitee/GitHub: 已双推 / 未推
户口本真表: 缓办 / 已建（仓名+表名）
```

---

*与 Step3 Windows 开工清单同一套纪律：一步一双推、测试只增不减、契约冻结后不许悄悄改字段。本单冲突时以 VERSIONING 红线为准。*
