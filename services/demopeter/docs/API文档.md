# szpeter2026 知识库 API 文档

Base URL: `http://127.0.0.1:5220`

---

## 统计

### GET /api/stats

获取知识库统计信息。

**响应：**
```json
{
    "documents_total": 42,
    "documents_completed": 38,
    "documents_pending": 4,
    "chunks_total": 1560,
    "total_characters": 1250000,
    "queries_total": 230,
    "vector": {
        "available": true,
        "collection_name": "szpeter2026_kb",
        "total_vectors": 1560
    },
    "ai_provider": "deepseek"
}
```

---

## 文档管理

### GET /api/documents

获取文档列表。

参数：`?status=completed`（可选：completed/pending/failed）

### GET /api/documents/:id

获取文档详情（含分块）。

### POST /api/documents/import

批量导入文档。

**请求体：**
```json
{
    "directory": "E:\\szpeter2026\\knowledge_base\\documents"
}
```

### DELETE /api/documents/:id

删除文档及其所有分块和向量数据。

---

## RAG 问答

### POST /api/rag/query

RAG 问答（同步）。

**请求体：**
```json
{
    "query": "你的问题",
    "top_k": 5,
    "threshold": 0.5
}
```

**响应：**
```json
{
    "query": "你的问题",
    "answer": "回答内容...",
    "sources": [
        {
            "content": "相关内容片段...",
            "source": "document.md",
            "similarity": 0.85
        }
    ],
    "response_time_ms": 1250.5,
    "chunk_count": 3
}
```

### GET /api/rag/stream

流式 RAG 问答（SSE）。

参数：`?query=你的问题&top_k=5&threshold=0.5`

**SSE 事件：**
```
data: {"type":"sources","data":[...]}
data: {"type":"text","content":"回"}
data: {"type":"text","content":"答"}
data: {"type":"done","time_ms":1250.5}
```

---

## D-Indexer：D 盘代码索引

### GET /api/d-index/stats

D 盘索引统计。

**响应：**
```json
{
    "available": true,
    "chunks": 28450,
    "projects": [
        {"project": "jobfirst-claw", "files": 320, "chunks": 4800, "file_types": [".rs", ".toml"]}
    ],
    "collection": "d_drive_index",
    "project_roots": 22,
    "scheduler_running": true,
    "last_scan": "2026-06-09T03:00:00"
}
```

### GET /api/d-index/projects

已索引项目列表。

### POST /api/d-index/search

D 盘代码语义搜索。

**请求体：**
```json
{
    "query": "用户认证逻辑在哪里实现",
    "top_k": 10,
    "project_filter": "jobfirst-claw",
    "file_type_filter": "rs"
}
```

> `project_filter` 和 `file_type_filter` 为可选参数。

**响应：**
```json
{
    "results": [
        {
            "chunk_id": "abc123_chunk_0",
            "file_path": "D:/jobfirst-claw/src/auth.rs",
            "project_name": "jobfirst-claw",
            "content": "pub fn authenticate...",
            "file_type": "rs",
            "similarity": 0.92,
            "last_modified": "2026-06-08 15:30"
        }
    ],
    "total": 5
}
```

### POST /api/d-index/scan

手动触发 D 盘扫描。

**请求体：**
```json
{
    "mode": "resume"
}
```

mode 可选值：

| 值 | 说明 |
|----|------|
| `resume` | 断点续传：从中断处继续未完成的扫描（推荐首次使用） |
| `incremental` | 增量扫描：仅索引变更文件，文件缓存加速（日常使用） |
| `full` | 全量扫描：重置所有断点，从头开始（慎用，耗时数小时） |

**响应：**
```json
{
    "mode": "resume",
    "total_files": 12500,
    "new_chunks": 480,
    "skipped_chunks": 0,
    "skipped_files": 12020,
    "duration_seconds": 45.3,
    "timestamp": "2026-06-09T22:30:00"
}
```

---

## D-Indexer：断点管理

### GET /api/d-index/checkpoint

获取所有项目的扫描断点/进度。

**响应：**
```json
{
    "projects": [
        {
            "project_root": "D:/jobfirst-claw",
            "status": "in_progress",
            "completed_dirs_count": 45,
            "current_dir": "D:/jobfirst-claw/src/handlers",
            "current_file": "D:/jobfirst-claw/src/handlers/user.rs",
            "files_scanned": 320,
            "files_indexed": 280,
            "chunks_indexed": 4350,
            "started_at": "2026-06-09T03:00:00",
            "updated_at": "2026-06-09T05:30:00"
        },
        {
            "project_root": "D:/SmartJobs",
            "status": "completed",
            "completed_dirs_count": 120,
            "files_scanned": 850,
            "files_indexed": 780,
            "chunks_indexed": 12000
        }
    ],
    "has_incomplete": true,
    "cache": {
        "total_cached_files": 15230,
        "by_project": [
            {"project": "jobfirst-claw", "files": 320},
            {"project": "SmartJobs", "files": 850}
        ]
    }
}
```

### POST /api/d-index/checkpoint/reset

重置断点。

**请求体（重置单个项目）：**
```json
{
    "project_root": "D:/jobfirst-claw"
}
```

**请求体（重置所有项目）：**
```json
{}
```

### DELETE /api/d-index/checkpoint

删除项目的文件索引缓存（强制重新索引）。

**请求体：**
```json
{
    "project_root": "D:/jobfirst-claw"
}
```

---

## 报告

### POST /api/reports/generate

生成报告。

**请求体：**
```json
{
    "type": "daily"
}
```

`type` 可选：daily / weekly / monthly

### GET /api/reports/queries

获取查询历史。

参数：`?limit=50`

---

## 系统

### GET /api/system/check

系统健康检查。

**响应：**
```json
{
    "status": "ok",
    "ai_provider": "deepseek",
    "chroma_available": true,
    "db_path": "E:\\szpeter2026\\db\\szpeter2026.db"
}
```
