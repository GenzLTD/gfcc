# Cursor 对话导入指南

## 概述

将 `C:\Users\HUAWEI\.cursor\projects\` 下的 AI 辅助开发对话导入 DemoPeter RAG 知识库，实现"为什么这样设计"的语义检索。

### 数据规模

| 指标 | 数值 |
|------|------|
| Cursor 项目目录 | ~188 个（含 110+ 临时目录） |
| 实际项目 | ~30 个 |
| JSONL 对话文件 | ~91 个 |
| 预估总字符 | ~10 MB+ |
| 预估 Chroma 向量 | ~5,000-8,000 条 |

## 快速开始

### 1. 预览（推荐先执行）

```powershell
cd C:\Users\HUAWEI\DemoPeter
python scripts/import_cursor_transcripts.py --dry-run
```

这会扫描所有 Cursor 对话文件，显示统计但不写入 Chroma。

### 2. 正式导入

```powershell
python scripts/import_cursor_transcripts.py
```

### 3. 同时生成 Chronicle 事件

```powershell
python scripts/import_cursor_transcripts.py --chronicle
```

这会额外生成 Chronicle 事件种子文件到 `db/chronicle_seeds/`。

### 4. 导入 Chronicle 事件

```powershell
# 方式 A：从种子文件导入
python -m scripts.seed_chronicle --seed db/chronicle_seeds/cursor_seed_20260612_090000.json

# 方式 B：直接从 Cursor 对话提取并导入
python -m scripts.seed_chronicle --from-cursor
```

## 常用命令

```powershell
# 仅导入指定项目
python scripts/import_cursor_transcripts.py --project Nezha
python scripts/import_cursor_transcripts.py --project "数据库优化"

# 强制重新导入（覆盖已有数据）
python scripts/import_cursor_transcripts.py --force

# 在已导入的对话中搜索
python scripts/import_cursor_transcripts.py --search "SmartJobs Consul 服务注册"

# Chronicle 预览
python -m scripts.seed_chronicle --from-cursor --dry-run
```

## 项目映射

导入脚本自动将 Cursor 项目目录映射到友好的项目名和 D 盘路径：

| Cursor 目录 | 项目名 | D 盘路径 |
|-------------|--------|----------|
| `d-ServBay-www-zervi-rust` | Zervi-Rust 中央大脑 | D:/surface-zervi |
| `e-Nezha` | Nezha Spring AI | D:/Nezha |
| `e-Iamgeek` | Iamgeek 匿名社区 | D:/Iamgeek |
| `e-SmartJobs` | SmartJobs 智能招聘 | D:/SmartJobs |
| `e-StudyDaily-TimesSquare-main` | TimesSquare 知识库 | D:/TimesSquare |
| `c-Users-HUAWEI-DataGripProjects-Qiankun` | Qiankun 数据库优化 | - |
| ... | ... | ... |

完整映射见 `scripts/cursor_parser.py` 中的 `PROJECT_MAPPING` 字典。

## Chroma Collection

| 属性 | 值 |
|------|-----|
| Collection 名 | `cursor_conversations` |
| Embedding 模型 | all-MiniLM-L6-v2 (Chroma 默认) |
| 存储路径 | `db/chroma_data/` |
| 元数据字段 | session_id, project_name, d_project, tags, turn_start, turn_end |

## 分块策略

- **按对话轮次边界分块**，不按固定字符数切分
- 每块最多 2000 字符
- 块间重叠 300 字符（保留上下文连贯性）
- 跳过 Cursor 临时目录（`C-Users-HUAWEI-AppData-Local-Temp-*`）

## 脱敏规则

导入时自动处理以下敏感信息：

| 模式 | 替换为 |
|------|--------|
| IP 地址 | `[IP]` |
| API Key (sk-...) | `[API_KEY]` |
| 密码字段 | `[REDACTED]` |
| Secret 字段 | `[REDACTED]` |

## 在 Web 面板中使用

导入完成后，在 DemoPeter Web 面板中搜索时，结果会自动包含对话内容：

```
http://127.0.0.1:5220/query
```

示例查询：
- "Nezha 为什么要从 zervi.test 底座升级？"
- "SmartJobs 的服务注册用的是什么方案？"
- "Iamgeek Admin 后台技术选型讨论"
- "数据库 app_secret 哈希化方案"

## 架构关系

```
Cursor 项目目录
  └─ import_cursor_transcripts.py  ──→  Chroma "cursor_conversations"
  └─ cursor_parser.py              ──→  解析 + 脱敏 + 分块
  └─ seed_chronicle.py             ──→  Chroma "chronicle" (事件)
                                          │
D-Indexer (已有)                    ──→  Chroma "d_drive_index" (代码)
                                          │
Web 面板 RAG 引擎                   ──→  跨 collection 检索
                                          │
                                    代码 + 对话 = 完整知识图谱
```

## 增量更新

后续 Cursor 产生新对话后：

```powershell
# 增量导入（自动跳过已导入的会话）
python scripts/import_cursor_transcripts.py

# 如果某个项目的对话更新了，强制覆盖
python scripts/import_cursor_transcripts.py --project Zervi --force
```

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| `ModuleNotFoundError: No module named 'chromadb'` | `pip install chromadb onnxruntime` |
| Chroma 初始化失败 | 确认 `db/chroma_data/` 目录存在且可写 |
| JSONL 解析失败 | 检查文件编码（应为 UTF-8），跳过损坏文件 |
| 导入后搜索无结果 | 先确认向量数 > 0：查看 Web 面板仪表盘 |
