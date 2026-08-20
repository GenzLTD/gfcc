# 文档加载与筛选功能指南

## 📌 不需要你实现筛选!

系统已经**自动支持**文档筛选和处理了!你只需要把文档放到目录下,系统会自动:

1. ✅ **识别支持的格式** - 自动识别 `.txt`, `.md` 等格式
2. ✅ **跳过不支持的格式** - 自动跳过 `.pdf`, `.docx` 等
3. ✅ **提取元数据** - 从文件路径和名称自动提取分类信息
4. ✅ **批量处理** - 一次性处理整个目录
5. ✅ **分块存储** - 自动将文档分块并向量化

---

## 🎯 工作原理

### 自动文件筛选流程

```
 documents/ 目录
    ↓
 遍历所有文件
    ↓
 检查文件扩展名
    ↓
    ├─ .txt → 处理 ✓
    ├─ .md → 处理 ✓
    ├─ .pdf → 跳过 ✗ (不支持)
    ├─ .docx → 跳过 ✗ (不支持)
    └─ 其他 → 跳过 ✗ (未知格式)
    ↓
 处理支持的文件
    ↓
 分块 + 向量化
    ↓
 存入知识库
```

### 支持的文件格式

✅ **支持的格式**:
- `.txt` - 纯文本文件
- `.md` - Markdown 文件
- `.markdown` - Markdown 文件 (别名)

❌ **不支持的格式** (自动跳过):
- `.pdf` - PDF 文档
- `.doc`, `.docx` - Word 文档
- `.xls`, `.xlsx` - Excel 文件
- `.ppt`, `.pptx` - PowerPoint 文件
- `.jpg`, `.png`, `.gif` - 图片文件
- `.zip`, `.rar` - 压缩文件

---

## 🚀 使用方法

### 方法 1: 批量加载整个目录 (推荐)

```bash
# 使用新的批量加载 API
./upload-docs.sh ./documents

# 或者指定其他目录
./upload-docs.sh /path/to/your/docs
```

**特点**:
- ✅ 自动扫描目录
- ✅ 自动筛选文件
- ✅ 自动提取元数据
- ✅ 显示详细统计
- ✅ 报告错误信息

### 方法 2: API 调用

#### 2.1 扫描目录 (查看有哪些文件)

```bash
curl "http://localhost:8080/api/documents/load/scan?directory=./documents"
```

**响应示例**:
```json
{
  "exists": true,
  "path": "./documents",
  "files": [
    {
      "name": "spring-boot.md",
      "path": "/path/to/documents/spring-boot.md",
      "size": 2048,
      "extension": ".md",
      "supported": true
    },
    {
      "name": "manual.pdf",
      "path": "/path/to/documents/manual.pdf",
      "size": 1024000,
      "extension": ".pdf",
      "supported": false
    }
  ],
  "totalCount": 2,
  "supportedCount": 1
}
```

#### 2.2 批量加载目录

```bash
curl -X POST http://localhost:8080/api/documents/load/directory \
  -H "Content-Type: application/json" \
  -d '{
    "directory": "./documents",
    "metadata": {
      "source": "batch-upload",
      "project": "my-knowledge-base"
    }
  }'
```

**响应示例**:
```json
{
  "success": true,
  "successCount": 5,
  "skippedCount": 3,
  "errors": [],
  "message": null
}
```

#### 2.3 查看支持的格式

```bash
curl http://localhost:8080/api/documents/load/supported-formats
```

**响应示例**:
```json
{
  "supported": [".txt", ".md", ".markdown"],
  "unsupported": [".pdf", ".doc", ".docx", ".jpg", ".png"]
}
```

#### 2.4 上传单个文件

```bash
curl -X POST http://localhost:8080/api/documents/load/file \
  -F "file=@document.md" \
  -F "category=技术" \
  -F "topic=Spring Boot"
```

---

## 📁 目录结构与元数据

### 推荐的目录结构

```
documents/
├── technical/              # 技术文档 (自动作为 category)
│   ├── spring/            # Spring 相关 (自动作为 sub_category)
│   │   ├── spring-boot.md
│   │   └── spring-mvc.md
│   ├── database/
│   │   └── mysql-guide.md
│   └── ai/
│       └── rag-intro.md
├── business/              # 业务文档
│   ├── policies/
│   └── procedures/
└── knowledge/             # 知识库
    └── faq/
```

### 自动提取的元数据

系统会自动从文件路径和名称提取以下元数据:

```json
{
  "category": "technical",          // 从第一级目录提取
  "sub_category": "spring",        // 从第二级目录提取
  "topic": "spring-boot",          // 从文件名提取
  "filename": "spring-boot.md",    // 文件名
  "file_path": "/path/to/file",    // 完整路径
  "file_size": 2048,               // 文件大小
  "extension": ".md",              // 文件扩展名
  "last_modified": "2024-01-01",   // 最后修改时间
  "source": "batch-upload",        // 上传来源
  "upload_time": "2024-01-01"      // 上传时间
}
```

**示例**:
- 文件: `documents/technical/spring/spring-boot.md`
- 自动提取的元数据:
  - `category`: `technical`
  - `sub_category`: `spring`
  - `topic`: `spring-boot`

---

## 🔍 查询时使用元数据筛选

### 1. 按分类查询

```bash
# 查询技术文档
curl -X POST http://localhost:8080/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何配置数据库连接池?",
    "topK": 5,
    "similarityThreshold": 0.7
  }'

# 系统会自动从技术分类中查找相关文档
```

### 2. 相似度搜索

```bash
# 搜索包含 "Spring Boot" 的文档块
curl -X POST http://localhost:8080/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Spring Boot 自动配置",
    "topK": 10,
    "similarityThreshold": 0.6
  }'
```

---

## 📊 脚本输出示例

运行 `./upload-docs.sh` 的输出:

```
========================================
  本地知识库语料批量上传脚本
========================================

文档目录: ./documents
API 地址: http://localhost:8080

1. 扫描目录...
   ✓ 目录存在: ./documents

文件统计:
   总文件数: 15
   支持的文件: 12
   不支持的文件: 3

支持的文件格式:
   - .txt
   - .md
   - .markdown

是否继续上传? (y/n) y

2. 开始批量加载...

3. 加载结果:
   成功: 12 个文件
   跳过: 3 个文件
   失败: 0 个文件
   耗时: 8s

4. 测试查询...

测试搜索功能:
   找到相关文档: 5 个

测试 RAG 问答:
   ✓ 这个知识库包含 Spring Boot、MySQL、RAG 等技术文档...

========================================
✓ 完成! 知识库已就绪。
========================================
```

---

## 🎓 完整使用流程

### 1. 准备文档

```bash
# 创建目录
mkdir -p documents/technical/spring
mkdir -p documents/technical/database
mkdir -p documents/knowledge/faq

# 放置文档 (支持 .txt 和 .md)
cp your-docs/*.md documents/technical/spring/
cp your-docs/*.txt documents/knowledge/faq/

# 也可以包含其他格式 (会自动跳过)
cp your-docs/manual.pdf documents/  # 会被跳过
```

### 2. 扫描目录

```bash
# 查看有哪些文件
curl "http://localhost:8080/api/documents/load/scan?directory=./documents" | jq
```

### 3. 批量加载

```bash
# 一键批量上传
./upload-docs.sh
```

### 4. 测试查询

```bash
# 测试搜索
curl -X POST http://localhost:8080/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Spring Boot", "topK": 5}'

# 测试问答
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "什么是 Spring Boot?"}'
```

---

## 💡 最佳实践

### 1. 文档组织

✅ **推荐**:
```
documents/
├── by-category/     # 按业务领域分类
├── by-type/         # 按文档类型分类
└── by-topic/        # 按技术主题分类
```

❌ **避免**:
```
documents/
├── 文档1.txt
├── 文档2.txt
├── doc3.txt
└── 文档4.txt
```

### 2. 文件命名

✅ **推荐**:
- `spring-boot-quickstart.md`
- `mysql-optimization-guide.md`
- `rag-best-practices.md`

❌ **避免**:
- `doc1.txt`
- `20240101.md`
- `文档.md`

### 3. 文档内容

✅ **推荐**:
- 结构清晰的 Markdown
- 适当使用标题和分段
- 避免过长的单个文档 (建议 < 100KB)

❌ **避免**:
- 纯代码文件
- 二进制文件
- 重复内容

---

## 🔧 高级功能

### 1. 自定义元数据

批量加载时可以添加自定义元数据:

```bash
curl -X POST http://localhost:8080/api/documents/load/directory \
  -H "Content-Type: application/json" \
  -d '{
    "directory": "./documents",
    "metadata": {
      "source": "company-knowledge-base",
      "department": "IT",
      "version": "2.0",
      "language": "zh-CN",
      "maintainer": "张三"
    }
  }'
```

### 2. 增量更新

只上传新增或修改的文件:

```bash
# 1. 先扫描目录
curl "http://localhost:8080/api/documents/load/scan?directory=./documents" > scan-result.json

# 2. 查看文件列表
cat scan-result.json | jq '.files'

# 3. 只上传需要的文件
curl -X POST http://localhost:8080/api/documents/load/file \
  -F "file=@new-doc.md"
```

### 3. 错误处理

查看加载失败的文件:

```bash
# 批量加载后会返回错误列表
curl -X POST http://localhost:8080/api/documents/load/directory \
  -H "Content-Type: application/json" \
  -d '{"directory": "./documents"}' | jq '.errors'
```

---

## ❓ 常见问题

### Q1: 为什么某些文件被跳过?

**A**: 系统只支持 `.txt` 和 `.md` 格式。其他格式 (如 `.pdf`, `.docx`) 会自动跳过。

查看支持的格式:
```bash
curl http://localhost:8080/api/documents/load/supported-formats
```

### Q2: 如何查看哪些文件被支持/不支持?

**A**: 使用扫描 API:

```bash
curl "http://localhost:8080/api/documents/load/scan?directory=./documents" | jq
```

会显示每个文件是否被支持。

### Q3: 文件被跳过后如何处理?

**A**:
1. 转换格式: 使用工具将 PDF/Word 转换为 Markdown
2. 提取文本: 使用 `pdftotext` 等工具提取文本
3. 重新上传: 转换后重新运行上传脚本

### Q4: 如何更新已有文档?

**A**:
1. 修改源文件
2. 重新运行批量加载
3. 或者删除旧文档 (需要文档 ID) 后重新上传

### Q5: 支持中文文档吗?

**A**: ✅ 完全支持中文文档!系统使用的是通用的文本处理方式,支持所有语言的文本。

---

## 📝 总结

### 核心要点

1. **无需实现筛选** - 系统自动识别和筛选文件
2. **支持格式有限** - 目前只支持 `.txt` 和 `.md`
3. **自动提取元数据** - 从路径和文件名自动提取
4. **批量处理** - 一次处理整个目录
5. **错误报告** - 详细显示加载失败的文件

### 快速开始

```bash
# 1. 准备文档 (只放 .txt 和 .md)
mkdir -p documents/technical
cp your-docs/*.md documents/technical/

# 2. 批量上传 (自动筛选)
./upload-docs.sh

# 3. 测试查询
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "你的问题"}'
```

**就是这么简单!系统会自动处理所有细节。** 🎉
