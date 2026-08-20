# 快速参考 - 文档筛选与加载

## 🎯 一句话说明

**不需要实现筛选!系统自动识别和处理 `.txt` 和 `.md` 文件,自动跳过其他格式。**

---

## 📝 快速开始

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

---

## ✅ 支持的文件格式

| 格式 | 说明 | 处理方式 |
|------|------|----------|
| `.txt` | 纯文本 | ✅ 自动处理 |
| `.md` | Markdown | ✅ 自动处理 |
| `.markdown` | Markdown | ✅ 自动处理 |
| `.pdf` | PDF 文档 | ❌ 自动跳过 |
| `.docx` | Word 文档 | ❌ 自动跳过 |
| 其他格式 | - | ❌ 自动跳过 |

---

## 🚀 常用命令

### 查看支持的格式
```bash
curl http://localhost:8080/api/documents/load/supported-formats
```

### 扫描目录
```bash
curl "http://localhost:8080/api/documents/load/scan?directory=./documents" | jq
```

### 批量加载
```bash
./upload-docs.sh
```

### 上传单个文件
```bash
curl -X POST http://localhost:8080/api/documents/load/file \
  -F "file=@document.md" \
  -F "category=技术"
```

---

## 📁 推荐目录结构

```
documents/
├── technical/           # 技术文档
│   ├── spring/
│   ├── database/
│   └── ai/
├── business/            # 业务文档
│   ├── policies/
│   └── procedures/
└── knowledge/           # 知识库
    └── faq/
```

---

## 🔍 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/documents/load/directory` | POST | 批量加载目录 |
| `/api/documents/load/scan` | GET | 扫描目录 |
| `/api/documents/load/supported-formats` | GET | 查看支持的格式 |
| `/api/documents/load/file` | POST | 上传单个文件 |

---

## 📊 脚本输出示例

```
========================================
  本地知识库语料批量上传脚本
========================================

文档目录: ./documents

1. 扫描目录...
   ✓ 目录存在

文件统计:
   总文件数: 15
   支持的文件: 12
   不支持的文件: 3

2. 开始批量加载...

3. 加载结果:
   成功: 12 个文件
   跳过: 3 个文件
   耗时: 8s

4. 测试查询...
   ✓ 测试通过

========================================
✓ 完成! 知识库已就绪。
========================================
```

---

## 💡 提示

1. **只需要 `.txt` 和 `.md` 文件** - 其他格式会被自动跳过
2. **目录结构很重要** - 系统会从路径自动提取分类信息
3. **文件名要清晰** - 使用有意义的文件名
4. **定期测试查询** - 上传后测试查询效果
5. **更新文档** - 修改后重新运行上传脚本

---

## 📚 详细文档

- `ANSWER.md` - 关于文档筛选的详细回答
- `DOCUMENT_LOADER_GUIDE.md` - 完整使用指南
- `WORKFLOW.md` - 工作流程说明
- `QUICK_START.md` - 快速开始指南

---

**就是这么简单!系统会自动处理所有细节。** 🎉
