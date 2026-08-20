# 关于文档筛选功能的回答

## ❓ 你的问题

"需要获取的文档需要我实现筛选出来,比如说 md 文档?"

## ✅ 简短回答

**不需要!** 系统已经完全自动支持文档筛选了!

---

## 🎯 核心说明

### 1. 系统已自动实现筛选功能

你**不需要**自己编写任何代码来筛选文档。系统已经内置了完整的文档筛选和处理功能:

✅ **自动识别格式** - 自动识别 `.txt`, `.md` 等格式
✅ **自动跳过不支持的格式** - 自动跳过 `.pdf`, `.docx` 等
✅ **批量处理** - 一次处理整个目录
✅ **详细报告** - 显示处理结果和错误信息

### 2. 你只需要做一件事

**把文档放到目录下,然后运行上传脚本!**

```bash
# 1. 把你的文档放到 documents/ 目录
#    支持的格式: .txt, .md
#    不支持的格式会被自动跳过

# 2. 运行上传脚本 (自动筛选和处理)
./upload-docs.sh

# 完成!系统会自动:
# - 筛选支持的文件
# - 跳过不支持的文件
# - 分块并向量化
# - 存入知识库
```

---

## 🚀 实际操作示例

### 场景 1: 你有各种格式的文档

假设你的 `documents/` 目录包含:

```
documents/
├── technical/
│   ├── spring-boot.md      ← 支持,会处理
│   ├── mysql-guide.txt     ← 支持,会处理
│   ├── manual.pdf          ← 不支持,自动跳过
│   └── slides.pptx         ← 不支持,自动跳过
├── business/
│   ├── policies.md         ← 支持,会处理
│   ├── contract.docx       ← 不支持,自动跳过
│   └── report.pdf          ← 不支持,自动跳过
└── other/
    └── random.jpg          ← 不支持,自动跳过
```

**运行 `./upload-docs.sh` 后**:

```
文件统计:
   总文件数: 7
   支持的文件: 3 (spring-boot.md, mysql-guide.txt, policies.md)
   不支持的文件: 4 (自动跳过)

加载结果:
   成功: 3 个文件
   跳过: 4 个文件
```

**系统自动处理了支持的文件,跳过了不支持的文件!**

---

## 📋 支持和不支持的格式

### ✅ 支持的格式 (会被处理)

- `.txt` - 纯文本文件
- `.md` - Markdown 文件
- `.markdown` - Markdown 文件 (别名)

### ❌ 不支持的格式 (自动跳过)

- `.pdf` - PDF 文档
- `.doc`, `.docx` - Word 文档
- `.xls`, `.xlsx` - Excel 文档
- `.ppt`, `.pptx` - PowerPoint 文档
- `.jpg`, `.png`, `.gif` - 图片文件
- `.zip`, `.rar` - 压缩文件

---

## 🔍 如何查看支持的格式

### 方法 1: API 查询

```bash
curl http://localhost:8080/api/documents/load/supported-formats
```

**响应**:
```json
{
  "supported": [".txt", ".md", ".markdown"],
  "unsupported": [".pdf", ".doc", ".docx", ".jpg", ".png"]
}
```

### 方法 2: 扫描目录

```bash
curl "http://localhost:8080/api/documents/load/scan?directory=./documents" | jq
```

**会显示每个文件是否被支持**:
```json
{
  "files": [
    {
      "name": "spring-boot.md",
      "extension": ".md",
      "supported": true    ← 这个会被处理
    },
    {
      "name": "manual.pdf",
      "extension": ".pdf",
      "supported": false   ← 这个会被跳过
    }
  ]
}
```

---

## 💡 完整使用流程

### 1. 准备文档

```bash
# 创建目录
mkdir -p documents/technical/spring
mkdir -p documents/knowledge/faq

# 放置文档 (支持 .txt 和 .md)
cp your-docs/*.md documents/technical/spring/
cp your-docs/*.txt documents/knowledge/faq/

# 也可以包含其他格式 (会自动跳过)
cp your-docs/manual.pdf documents/    # 会被跳过,不影响
```

### 2. 批量上传 (自动筛选)

```bash
# 一键批量上传 (自动筛选支持的文件)
./upload-docs.sh
```

**脚本会自动**:
- ✅ 扫描目录
- ✅ 识别支持的格式 (`.txt`, `.md`)
- ✅ 跳过不支持的格式 (`.pdf`, `.docx` 等)
- ✅ 显示详细的处理报告
- ✅ 报告错误信息

### 3. 测试查询

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

## 🎓 技术实现细节

### 新增的服务和控制器

我为你添加了以下功能:

1. **DocumentLoaderService** - 文档加载服务
   - 自动识别和筛选文件格式
   - 批量处理整个目录
   - 自动提取元数据

2. **DocumentLoadController** - 文档加载控制器
   - `/api/documents/load/directory` - 批量加载目录
   - `/api/documents/load/scan` - 扫描目录
   - `/api/documents/load/supported-formats` - 查看支持的格式
   - `/api/documents/load/file` - 上传单个文件

3. **更新的上传脚本** (`upload-docs.sh`)
   - 使用新的批量加载 API
   - 显示详细的统计信息
   - 自动测试查询功能

### 文件列表

```
src/main/java/com/knowledgebase/
├── service/
│   └── DocumentLoaderService.java       ← 新增:文档加载服务
├── controller/
│   └── DocumentLoadController.java     ← 新增:文档加载控制器
└── ...

项目根目录:
├── upload-docs.sh                       ← 更新:批量上传脚本
├── test-loader.sh                       ← 新增:测试脚本
├── DOCUMENT_LOADER_GUIDE.md             ← 新增:详细指南
└── ANSWER.md                           ← 本文件
```

---

## 📚 相关文档

我为你创建了详细的文档:

1. **DOCUMENT_LOADER_GUIDE.md** - 文档加载功能完整指南
   - 详细的工作原理
   - API 使用说明
   - 最佳实践
   - 常见问题

2. **KNOWLEDGE_BASE_GUIDE.md** - 知识库运作机制
   - RAG 原理
   - 语料组织方法
   - 检索优化技巧

3. **WORKFLOW.md** - 完整工作流程
   - 快速开始
   - 实际操作指南
   - 使用场景举例

---

## 🎯 总结

### 你需要做什么

1. ✅ 准备文档 (`.txt` 或 `.md` 格式)
2. ✅ 放到 `documents/` 目录
3. ✅ 运行 `./upload-docs.sh`
4. ✅ 完成!

### 系统会自动做什么

1. ✅ 筛选支持的格式 (`.txt`, `.md`)
2. ✅ 跳过不支持的格式 (`.pdf`, `.docx` 等)
3. ✅ 分块文档
4. ✅ 向量化处理
5. ✅ 存入知识库
6. ✅ 报告处理结果

---

## ❓ 仍需要帮助?

查看这些文档:

- `DOCUMENT_LOADER_GUIDE.md` - 了解详细的加载功能
- `WORKFLOW.md` - 了解完整的工作流程
- `QUICK_START.md` - 快速启动指南
- `api-example.http` - API 使用示例

**不需要实现任何筛选代码,系统已经完全自动化了!** 🎉
