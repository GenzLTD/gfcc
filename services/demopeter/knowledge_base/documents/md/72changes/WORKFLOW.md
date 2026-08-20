# 本地知识库 - 语料组织与使用工作流

## 📖 快速理解

这个本地知识库是如何工作的?简单来说:

```
你的文档 → 分块 → 向量化 → 存入数据库
   ↓
用户提问 → 向量搜索 → 找到相关文档块 → 给 AI → 生成答案
```

## 🎯 一句话总结

**把你的文档喂给系统,系统会记住它们,然后用户提问时,系统会从这些文档中找到相关内容来回答问题。**

---

## 📚 详细运作流程

### 第一步: 准备语料 (你的文档)

你需要准备以下类型的文档:

**支持的格式**:
- ✅ `.txt` - 纯文本文件
- ✅ `.md` - Markdown 文件
- ❌ `.pdf` - 暂不支持 (计划支持)

**文档示例**:
```
documents/
├── technical/          # 技术文档
│   ├── spring-boot.md
│   ├── mysql-guide.md
│   └── rag-intro.md
├── business/           # 业务文档
│   ├── policies.md
│   └── procedures.md
└── knowledge/          # 知识库
    └── faq.md
```

### 第二步: 上传文档到知识库

**方法 1: 单个文件上传**
```bash
curl -X POST http://localhost:8080/api/documents/text-file \
  -F "file=@spring-boot.md" \
  -F "category=技术" \
  -F "topic=Spring Boot"
```

**方法 2: 批量上传 (推荐)**
```bash
# 1. 先创建示例文档
./CREATE_SAMPLE_DOCS.sh

# 2. 批量上传
./upload-docs.sh
```

### 第三步: 系统自动处理文档

上传文档后,系统会自动:

1. **读取文件内容** - 读取文本
2. **添加元数据** - 记录分类、主题、来源等
3. **分块处理** - 把长文档切成小块 (每块 1000 tokens,重叠 200 tokens)
4. **向量化** - 把每个文本块转换成向量 (数字数组)
5. **存储** - 存入 Chroma 向量数据库

**示例**: 一篇 3000 字的文档会被切成 3-4 个块,每个块都被向量化存储。

### 第四步: 用户提问

当用户提问时:

```bash
curl -X POST http://localhost:8080/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Spring Boot 有什么特点?",
    "topK": 5,
    "similarityThreshold": 0.7
  }'
```

### 第五步: 系统回答 (RAG 过程)

系统会执行以下步骤:

1. **向量化问题** - 把 "Spring Boot 有什么特点?" 转成向量
2. **相似度搜索** - 在向量数据库中找最相似的 5 个文档块
3. **构建上下文** - 把这 5 个块组合成上下文文本
4. **调用 AI** - 把问题和上下文一起发给大语言模型 (GPT、Ollama 等)
5. **生成答案** - AI 基于上下文回答问题
6. **返回结果** - 返回答案和引用的文档来源

---

## 🗂️ 如何组织你的语料

### 目录结构建议

```
your-knowledge-base/
├── documents/
│   ├── by-topic/          # 按主题分类
│   │   ├── spring/
│   │   ├── database/
│   │   └── ai/
│   ├── by-type/          # 按类型分类
│   │   ├── tutorials/    # 教程
│   │   ├── faq/          # 问答
│   │   └── reference/    # 参考资料
│   └── by-department/    # 按部门分类
│       ├── hr/
│       ├── finance/
│       └── it/
```

### 文档命名规范

**好的命名**:
- `spring-boot-quickstart.md` - 清晰,包含关键词
- `mysql-performance-2024.md` - 包含版本或年份
- `rag-best-practices-guide.md` - 完整描述

**不好的命名**:
- `doc1.txt` - 无法理解内容
- `20240101.md` - 只有日期
- `文档.txt` - 中英文混用

### 元数据使用

上传时可以添加元数据来提高检索精度:

```bash
curl -X POST http://localhost:8080/api/documents/text-file \
  -F "file=@spring-boot.md" \
  -F "category=技术文档" \
  -F "topic=Spring Boot" \
  -F "difficulty=中级" \
  -F "language=zh-CN" \
  -F "version=3.0"
```

---

## 🚀 实际操作指南

### 1. 快速体验 (5 分钟)

```bash
# Step 1: 启动 Chroma
docker-compose up -d chroma

# Step 2: 启动应用
export DEEPSEEK_API_KEY=your-key  # 与 Wukong 一致，或使用本地 Ollama
mvn spring-boot:run

# Step 3: 创建示例文档
./CREATE_SAMPLE_DOCS.sh

# Step 4: 批量上传
./upload-docs.sh

# Step 5: 测试查询
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "什么是 Spring Boot?"}'
```

### 2. 添加自己的文档

```bash
# 创建你的文档目录
mkdir -p documents/my-docs

# 编写文档
cat > documents/my-docs/my-knowledge.md << 'EOF'
# 我的知识

这里写你的内容...

## 重要概念

列出重要概念...

## 常见问题

列出常见问题...
EOF

# 上传文档
curl -X POST http://localhost:8080/api/documents/text-file \
  -F "file=@documents/my-docs/my-knowledge.md" \
  -F "category=我的文档" \
  -F "topic=个人知识"
```

### 3. 批量上传现有文档

```bash
# 假设你有大量 Markdown 文档
# 放到 documents/ 目录下
cp -r ~/my-docs/* documents/

# 批量上传
./upload-docs.sh
```

---

## 📊 语料质量要求

### ✅ 推荐的文档

- **结构清晰** - 有标题、分段
- **内容完整** - 避免断章取义
- **长度适中** - 建议 500-5000 字
- **语言规范** - 使用正确的标点和语法
- **及时更新** - 定期更新过时内容

### ❌ 避免的文档

- **代码文件** - 纯代码不适合作为知识库
- **二进制文件** - PDF、Word 等暂不支持
- **重复内容** - 避免重复上传相同内容
- **过时信息** - 删除或更新过时文档

### 📝 文档格式建议

**Markdown 格式 (推荐)**:
```markdown
# 标题

**关键词**: 关键词1, 关键词2, 关键词3

## 一级标题

段落内容...

### 二级标题

- 列表项 1
- 列表项 2
```

---

## 🔍 检索优化技巧

### 1. 添加关键词

在文档开头添加关键词摘要:

```markdown
# Spring Boot 教程

**关键词**: Spring Boot, 自动配置, 嵌入式服务器, REST API

本文介绍如何使用 Spring Boot 快速开发 Web 应用...
```

### 2. 使用元数据分类

按业务领域分类上传:

```bash
# 技术文档
curl -F "file=@tech.md" -F "category=技术" ...

# 业务文档
curl -F "file=@business.md" -F "category=业务" ...

# 政策文档
curl -F "file=@policy.md" -F "category=政策" ...
```

### 3. 调整搜索参数

根据需要调整:

```json
{
  "query": "问题",
  "topK": 3,                    // 检索 3 个最相关的块
  "similarityThreshold": 0.7    // 相似度阈值 (0-1)
}
```

- **topK 越大**: 召回越多,但可能包含不相关内容
- **threshold 越高**: 结果越精准,但可能遗漏相关内容

---

## 🎓 使用场景举例

### 场景 1: 企业内部知识库

```bash
# 文档组织
documents/
├── hr/           # 人力资源
├── finance/      # 财务
├── it/           # IT 支持
└── sales/        # 销售培训

# 员工查询
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "如何申请年假?"}'
```

### 场景 2: 技术文档查询

```bash
# 文档组织
documents/
├── frameworks/   # 框架文档
├── tools/        # 工具文档
├── tutorials/    # 教程
└── best-practices/ # 最佳实践

# 开发者查询
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "如何优化 MySQL 查询性能?"}'
```

### 场景 3: 客服助手

```bash
# 文档组织
documents/
├── products/     # 产品信息
├── policies/     # 政策说明
├── faq/          # 常见问题
└── solutions/    # 解决方案

# 客服查询
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "退货流程是怎样的?"}'
```

---

## 🔧 高级功能

### 1. 相似度搜索

```bash
# 直接搜索相似文档,不经过 AI
curl -X POST http://localhost:8080/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "搜索关键词",
    "topK": 10,
    "similarityThreshold": 0.5
  }'
```

### 2. 流式响应

```bash
# 流式返回答案 (适用于长答案)
curl -N http://localhost:8080/api/rag/stream?query=你的问题
```

### 3. 自定义提示词

编辑 `src/main/resources/prompts/rag-prompt.st` 来自定义 AI 的回答风格:

```
你是一个专业的 {role}。
请根据以下上下文回答用户的问题。
回答要 {style}。

上下文: {context}
问题: {question}
```

---

## 📈 监控与维护

### 查看文档数量

```bash
# 统计已上传的文档
curl -X POST http://localhost:8080/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{"query": "a", "topK": 1000, "similarityThreshold": 0.0}' | jq '. | length'
```

### 定期测试检索质量

```bash
# 测试常见问题
for question in \
    "Spring Boot 是什么" \
    "什么是 RAG" \
    "如何优化数据库"; do
    echo "测试: $question"
    curl -s -X POST http://localhost:8080/api/rag/query/simple \
        -H "Content-Type: application/json" \
        -d "{\"query\": \"$question\"}" | jq -r '.answer'
    echo "---"
done
```

### 更新文档

```bash
# 删除旧文档 (需要先获取文档 ID)
curl -X DELETE http://localhost:8080/api/documents \
  -H "Content-Type: application/json" \
  -d '["doc-id-1"]'

# 上传新版本
curl -X POST http://localhost:8080/api/documents/text-file \
  -F "file=@updated-doc.md" \
  -F "category=技术"
```

---

## 🎯 总结

### 核心要点

1. **准备文档** - 整理好你的知识文档
2. **批量上传** - 使用脚本批量上传到知识库
3. **系统处理** - 自动分块、向量化、存储
4. **用户提问** - 通过 API 或前端界面查询
5. **智能回答** - RAG 技术生成准确答案

### 快速开始

```bash
# 1. 创建示例文档
./CREATE_SAMPLE_DOCS.sh

# 2. 批量上传
./upload-docs.sh

# 3. 测试查询
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "这个知识库包含哪些内容?"}'
```

### 相关文档

- `QUICK_START.md` - 快速启动指南
- `KNOWLEDGE_BASE_GUIDE.md` - 详细运作机制
- `README.md` - 完整项目文档
- `api-example.http` - API 使用示例

---

**现在就开始创建你的知识库吧!** 🚀
