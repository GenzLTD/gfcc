# Step 1-2 实施建议 — llm 槽接 Ollama + store 槽切 SQLite

> **状态：已收口**——Step1-2 已实施完成（llm 槽接 Ollama、store 槽接 SQLite 均已上线，见 CHANGELOG），本文为历史实施建议。  
> **2026-08-27 对照**：sqlite 持久化的是 `memory_records` 与 `signal_log`；circle / consensus / identity / session 仍内存，勿把「store 已切 SQLite」读成围坐态重启不丢。
> 致：Windows 端项目组
> 来自：Mac 侧（契约对齐 + 信号层设计）
> 日期：2026-08-20
> 前提：gfcc_kernel 1.1.0 stub 模式已验收 PASS（5211 金丝雀，6 场景全绿）

---

## 为什么先做这两步

我们在 Mac 侧准备 Step 3：把 gfcc_kernel 接入 THOMAS 信号层（consensus_match / personality_beacon 等 webhook 信号）。但信号层对接有一个硬前提——**内核必须能"理解"外部信号、能"记住"信号数据**。

当前状态：
- dispatcher 的 `parse_port` 是关键词规则匹配（`PORT_KEYWORDS` 字典），不是语义理解。外部信号 payload 里的 JSON 字段它匹配不到。
- store 槽是内存 dict（`StubStore._records`），进程重启即空。信号数据写进去就没了。

所以 Step 1-2 不是"锦上添花"，是 Step 3 的**前置依赖**。做完这两步，Mac 侧才能把 THOMAS 信号桥接进来。

---

## Step 1：llm 槽接 Ollama

### 目标

`parse_port` 从关键词规则解析升级为 LLM 语义分类。用户说自然语言（或外部信号带自然语言 message），LLM 输出 `{port, confidence, slots, dialog_mode}`。

### 改动范围

| 文件 | 改动 |
|------|------|
| `slots.py` → `OllamaLLM` 类 | 新增，继承 `LLMProvider`，实现 `is_available()` + `complete()` |
| `dispatcher.py` → `parse_port` | 优先调 llm 槽；llm 不可用时 fallback 到现有关键词规则 |
| `app.py` 或 `slots.py` 初始化 | 按 env `LLM_PROVIDER=ollama` 切换 |

### 技术要点

**1. Ollama 调用**

Ollama 本地 API：`POST http://localhost:11434/api/chat`

请求体示例：
```json
{
  "model": "qwen2.5:7b",
  "messages": [
    {"role": "system", "content": "你是格契内核的意图分类器。根据用户消息判断属于哪个端口。可选端口：circle(围坐)、identity(身份画像)、memory(记忆)、consensus(共议)、contribution(贡献)。输出JSON：{\"port\": \"...\", \"confidence\": 0.0-1.0, \"reason\": \"一句话理由\"}。如果都不匹配，输出{\"port\": \"unknown\", \"confidence\": 0.0}。"},
    {"role": "user", "content": "<用户消息>"}
  ],
  "format": "json",
  "stream": false
}
```

关键：`"format": "json"` 让 Ollama 强制输出合法 JSON，省掉正则解析。

**2. fallback 策略**

```python
def parse_port(message, port_hint=None):
    # port_hint 优先（不变）
    if port_hint and port_hint in FIRST_CLASS_PORTS:
        return port_hint, 1.0
    
    # 尝试 LLM
    if ctx.llm and ctx.llm.is_available():
        try:
            result = ctx.llm.complete([{"role": "user", "content": message}])
            port = result.get("port", "unknown")
            confidence = float(result.get("confidence", 0.0))
            if port in FIRST_CLASS_PORTS or port == "unknown":
                return port, confidence
        except Exception:
            pass  # fallback to keywords
    
    # fallback: 现有关键词规则（保留不删）
    return _parse_port_keywords(message)
```

把现有的关键词逻辑提取成 `_parse_port_keywords` 私有函数，LLM 失败时调用。**不要删掉关键词规则**——它是兜底，也是 CI 测试的基准。

**3. 环境变量**

```bash
# .env.example 新增
LLM_PROVIDER=ollama          # stub | ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b      # 或其他已 pull 的模型
```

留空或不配 = 仍然用 stub（`is_available()` 返回 False）。

### 验收标准

| 场景 | 输入 | 期望 port |
|------|------|----------|
| 自然语言建圈 | "我们几个人想一起搞个学习小组" | circle |
| 自然语言记忆 | "把今天讨论的定价策略存一下" | memory |
| 自然语言共识 | "大家对这个方案有没有意见，没意见就定了" | consensus |
| 模糊输入 | "你好" | unknown |
| LLM 离线 fallback | 断开 Ollama 后输入"记住今天开会" | memory（关键词兜底） |

---

## Step 2：store 槽切 SQLite

### 目标

`StubStore`（内存 dict）升级为 `SQLiteStore`，重启不丢数据。对齐 `memory.v1.json` 的 store_slot 接口：`put / get / query / supersede`。

### 改动范围

| 文件 | 改动 |
|------|------|
| `slots.py` → `SQLiteStore` 类 | 新增，实现 `put/get/query/supersede/count` |
| `slots.py` 初始化 | 按 env `STORE_PROVIDER=sqlite` 切换 |
| `app.py` | 启动时打印 store 类型（方便日志确认） |

### 技术要点

**1. 表结构**

一张表够了，`library` 列区分七库：

```sql
CREATE TABLE IF NOT EXISTS memory_records (
    id          TEXT PRIMARY KEY,
    library     TEXT NOT NULL,          -- issue/action/event/methodology_value/person/org/resource
    body        TEXT NOT NULL,          -- JSON string
    actor_sub   TEXT,
    circle_id   TEXT,
    created_at  TEXT NOT NULL,
    superseded_at TEXT,                 -- 非空 = 已被替代
    superseded_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_library ON memory_records(library);
CREATE INDEX IF NOT EXISTS idx_circle ON memory_records(circle_id);
CREATE INDEX IF NOT EXISTS idx_active ON memory_records(superseded_at) WHERE superseded_at IS NULL;
```

**2. 接口对齐**

`SQLiteStore` 必须实现跟 `StubStore` 完全一样的公开方法签名：

```python
class SQLiteStore:
    def __init__(self, db_path: str = "data/memory.db"):
        # 建表
        
    def put(self, record: Dict) -> Dict:
        # INSERT，返回带 id 的 record
        
    def get(self, rid: str) -> Optional[Dict]:
        # SELECT WHERE id = ?
        
    def query(self, filter_fn=None, limit=50) -> List[Dict]:
        # SELECT * FROM memory_records WHERE superseded_at IS NULL
        # filter_fn 是 Python 回调，在内存里过滤（数据量小，不用下推 SQL）
        
    def supersede(self, rid, new_body, actor_sub, observed_by="human") -> Optional[Dict]:
        # UPDATE 旧记录 SET superseded_at/by
        # INSERT 新记录
        # 注意：observed_by=ai 时不能静默改写（契约红线，跟 StubStore 一致）
        
    def count(self) -> int:
        # SELECT COUNT(*) WHERE superseded_at IS NULL
```

**3. supersede 的事务**

```python
def supersede(self, rid, new_body, actor_sub, observed_by="human"):
    conn = self._conn
    with conn:  # 事务
        conn.execute("UPDATE memory_records SET superseded_at=?, superseded_by=? WHERE id=?",
                      (_now(), actor_sub, rid))
        new_id = str(uuid.uuid4())
        conn.execute("INSERT INTO memory_records (...) VALUES (...)",
                      (new_id, ...))
    return new_record
```

`with conn:` 自动提交/回滚。

**4. 环境变量**

```bash
# .env.example 新增
STORE_PROVIDER=sqlite        # stub | sqlite
STORE_DB_PATH=data/memory.db
```

**5. 文件路径**

db 文件放在 `services/gfcc_kernel/data/memory.db`，跟 `logs/audit.db` 同级。`.gitignore` 里加 `data/`。

### 验收标准

| 场景 | 操作 | 期望 |
|------|------|------|
| 写入+读取 | `put` 一条记录 → `get(id)` | 返回完整记录 |
| 重启持久化 | `put` → 重启进程 → `get(id)` | 数据还在 |
| query 过滤 | `put` 3 条不同 library → `query(filter_fn=lambda r: r["library"]=="issue")` | 只返回 issue |
| supersede | `put` A → `supersede(A.id, new_body)` → `get(A.id)` | 旧记录有 `superseded_at`，新记录 `superseded_at` 为空 |
| count | 写 3 条，supersede 1 条 → `count()` | 2（只算未被替代的） |
| 切回 stub | `STORE_PROVIDER=stub` | 行为跟现在一致 |

---

## 两步的依赖关系

Step 1 和 Step 2 **互不依赖**，可以并行做。但 Step 3 依赖两者都完成：

```
Step 1 (llm) ─┐
              ├──→ Step 3 (THOMAS 信号层对接)
Step 2 (store)┘
```

Step 3 时 Mac 侧会做这些事（你们不用管）：
- THOMAS 的 consensus_match 信号 → POST /v1/ask（message 里带信号描述）→ dispatcher 用 LLM 识别 → consensus 端口处理
- 信号数据 → memory 端口 → SQLiteStore 持久化
- 如果 llm 还是规则解析、store 还是内存 dict，信号进来也存不住、理解不了

---

## 时间预估

| 步骤 | 工作量 | 说明 |
|------|--------|------|
| Step 1 | ~1 天 | Ollama 环境 + OllamaLLM 类 + dispatcher 改造 + 5 个验收场景 |
| Step 2 | ~1 天 | SQLiteStore 类 + 建表 + 6 个验收场景 + .env 配置 |
| 合计 | ~2 天 | 如果并行可能 1 天 |

模型选型建议：`qwen2.5:7b` 起步（中文好、体积小），如果效果不够再换大的。Ollama 里 `ollama pull qwen2.5:7b` 即可。

---

## 不需要动的部分

- `ports/` 五个端口文件 — 不改。端口逻辑跟 store 实现无关，因为端口调的是 store 槽的接口，不关心底层是 dict 还是 SQLite。
- `registry.py` — 不改。五端口注册表跟 llm/store 无关。
- `security.py` / `envelope.py` — 不改。信封和认证逻辑跟存储无关。
- `contracts/` — 不改。契约是 1.1.0，实现层升级不碰契约层。

这就是槽位抽象设计的好处——换实现不碰契约。

---

## 完成后通知 Mac 侧

Step 1-2 验收通过后，Mac 侧开始 Step 3：
1. 设计 THOMAS 信号 → gfcc `/v1/ask` 的信封映射
2. 在 THOMAS 的 `ECOSYSTEM_SIGNAL_ADAPTER_GUIDE.md` 里新增 gfcc 对接章节
3. 复用 SurfaceZervi 已验证的信封 + HMAC + mock 节奏

两边并行，你们推 Step 1-2，我们准备 Step 3 契约方案。Step 1-2 done 后直接进 Step 3。
