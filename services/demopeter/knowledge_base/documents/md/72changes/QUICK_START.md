# Spring Boot + Spring AI 本地知识库快速启动指南

## 前置条件

- Java 17+
- Maven 3.8+
- Docker (用于 Chroma 向量数据库)
- DeepSeek API Key（与 Wukong 一致，或使用 Ollama 本地模型）

## 1. 启动 Chroma 向量数据库

```bash
docker-compose up -d chroma
```

或者直接运行:

```bash
docker run -d -p 8001:8000 chromadb/chroma
```

## 2. 配置 DeepSeek API Key

### 方法 1: 环境变量
```bash
export DEEPSEEK_API_KEY=your-deepseek-api-key-here
```

### 方法 2: 修改配置文件
编辑 `src/main/resources/application.yml`,将你的 API Key 替换进去。

## 3. 使用本地 LLM (可选,推荐)

如果你有 Ollama,可以启动 Ollama 服务:

```bash
docker-compose up -d ollama
```

然后在 `application.yml` 中配置:

```yaml
spring:
  ai:
    ollama:
      base-url: http://localhost:11434
      chat:
        options:
          model: qwen2:latest
```

## 4. 启动应用

```bash
mvn spring-boot:run
```

应用将在 `http://localhost:8080` 启动。

## 5. 测试 API

### 5.1 添加文本文档

```bash
curl -X POST http://localhost:8080/api/documents/text \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Spring Boot 是基于 Spring 框架的开发框架,简化了 Spring 应用的配置和部署。它提供了自动配置、嵌入式服务器、生产就绪特性等功能。",
    "metadata": {"category": "技术", "topic": "Spring Boot"}
  }'
```

### 5.2 添加文本文件

```bash
curl -X POST http://localhost:8080/api/documents/text-file \
  -F "file=@README.md" \
  -F "category=文档"
```

### 5.3 简单问答

```bash
curl -X POST http://localhost:8080/api/rag/query/simple \
  -H "Content-Type: application/json" \
  -d '{"query": "什么是 Spring Boot?"}'
```

### 5.4 详细问答 (带来源)

```bash
curl -X POST http://localhost:8080/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Spring Boot 有什么特点?",
    "topK": 5,
    "similarityThreshold": 0.6
  }'
```

### 5.5 相似度搜索

```bash
curl -X POST http://localhost:8080/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Spring Boot 自动配置",
    "topK": 3,
    "similarityThreshold": 0.5
  }'
```

## 项目说明

### 核心功能

1. **文档管理**
   - 支持文本、TXT 文件上传
   - 文档自动分块
   - 向量嵌入和存储

2. **向量搜索**
   - 基于语义的相似度搜索
   - 可配置的 topK 和阈值

3. **RAG 问答**
   - 检索增强生成
   - 支持简单问答和详细问答
   - 支持流式输出

### 文件结构

```
src/main/java/com/knowledgebase/
├── KnowledgeBaseApplication.java      # 主应用类
├── config/
│   ├── AIConfiguration.java          # AI 配置 (ChatClient)
│   └── VectorStoreConfiguration.java  # 向量存储配置
├── controller/
│   ├── DocumentController.java       # 文档管理 API
│   └── RAGController.java            # RAG 问答 API
├── model/
│   ├── QueryRequest.java            # 查询请求
│   └── QueryResponse.java           # 查询响应
└── service/
    ├── DocumentService.java         # 文档服务
    └── RAGService.java              # RAG 服务
```

## 常见问题

### Q1: Chroma 连接失败

确保 Chroma 容器正在运行:
```bash
docker ps | grep chroma
```

### Q2: 没有配置 DeepSeek API Key

可以使用 Ollama 本地 LLM,参考上面的"使用本地 LLM"部分。

### Q3: 编译错误

确保 Maven 依赖下载完成:
```bash
mvn clean install -DskipTests
```

### Q4: 文档上传失败

检查 `documents` 目录权限:
```bash
chmod 755 documents/
```

## API 文档

完整的 API 文档和测试示例请查看 `api-example.http` 文件。

## 下一步

1. 添加更多文档到知识库
2. 自定义提示词模板 (`src/main/resources/prompts/rag-prompt.st`)
3. 集成前端界面 (React/Vue)
4. 添加用户认证 (Spring Security)
5. 部署到生产环境

## 技术支持

如有问题,请查看:
- Spring AI 官方文档: https://docs.spring.io/spring-ai/reference/
- Chroma 文档: https://docs.trychroma.com/
- 项目 README.md
