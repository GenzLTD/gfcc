# 72changes - 本地知识库

> 位于 Wukong 工作区内，与 Wukong 独立发育。职责：需求层——文档需求线索挖掘、成果分享。详见 `../docs/工作区说明.md`。

基于 Spring Boot 和 Spring AI 的本地知识库项目，使用 RAG（检索增强生成）技术实现智能问答。

## 技术栈

- **Spring Boot 3.3.0** - Web 应用框架
- **Spring AI 1.0.0-M5** - AI 集成框架
- **Chroma** - 本地向量数据库
- **Transformers** - 本地嵌入模型 (ONNX)
- **DeepSeek** - 聊天模型（与 Wukong 一致，可替换为 Ollama 等）

## 项目结构

```
src/main/java/com/knowledgebase/
├── KnowledgeBaseApplication.java      # 主应用类
├── config/                             # 配置类
│   ├── AIConfiguration.java          # AI 配置
│   └── VectorStoreConfiguration.java  # 向量存储配置
├── controller/                         # REST API 控制器
│   ├── DocumentController.java       # 文档管理 API
│   └── RAGController.java            # RAG 问答 API
├── model/                              # 数据模型
│   ├── QueryRequest.java
│   └── QueryResponse.java
└── service/                            # 业务服务
    ├── DocumentService.java           # 文档服务
    └── RAGService.java               # RAG 服务

src/main/resources/
├── application.yml                     # 应用配置
├── documents/                         # 初始文档目录
├── models/                            # 模型文件目录
│   ├── all-MiniLM-L6-v2.onnx        # 嵌入模型
│   └── tokenizer.json                # 分词器
└── prompts/                           # 提示词模板
    └── rag-prompt.st
```

## 语料库准备

### 本地语料库

项目已包含完整的本地MD文档语料库:

- **文件总数**: 25,149 个MD文件
- **总大小**: 327MB
- **总字符数**: 约58M字符
- **存储路径**: `./md_documents_collected/`
- **文件权限**: 所有文件具有读权限

### 批量文档加载

系统支持从目录批量加载文档,自动筛选支持的格式:

#### 支持的文件格式
- `.txt` - 纯文本文件
- `.md` / `.markdown` - Markdown 文件

#### 批量加载API

```bash
# 扫描目录
curl -X GET "http://localhost:8080/api/documents/load/scan?directory=./md_documents_collected"

# 批量加载整个目录
curl -X POST http://localhost:8080/api/documents/load/directory \
  -H "Content-Type: application/json" \
  -d '{
    "directory": "./md_documents_collected",
    "metadata": {
      "source": "本地语料库",
      "category": "技术文档"
    }
  }'

# 查看支持的格式
curl -X GET http://localhost:8080/api/documents/load/supported-formats
```

### 自动文档筛选

系统会自动过滤不支持的文件格式,无需手动筛选:

- **自动跳过**: PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, 图片, 压缩包等
- **自动加载**: 只处理 `.txt` 和 `.md` 文件
- **元数据提取**: 自动从文件名和路径提取分类信息

## 快速开始

### 1. 环境要求

- Java 17+
- Maven 3.8+
- Docker (用于运行 Chroma)

### 2. 安装 Chroma 向量数据库

```bash
docker run -d -p 8001:8000 chromadb/chroma
```

### 3. 下载嵌入模型

下载 ONNX 格式的嵌入模型并放置到 `src/main/resources/models/` 目录:

```bash
# 创建模型目录
mkdir -p src/main/resources/models

# 下载模型 (需要手动下载)
# all-MiniLM-L6-v2.onnx: https://github.com/SILICONAI/chroma-onnx-models/releases/download/v0.1.1/all-MiniLM-L6-v2.onnx
# tokenizer.json: https://raw.githubusercontent.com/Muennighoff/sgpt-bloom-7b1-slim/main/tokenizer.json

# 或使用 curl 下载
curl -L -o src/main/resources/models/all-MiniLM-L6-v2.onnx https://github.com/SILICONAI/chroma-onnx-models/releases/download/v0.1.1/all-MiniLM-L6-v2.onnx
curl -L -o src/main/resources/models/tokenizer.json https://raw.githubusercontent.com/Muennighoff/sgpt-bloom-7b1-slim/main/tokenizer.json
```

或者使用 Hugging Face 模型:

```yaml
# 在 application.yml 中配置
spring:
  ai:
    embedding:
      transformers:
        onnx:
          model-uri: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/model.onnx
          tokenizer-uri: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json
```

### 4. 配置 DeepSeek API Key（与 Wukong 一致）

在 `application.yml` 中配置或设置环境变量:

```bash
export DEEPSEEK_API_KEY=your-deepseek-api-key
```

获取 API Key：https://platform.deepseek.com/api_keys

或者使用其他模型提供商(如 Ollama 本地模型):

```yaml
spring:
  ai:
    ollama:
      base-url: http://localhost:11434
      chat:
        options:
          model: qwen2:latest
```

### 5. 运行应用

```bash
mvn spring-boot:run
```

应用将在 `http://localhost:8080` 启动。

### 6. 加载语料库

应用启动后,加载本地MD文档语料库:

```bash
curl -X POST http://localhost:8080/api/documents/load/directory \
  -H "Content-Type: application/json" \
  -d '{
    "directory": "./md_documents_collected",
    "metadata": {
      "source": "本地语料库",
      "category": "技术文档"
    }
  }'
```

加载完成后,系统将处理所有MD文件并进行向量化存储。

## API 文档

### 文档管理 API

#### 添加文本文档
```http
POST /api/documents/text
Content-Type: application/json

{
  "content": "这是文档内容",
  "metadata": {
    "category": "技术",
    "author": "张三"
  }
}
```

#### 添加 PDF 文档
```http
POST /api/documents/pdf
Content-Type: multipart/form-data

file: [PDF 文件]
category: 技术 (可选)
```

#### 添加文本文件
```http
POST /api/documents/text-file
Content-Type: multipart/form-data

file: [文本文件]
category: 技术 (可选)
```

#### 相似度搜索
```http
POST /api/documents/search
Content-Type: application/json

{
  "query": "搜索关键词",
  "topK": 5,
  "similarityThreshold": 0.7
}
```

### RAG 问答 API

#### 简单问答
```http
POST /api/rag/query/simple
Content-Type: application/json

{
  "query": "什么是 Spring Boot?"
}
```

#### 详细问答(带来源)
```http
POST /api/rag/query
Content-Type: application/json

{
  "query": "什么是 Spring Boot?",
  "topK": 5,
  "similarityThreshold": 0.7
}
```

#### 流式问答
```http
GET /api/rag/stream?query=什么是 Spring Boot?
```

## 使用示例

### 1. 批量加载本地语料库

```bash
# 先扫描目录,查看文件情况
curl -X GET "http://localhost:8080/api/documents/load/scan?directory=./md_documents_collected"

# 批量加载所有MD文件
curl -X POST http://localhost:8080/api/documents/load/directory \
  -H "Content-Type: application/json" \
  -d '{
    "directory": "./md_documents_collected",
    "metadata": {
      "source": "本地语料库",
      "category": "技术文档"
    }
  }'

# 响应示例
# {
#   "success": true,
#   "successCount": 25149,
#   "skippedCount": 0,
#   "errors": [],
#   "message": null
# }
```

### 2. 添加单个文档

```bash
# 添加文本文档
curl -X POST http://localhost:8080/api/documents/text \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Spring Boot 是基于 Spring 框架的开发框架,简化了 Spring 应用的配置和部署。",
    "metadata": {"category": "技术"}
  }'

# 添加 PDF 文档
curl -X POST http://localhost:8080/api/documents/pdf \
  -F "file=@document.pdf" \
  -F "category=技术"
```

### 3. 问答

```bash
# 简单问答
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "Spring Boot 有什么特点?"}'

# 详细问答
curl -X POST http://localhost:8080/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Spring Boot 有什么特点?",
    "topK": 5,
    "similarityThreshold": 0.7
  }'
```

## 配置说明

### 向量存储配置

```yaml
spring:
  ai:
    vectorstore:
      chroma:
        client:
          host: localhost
          port: 8000
        collection-name: knowledge-base
        initialize-schema: true
```

### 文档分块配置

```yaml
app:
  documents:
    storage-path: ./documents
    chunk-size: 1000      # 分块大小 (token 数)
    chunk-overlap: 200    # 分块重叠
```

### 嵌入模型配置

```yaml
spring:
  ai:
    embedding:
      onnx:
        model-uri: classpath:/models/all-MiniLM-L6-v2.onnx
        tokenizer-uri: classpath:/models/tokenizer.json
```

## 高级功能

### 1. 使用本地 LLM (Ollama)

```yaml
spring:
  ai:
    ollama:
      base-url: http://localhost:11434
      chat:
        options:
          model: qwen2:latest
          temperature: 0.7
```

### 2. 自定义提示词模板

修改 `src/main/resources/prompts/rag-prompt.st` 文件来自定义提示词。

### 3. 多语言支持

支持多种文档格式:
- TXT 文本文件
- MD / Markdown 文件
- 自动过滤不支持格式
- 可以扩展支持更多格式

## 常见问题

### 1. Chroma 连接失败

确保 Chroma 容器正在运行:
```bash
docker ps | grep chroma
# 或
docker run -d -p 8001:8000 chromadb/chroma
```

### 2. 模型下载失败

手动下载模型文件或配置使用 Hugging Face CDN:
```bash
mkdir -p src/main/resources/models
curl -L -o src/main/resources/models/all-MiniLM-L6-v2.onnx https://github.com/SILICONAI/chroma-onnx-models/releases/download/v0.1.1/all-MiniLM-L6-v2.onnx
curl -L -o src/main/resources/models/tokenizer.json https://raw.githubusercontent.com/Muennighoff/sgpt-bloom-7b1-slim/main/tokenizer.json
```

### 3. DeepSeek API Key 错误

确保设置了正确的 API Key 或使用其他模型提供商:
```bash
export DEEPSEEK_API_KEY=your-deepseek-api-key
```

### 4. 语料库加载失败

确保语料库目录存在且有读权限:
```bash
ls -la ./md_documents_collected
# 应该显示 25149 个文件,共 327MB
```

### 5. 文件格式不支持

系统自动筛选支持的格式(.txt, .md),不支持格式会自动跳过:
```bash
# 查看支持的格式
curl -X GET http://localhost:8080/api/documents/load/supported-formats
```

## 扩展建议

1. **前端界面**: 使用 React/Vue 构建聊天界面
2. **用户认证**: 添加 Spring Security 进行用户管理
3. **文档管理**: 实现文档的 CRUD 操作
4. **性能优化**: 添加缓存和异步处理
5. **监控**: 集成 Micrometer 进行性能监控
6. **文档增量更新**: 实现定期同步语料库更新
7. **多租户支持**: 为不同用户提供独立的知识库空间

## 项目就绪检查清单

在启动项目前,请确认以下条件已满足:

- [ ] Java 17+ 已安装
- [ ] Maven 3.8+ 已安装
- [ ] Docker 已安装
- [ ] Chroma 容器正在运行 (`localhost:8001`)
- [ ] ONNX 嵌入模型已下载到 `src/main/resources/models/`
- [ ] DeepSeek API Key 已配置 (或使用 Ollama 等本地模型)
- [ ] 语料库目录 `./md_documents_collected/` 存在 (25,149 个MD文件, 327MB)
- [ ] 所有文档文件具有读权限

## 许可证

MIT License
