# szpeter2026 知识库平台

> Your Personal Knowledge Base, Powered by RAG

一个现代、轻量、功能完整的本地知识库管理平台。支持多格式文档导入、智能分块、向量检索、RAG 问答、Web 管理面板、日/周/月报告生成，以及 **D 盘 28 个项目代码自动索引导航**（364k 向量 / 1.8 万文件，支持断点续传）。

---

## 🏗️ 架构设计

```
szpeter2026/
├── config/                  # 配置中心
│   ├── settings.py          # 统一配置（.env + 默认值）
│   ├── logging_config.py    # 日志配置
│   └── corpora.json         # 语料配置
├── static/src/              # 核心引擎（Web 仪表盘）
│   ├── db_manager.py        # 元数据库管理器（SQLite）
│   ├── doc_processor.py     # 文档处理管道（PDF/MD/TXT → 智能分块）
│   ├── vector_store.py      # Chroma 向量存储
│   ├── rag_engine.py        # RAG 检索引擎（检索→增强→生成）
│   ├── ai_client.py         # AI 统一客户端（DeepSeek / Ollama）
│   ├── report_gen.py        # 报告生成器（日/周/月报）
│   ├── hybrid_search.py     # 混合搜索（向量 + FTS5 RRF 融合）
│   └── web_dashboard.py     # Flask Web 管理面板
├── d_indexer/               # D 盘自动代码索引
│   ├── scanner.py           # 文件扫描器（os.walk + 可索引扩展名过滤）
│   ├── indexer.py           # Chroma 向量索引器（支持断点续传）
│   ├── checkpoint.py        # SQLite 断点管理器（持久化扫描状态）
│   ├── scheduler.py         # 每日定时扫描调度器
│   └── projects.py          # D 盘项目根目录列表（28 个）
├── chronicle/               # 时光纪（浏览历史/知识轨迹）
├── templates/               # Web 前端模板
│   ├── base.html            # 基础布局
│   ├── index.html           # 仪表盘
│   ├── documents.html       # 文档管理
│   ├── query.html           # RAG 问答（支持流式）
│   ├── reports.html         # 报告中心
│   └── d_index.html         # D 盘索引导航
├── static/css/style.css     # 现代 UI 样式
├── scripts/                 # 运维脚本
│   ├── manage.ps1           # 统一管理脚本（PowerShell）
│   ├── import_docs.py       # 批量文档导入
│   ├── query.py             # CLI 查询工具
│   └── gen_report.py        # 报告生成
├── knowledge_base/          # 知识库存储
│   ├── documents/           # 原始文档（md/pdf/txt）
│   └── chunks/              # 分块缓存
├── db/                      # 数据库
│   ├── szpeter2026.db       # SQLite 元数据 + 断点 + 文件缓存
│   ├── schema.sql           # 完整表结构参考
│   ├── d_index_data/        # Chroma 持久化向量数据（本地模式）
│   └── d_index_v2/          # 备用 Chroma 目录
├── docs/                    # 项目文档
├── tests/                   # 测试套件
└── reports/                 # 报告输出
```

## 🎯 核心能力

| 模块 | 功能 | 吸收来源 |
|------|------|----------|
| **文档管道** | PDF/MD/TXT → 文本提取 → 智能分块（保留段落/章节边界） | HKIE + Wukong |
| **向量检索** | Chroma 语义搜索 + 混合搜索（向量 + FTS5 RRF 融合） | 72changes |
| **RAG 引擎** | 检索增强生成（检索→上下文增强→AI 生成） | 72changes |
| **AI 客户端** | DeepSeek API / Ollama 本地模型，双模式一键切换 | Wukong ai_sql |
| **元数据库** | SQLite 管理文档/分块/查询日志 | Wukong metadata |
| **Web 面板** | Flask 仪表盘 + 文档管理 + 流式问答 + 报告 | Wukong web_dashboard |
| **报告系统** | 日/周/月报自动生成 | Wukong report_gen |
| **D 盘代码索引** | 自动扫描 22 个项目目录 → 代码语义搜索 → "那个做跨境电商的项目在哪" | 自研 |
| **断点续传** | 目录级 checkpoint + 文件级缓存，崩溃后从中断处自动恢复 | 自研 |

---

## 🔌 断点续传扫描（D-Indexer）

### 为什么需要

D 盘 28 个项目根目录，包含 `surface-zervi`（31 个 git 子仓库）等庞然大物，63,026 个可索引文件，全量扫描耗时约 2.5 小时。如果中途断电/crash/OOM，**所有进度归零**。

### 机制设计

```
┌─────────────────────────────────────────────────┐
│                   DIndexer                       │
│  ┌──────────┐   ┌──────────────┐   ┌──────────┐│
│  │ Scanner   │ → │ Checkpoint   │ → │ ChromaDB ││
│  │ (续传模式)│   │ Manager      │   │ (upsert) ││
│  └──────────┘   └──────┬───────┘   └──────────┘│
│                        │                        │
│              ┌─────────▼──────────┐             │
│              │  SQLite (WAL)      │             │
│              │  scan_checkpoints  │             │
│              │  indexed_files_cache│            │
│              └────────────────────┘             │
└─────────────────────────────────────────────────┘
```

- **目录级断点**：每处理完一个目录立即持久化，崩溃后跳过已完成目录（通过 `os.walk` 的 `dirnames.remove()` 直接跳过，零开销）
- **文件级缓存**：`indexed_files_cache` 表存 `(path, size, mtime, fingerprint)`，三者全匹配 → 不读文件、不查 ChromaDB、直接跳过
- **自动续传**：调度器启动时检测 `in_progress` 状态，自动从中断处继续

### API 端点

```bash
# 查看所有项目的断点/扫描进度
GET  /api/d-index/checkpoint

# 增量扫描（仅索引变更文件，文件缓存加速）
POST /api/d-index/scan  {"mode": "incremental"}

# 断点续传（从中断处继续未完成的扫描）
POST /api/d-index/scan  {"mode": "resume"}

# 强制全量扫描（重置所有断点，从头开始）
POST /api/d-index/scan  {"mode": "full"}

# 重置某个项目的断点
POST /api/d-index/checkpoint/reset  {"project_root": "D:/jobfirst-claw"}

# 删除项目文件缓存
DELETE /api/d-index/checkpoint  {"project_root": "D:/jobfirst-claw"}

# D 盘代码语义搜索
POST /api/d-index/search  {"query": "用户认证逻辑在哪里", "top_k": 10}
```

### 效果对比

| 场景 | 无断点 | 断点续传 |
|------|--------|----------|
| 扫描到 75% 崩溃 | 从头开始，白费数小时 | 跳过已完成目录完成剩余 |
| 实战检验 | — | **三次中断（休眠/重启），每次都续上，28/28 项目全完成** |
| 次日增量扫描 | 读取全部文件 + 逐个查 ChromaDB | 79k 文件缓存命中直接跳过 (10-100x 加速) |
| 最终成果 | — | 364k 向量 / 1.8 万文件 / 2.5h 累计耗时 |

---

## 🚀 快速开始

### 1. 环境准备

```powershell
# 进入项目目录
cd E:\szpeter2026

# 一键初始化（安装依赖 + 创建配置）
.\scripts\manage.ps1 -Action setup
```

### 2. 配置 AI

编辑 `.env` 文件，填入 API Key：

```env
# 使用 DeepSeek（推荐）
DEEPSEEK_API_KEY=sk-your-key-here
AI_PROVIDER=deepseek

# 或使用 Ollama 本地模型
# AI_PROVIDER=ollama
# OLLAMA_MODEL=qwen2:latest

# Chroma 持久化目录（D-Indexer 本地模式）
CHROMA_PERSIST_DIR=./db/d_index_data
```

### 3. 启动向量数据库容器（Docker，可选）

```powershell
# 一键启动 Chroma + pgvector（数据持久化到 db/ 目录）
.\scripts\manage.ps1 -Action docker-up

# 查看状态
.\scripts\manage.ps1 -Action docker-status

# 停止容器（保留数据）
.\scripts\manage.ps1 -Action docker-down
```

> **注意**：Chroma 默认使用本地 PersistentClient 模式（无需 Docker），数据存储在 `.env` 指定的 `CHROMA_PERSIST_DIR`（当前联调主库为 `db/merged_chroma`，约 4.4GB）。Docker 模式（`CHROMA_MODE=auto` + `CHROMA_HOST`/`CHROMA_PORT`）仅在需要远程访问 Chroma 时使用。

### 4. 启动 Web 面板

```powershell
.\scripts\manage.ps1 -Action web
# 访问 http://127.0.0.1:5220
```

> **本机联调实测（Windows）**：直接启动（加载约 4.4GB 合并向量库需 2-3 分钟）：
> ```powershell
> cd E:\DemoPeter
> .\.venv\Scripts\python.exe static\src\web_dashboard.py
> # 访问 http://127.0.0.1:5220
> ```
> 端口由 `.env` 的 `WEB_HOST=127.0.0.1` / `WEB_PORT=5220` 控制；Chroma 使用本地持久化主库 `CHROMA_MODE=persistent` + `CHROMA_PERSIST_DIR=E:/DemoPeter/db/merged_chroma`，无需 Docker 容器即可运行。

面板启动后，D-Indexer 调度器会在后台自动运行：
- **首次启动**：检测是否有未完成的扫描 → 自动续传
- **每日凌晨 3:00**：定时增量扫描（仅索引变更文件）

### 5. 手动触发扫描

```powershell
# 通过 API 触发
curl -X POST http://127.0.0.1:5220/api/d-index/scan \
  -H "Content-Type: application/json" \
  -d '{"mode": "resume"}'
```

---

## 📖 使用指南

### Web 面板

| 页面 | 功能 |
|------|------|
| **仪表盘** | 实时统计、快速问答、系统状态 |
| **D 盘索引** | 代码语义搜索、项目导航、扫描进度、断点状态 |
| **文档管理** | 批量导入、文档列表、详情预览、删除 |
| **RAG 问答** | 流式对话、多轮对话、来源追踪、参数调节 |
| **报告中心** | 日报/周报/月报生成、查询历史 |

### CLI 工具

```powershell
# Docker 容器管理
.\scripts\manage.ps1 -Action docker-up       # 启动向量数据库容器
.\scripts\manage.ps1 -Action docker-down     # 停止容器（保留数据）
.\scripts\manage.ps1 -Action docker-status   # 健康检查
.\scripts\manage.ps1 -Action docker-reset    # 清除所有数据

# 命令行查询
python scripts\query.py "知识库中有哪些关于XXX的内容？"

# 查看统计
.\scripts\manage.ps1 -Action stats

# 生成报告
.\scripts\manage.ps1 -Action report

# 运行测试
.\scripts\manage.ps1 -Action test
```

---

## 🔧 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | Python 3.10+ / Flask 3.1 / SQLite (WAL) |
| **向量库** | ChromaDB (PersistentClient 本地模式 / 可选 Docker) |
| **AI** | DeepSeek API / Ollama（本地模型） |
| **文档处理** | pdfplumber / pypdf / python-docx / markdown |
| **断点续传** | SQLite checkpoint 表 + 文件级索引缓存 |
| **前端** | Jinja2 模板 + 原生 HTML/CSS/JS（零框架依赖） |
| **容器化** | Docker Compose（Chroma + pgvector + Nginx） |

---

## 📂 数据流程

```
┌──────────────────────────────────────────────┐
│              文档知识 (Knowledge Base)         │
│                                               │
│  文档文件 (PDF/MD/TXT)                        │
│      ↓ doc_processor.py                      │
│  文本提取 + 智能分块                           │
│      ↓                                        │
│  SQLite 元数据库 (documents + chunks)          │
│      ↓ vector_store.py                       │
│  Chroma 向量嵌入                              │
│      ↓ rag_engine.py                         │
│  用户查询 → 向量检索 → 上下文增强 → AI 回答    │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│             代码索引 (D-Indexer)               │
│                                               │
│  22 个 D 盘项目目录                            │
│      ↓ scanner.py (os.walk 过滤)              │
│  可索引文本文件 (py/js/ts/go/rs/md/...)       │
│      ↓ checkpoint.py (读断点/查缓存)           │
│  跳过已完成目录 + 未变更文件                    │
│      ↓ indexer.py                            │
│  Chroma 向量嵌入 + 文件缓存更新                │
│      ↓ D-Indexer 搜索                        │
│  "跨境电商项目在哪里" → 语义搜索 → 定位代码     │
└──────────────────────────────────────────────┘
```

---

## 📊 元数据库表结构

### 文档知识库表

| 表 | 说明 |
|----|------|
| `documents` | 文档注册表（标题、路径、类型、状态） |
| `chunks` | 分块表（文档→分块索引→内容→字符数） |
| `query_logs` | 查询日志（问题、AI 提供商、耗时） |

### D-Indexer 断点表

| 表 | 说明 |
|----|------|
| `scan_checkpoints` | 扫描断点（项目目录 → 状态 → 已完成目录列表 → 进度计数） |
| `indexed_files_cache` | 文件索引缓存（路径 → 大小 → 修改时间 → 指纹，三元匹配跳过重索引） |

---

## 🧪 测试

```powershell
.\scripts\manage.ps1 -Action test
```

---

## 📝 许可证

MIT License
