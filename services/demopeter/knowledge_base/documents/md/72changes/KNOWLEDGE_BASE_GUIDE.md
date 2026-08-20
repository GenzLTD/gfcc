# 本地知识库运作机制与语料组织指南

## 一、知识库运作原理

### 1.1 核心流程 (RAG 模式)

```
用户提问
    ↓
[1] 向量嵌入 - 将问题转换为向量
    ↓
[2] 相似度搜索 - 在向量数据库中搜索相关文档块
    ↓
[3] 上下文构建 - 将搜索到的文档块组织成上下文
    ↓
[4] LLM 推理 - 将问题 + 上下文发送给大语言模型
    ↓
[5] 返回答案 - 基于上下文生成准确答案
```

### 1.2 技术架构

```
┌─────────────┐
│   用户问题   │
└──────┬──────┘
       │
       ↓
┌─────────────────────────────────────┐
│  RAG Service (查询处理)             │
│  1. 接收用户问题                    │
│  2. 调用向量搜索                    │
│  3. 构建提示词                      │
│  4. 调用 LLM                        │
└──────┬──────────────────┬──────────┘
       │                  │
       ↓                  ↓
┌──────────────┐   ┌──────────────┐
│ 向量搜索     │   │  ChatClient  │
│ (Chroma)    │   │  (DeepSeek等) │
└──────┬───────┘   └──────┬───────┘
       │                  │
       └────────┬─────────┘
                ↓
        ┌───────────────┐
        │  向量数据库     │
        │  (Chroma)     │
        └───────────────┘
```

## 二、语料组织与管理

### 2.1 语料处理流程

```
原始文档 (TXT/MD)
       ↓
[1] 文档读取 - TextReader 读取文本内容
       ↓
[2] 添加元数据 - 为文档添加分类、来源等信息
       ↓
[3] 文本分块 - TokenTextSplitter 将文档分成小块
       ↓
[4] 向量嵌入 - 将文本块转换为向量
       ↓
[5] 向量存储 - 存储到 Chroma 向量数据库
```

### 2.2 分块策略

**当前配置** (`application.yml`):
```yaml
app:
  documents:
    chunk-size: 1000      # 每块 1000 tokens
    chunk-overlap: 200    # 块之间重叠 200 tokens
```

**为什么需要分块?**
- LLM 有上下文长度限制
- 提高检索精度
- 加快处理速度

**分块示例**:
```
原始文档 (3000 tokens):
┌─────────────────────────────────────────┐
│  第一章 Spring Boot 简介 (1000)         │
│  第二章 自动配置原理 (1000)             │
│  第三章 嵌入式服务器 (1000)             │
└─────────────────────────────────────────┘
           ↓ 分块后 (1000 + 200 overlap)
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ 块1: 第一章    │ │ 块2: 第一章末   │ │ 块3: 第二章    │
│   + 第二章开始  │ │   + 第二章部分  │ │   + 第三章部分  │
└────────────────┘ └────────────────┘ └────────────────┘
```

## 三、语料组织最佳实践

### 3.1 文档分类与元数据

使用元数据来组织语料,提高检索精度:

```json
{
  "content": "文档内容...",
  "metadata": {
    "category": "技术文档",      // 分类
    "topic": "Spring Boot",     // 主题
    "author": "张三",            // 作者
    "filename": "spring-boot.md", // 文件名
    "source": "./documents/",   // 来源路径
    "language": "zh-CN",        // 语言
    "version": "1.0",           // 版本
    "date": "2024-01-01"        // 日期
  }
}
```

### 3.2 推荐的目录结构

```
knowledge-base/
├── documents/                      # 语料存储目录
│   ├── technical/                  # 技术文档
│   │   ├── spring/
│   │   │   ├── spring-boot.md
│   │   │   ├── spring-mvc.md
│   │   │   └── spring-data.md
│   │   ├── ai/
│   │   │   ├── rag-intro.md
│   │   │   └── vector-databases.md
│   │   └── databases/
│   │       ├── mysql-guide.md
│   │       └── postgresql.md
│   ├── business/                   # 业务文档
│   │   ├── policies/
│   │   ├── procedures/
│   │   └── meetings/
│   └── knowledge/                  # 知识库
│       ├── qa/
│       └── tutorials/
└── src/main/resources/documents/  # 初始文档
    └── example.txt
```

### 3.3 文档命名规范

建议使用清晰的命名方式:

```
✅ 好的命名:
- spring-boot-quickstart.md
- mysql-performance-optimization.md
- rag-best-practices-2024.md

❌ 不好的命名:
- doc1.txt
- 20240101.md
- 文档.txt
```

## 四、语料上传方法

### 4.1 方法 1: API 上传文本

```bash
curl -X POST http://localhost:8080/api/documents/text \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Spring Boot 是基于 Spring 框架的开发框架...",
    "metadata": {
      "category": "技术",
      "topic": "Spring Boot",
      "author": "AI Assistant"
    }
  }'
```

### 4.2 方法 2: API 上传文件

```bash
# 上传单个文件
curl -X POST http://localhost:8080/api/documents/text-file \
  -F "file=@spring-boot.md" \
  -F "category=技术" \
  -F "topic=Spring"

# 批量上传脚本
for file in documents/*.md; do
  curl -X POST http://localhost:8080/api/documents/text-file \
    -F "file=@$file" \
    -F "category=技术文档"
done
```

### 4.3 方法 3: 初始文档加载

将文档放在 `src/main/resources/documents/` 目录,应用启动时自动加载:

```
src/main/resources/documents/
├── welcome.txt          # 欢迎文档
├── tech-faq.txt         # 技术问答
└── company-info.txt     # 公司信息
```

## 五、语料质量要求

### 5.1 内容质量

✅ **推荐**:
- 结构清晰的文档
- 适当使用标题和分段
- 避免过短的段落 (至少 50 字)
- 避免过长的段落 (建议 < 500 字)
- 使用标准标点符号

❌ **避免**:
- 纯代码或数据文件
- 二进制文件 (PDF、Word 等暂不支持)
- 重复内容
- 过时信息

### 5.2 文档格式

**Markdown 格式 (推荐)**:
```markdown
# Spring Boot 简介

## 什么是 Spring Boot?

Spring Boot 是基于 Spring 框架的开发框架...

## 核心特性

1. 自动配置
2. 嵌入式服务器
3. 生产就绪
```

**纯文本格式**:
```
Spring Boot 简介
================

什么是 Spring Boot?
Spring Boot 是基于 Spring 框架的开发框架...

核心特性:
1. 自动配置
2. 嵌入式服务器
3. 生产就绪
```

## 六、检索优化技巧

### 6.1 添加相关元数据

```json
{
  "content": "...",
  "metadata": {
    "category": "技术文档",
    "topic": "Spring Boot",
    "tags": ["后端", "Java", "Web"],
    "difficulty": "中级",
    "version": "3.0"
  }
}
```

### 6.2 使用关键词

在文档开头添加关键词摘要:

```markdown
# Spring Boot 教程

**关键词**: Spring Boot, 自动配置, 嵌入式服务器, REST API

本文介绍如何使用 Spring Boot 快速开发 Web 应用...
```

### 6.3 保持内容更新

定期更新语料:
- 删除过时内容
- 添加新版本信息
- 修正错误内容

## 七、示例: 构建技术文档知识库

### 7.1 准备语料

```bash
# 1. 创建目录
mkdir -p documents/technical/spring
mkdir -p documents/technical/ai
mkdir -p documents/technical/database

# 2. 准备文档
# documents/technical/spring/spring-boot.md
# documents/technical/spring/spring-mvc.md
# documents/technical/ai/rag-intro.md
# documents/technical/database/mysql-guide.md
```

### 7.2 批量上传

```bash
#!/bin/bash
# upload-docs.sh

for category in technical business knowledge; do
  for file in documents/$category/*.md; do
    if [ -f "$file" ]; then
      topic=$(basename "$file" .md)
      echo "上传: $file ($category, $topic)"
      curl -X POST http://localhost:8080/api/documents/text-file \
        -F "file=@$file" \
        -F "category=$category" \
        -F "topic=$topic"
      sleep 1
    fi
  done
done
```

### 7.3 测试查询

```bash
# 测试技术文档查询
curl -X POST http://localhost:8080/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何使用 Spring Boot 创建 REST API?",
    "topK": 5,
    "similarityThreshold": 0.7
  }'

# 测试 AI 概念查询
curl -X POST http://localhost:8080/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "什么是 RAG 技术?",
    "topK": 3,
    "similarityThreshold": 0.6
  }'
```

## 八、监控与维护

### 8.1 查看文档数量

```bash
# 通过 API 查询
curl -X POST http://localhost:8080/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Spring Boot",
    "topK": 100,
    "similarityThreshold": 0.0
  }' | jq '. | length'
```

### 8.2 测试检索质量

定期测试查询结果质量:

```bash
# 测试常见问题
queries=(
  "Spring Boot 的核心特性"
  "如何配置数据库"
  "什么是 RAG"
)

for query in "${queries[@]}"; do
  echo "测试: $query"
  curl -X POST http://localhost:8080/api/rag/query/simple \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$query\"}"
  echo -e "\n---\n"
done
```

### 8.3 优化分块参数

根据实际效果调整分块参数:

```yaml
app:
  documents:
    chunk-size: 500        # 更小的块,更精确
    chunk-overlap: 100    # 减少重叠
```

## 九、常见问题

### Q1: 搜索结果不准确?

**解决方案**:
1. 检查文档质量和相关性
2. 调整 `similarityThreshold` (降低阈值)
3. 增加 `topK` 数量
4. 优化文档中的关键词

### Q2: 如何更新已有文档?

**解决方案**:
```bash
# 1. 删除旧文档 (需要文档 ID)
curl -X DELETE http://localhost:8080/api/documents \
  -H "Content-Type: application/json" \
  -d '["doc-id-1", "doc-id-2"]'

# 2. 重新上传新版本
curl -X POST http://localhost:8080/api/documents/text-file \
  -F "file=@updated-doc.md" \
  -F "category=技术"
```

### Q3: 如何批量导入大量文档?

**解决方案**:
使用脚本批量上传 (参考上面的 `upload-docs.sh`)

## 十、总结

### 核心要点

1. **分块是关键**: 合理的分块大小和重叠
2. **元数据重要**: 用好分类、主题等元数据
3. **质量优先**: 高质量的语料比数量更重要
4. **持续更新**: 定期维护和更新知识库
5. **测试验证**: 定期测试检索质量

### 下一步

1. 根据实际需求调整分块参数
2. 建立文档命名规范
3. 创建自动化上传脚本
4. 建立知识库维护流程
5. 集成前端界面供用户查询

---

**更多帮助**:
- 查看 QUICK_START.md 了解快速启动
- 查看 README.md 了解完整文档
- 查看 api-example.http 了解 API 使用
