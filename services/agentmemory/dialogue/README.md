# dialogue_library · 对话库（情景记忆子集）

GFCC 记忆体体系的"对话/情景记忆"工具集：**代码随仓库交付，数据各自本地**。

- 仓库代码：`services/agentmemory/dialogue/`（本目录）
- 种子样例：`docs/examples/dialogue_library_seed.jsonl`
- 本地运行实例：`E:\CorpusPipeline\dialogue_library\`（Windows 侧；数据目录 `data/` 被 .gitignore 忽略，不入库）

## 三库定位

```
知识库  DemoPeter / ChromaDB RAG（38 万向量，端口 5200）
记忆体  services/agentmemory          （HTTP 3111，存 fact/decision）
对话库  本工具集                      （情景记忆：对话历史持久化 + 可检索）
```

对话库不是与知识库、记忆体平级的第三类，而是**记忆体的一个子集（情景记忆）**——负责"谁、何时、说了什么"的流水留痕与 recall。

## 目录结构

```
services/agentmemory/dialogue/
├── schema.sql   # 建表 + FTS5 trigram 索引（v1.0.0）
├── store.py     # 写入端：init / session / append / import-jsonl
├── query.py     # 检索端：recall / transcript / list-sessions / stats
└── README.md
```

## 快速开始

数据默认落在本目录 `data/`（自动被 .gitignore 忽略）；生产/日常使用建议用 `--db` 指向仓库外数据目录，避免在仓库内堆积运行数据。以下命令从 `services\agentmemory\dialogue` 目录执行（`--db` 为顶层参数，须放在子命令前）。

```powershell
# 1. 建库（幂等）
python store.py --db E:\CorpusPipeline\dialogue_library\data\dialogue.db init

# 2. 批量导入种子样例（UTF-8 文件，规避 PowerShell 中文乱码）
python store.py --db E:\CorpusPipeline\dialogue_library\data\dialogue.db import-jsonl --file D:\gfcc\docs\examples\dialogue_library_seed.jsonl

# 3. 检索（≥3 字符走 FTS5 trigram，<3 字符自动回退 LIKE）
python query.py --db E:\CorpusPipeline\dialogue_library\data\dialogue.db recall 本机复核 --limit 5
python query.py --db E:\CorpusPipeline\dialogue_library\data\dialogue.db recall ea76e86

# 4. 回看 / 清单 / 统计
python query.py --db E:\CorpusPipeline\dialogue_library\data\dialogue.db transcript <session_id>
python query.py --db E:\CorpusPipeline\dialogue_library\data\dialogue.db list-sessions
python query.py --db E:\CorpusPipeline\dialogue_library\data\dialogue.db stats
```

## Schema 约定（v1.0.0）

| 表 | 字段 | 说明 |
|---|---|---|
| `sessions` | `kind` | `collab`=协作 / `coach`=教练（对应 `dialog_mode` 双轨） |
| `turns` | `role` | user / assistant / ai / system |
| | `mode` | 双轨对话模式（协作 / 教练） |
| | `signal_ref` | 关联 GFCC 契约信号，如 `THOMAS:5211:v1.0.0` |
| | `channel` | 来源：gfcc / demopeter / agentmemory / manual |
| | `ts` | ISO8601 UTC，与 agentmemory 时间戳风格一致 |
| `turns_fts` | FTS5 | `trigram` tokenizer，中文短语可查，触发器自动同步 |

## 对接方式

- **GFCC 对话**：G3 绿灯、对话链路落地后，`channel=gfcc`、`signal_ref` 挂契约信号，用 `import-jsonl` 或 `append` 批量入库。
- **agentmemory 融合**：agentmemory 存"观察/决策"（`fact/decision`），本库存"原始对话流水"——两者按 `sessionId` 对应；未来可把对话摘要提炼成 `fact` 写入 agentmemory，形成"对话 → 记忆"升华链路。
- **向量化扩展（可选）**：用 DemoPeter 的 `nomic-embed-text` 将 `turns.content` 嵌入 Chroma 新 collection（如 `dialogue_index`），即可获得语义 recall。

## 注意

- PowerShell 5.1 下命令行直接传中文参数会乱码，**建议用 `import-jsonl` 走 UTF-8 文件导入**。
- `import-jsonl` 是追加式导入：重复导入会翻倍，重建请先删 `data/dialogue.db*` 再 `init`（PowerShell 下逐个文件删除，避免多文件一并删除时因部分文件不存在而整体失败）。
- 数据目录 `data/` 已在 .gitignore 忽略（`data/` 规则），运行数据不会进版本库；`seed.jsonl` 样例随 docs 交付，供参考。
