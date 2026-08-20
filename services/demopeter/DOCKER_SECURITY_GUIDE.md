# Docker Compose 安全配置指南

## 配置文件说明

### 1. `docker-compose.yml`（原配置）
- 基础配置，适合快速开发
- 部分安全选项未启用

### 2. `docker-compose.secure.yml`（安全加固版）
- **资源限制**：防止容器耗尽系统资源
- **安全加固**：只读文件系统、权限控制
- **健康检查**：自动检测服务状态
- **日志管理**：防止日志文件过大
- **网络隔离**：增强网络安全性

## 快速使用

### 方案 A：使用安全配置（推荐）
```bash
# 本地开发（安全模式）
docker compose -f docker-compose.secure.yml up -d

# 生产部署（含 nginx）
docker compose -f docker-compose.secure.yml --profile production up -d

# 查看日志
docker compose -f docker-compose.secure.yml logs -f

# 停止服务
docker compose -f docker-compose.secure.yml down
```

### 方案 B：覆盖特定配置
```bash
# 同时使用两个文件（基础 + 安全覆盖）
docker compose -f docker-compose.yml -f docker-compose.secure.yml up -d
```

## 主要安全改进

### 1. 资源限制（防止 DoS）
| 服务 | 内存限制 | CPU 限制 |
|------|----------|----------|
| nginx | 256MB | 0.5 核 |
| web | 2GB | 2 核 |
| chroma | 4GB | 2 核 |
| pgvector | 2GB | 1 核 |

### 2. 安全加固选项
```yaml
# 只读文件系统（如可能）
read_only: true

# 禁止权限提升
security_opt:
  - no-new-privileges:true

# 删除所有 Linux 能力，仅添加必需的
cap_drop:
  - ALL
cap_add:
  - NET_BIND_SERVICE  # 仅 nginx 需要
```

### 3. 健康检查
- **web**: `curl -f http://localhost:5220/health`
- **chroma**: `curl -f http://localhost:8001/api/v1/heartbeat`
- **pgvector**: `pg_isready -U szpeter -d szpeter2026`

### 4. 网络隔离
```yaml
networks:
  szpeter2026-net:
    driver: bridge
    driver_opts:
      com.docker.network.bridge.enable_icc: "false"  # 禁止容器间通信
      com.docker.network.bridge.enable_ip_masquerade: "true"
```

### 5. 日志管理
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "50m"   # 单文件最大 50MB
    max-file: "5"      # 最多保留 5 个文件
```

## 生产环境额外建议

### 1. 创建非 root 用户（Dockerfile）
```dockerfile
# 在 Dockerfile 中添加
RUN useradd -m -u 1000 appuser
USER appuser
```

### 2. 使用 Docker Secrets 管理敏感信息
```yaml
# 替换 env_file
secrets:
  - deepseek_api_key
  - pgvector_password

secrets:
  deepseek_api_key:
    file: ./secrets/deepseek_api_key.txt
  pgvector_password:
    file: ./secrets/pgvector_password.txt
```

### 3. 启用 HTTPS（nginx）
```yaml
# 挂载 SSL 证书
volumes:
  - ./ssl/cert.pem:/etc/nginx/ssl/cert.pem:ro
  - ./ssl/key.pem:/etc/nginx/ssl/key.pem:ro
```

### 4. 定期更新镜像
```bash
# 定期拉取最新镜像
docker compose pull
docker compose up -d --build
```

## 故障排查

### 查看容器资源使用
```bash
docker stats
```

### 查看详细错误信息
```bash
docker compose -f docker-compose.secure.yml logs [service_name]
```

### 进入容器调试
```bash
docker exec -it szpeter2026-web /bin/bash
```

## 当前系统资源评估

根据检测结果：
- **CPU**: 4 核（可用）
- **内存**: 8GB（WSL2 分配）
- **C 盘**: 119GB 总容量，34GB 可用（72% 使用率）

**建议**：
1. 当前配置适合开发测试
2. 生产环境建议升级到 16GB+ 内存
3. 考虑将持久化数据迁移到独立磁盘
4. 定期清理 Docker 镜像和容器（`docker system prune -a`）

## 下一步行动

1. ✅ 测试安全配置文件
   ```bash
   docker compose -f docker-compose.secure.yml up -d
   ```

2. ⏳ 创建非 root 用户（Dockerfile）

3. ⏳ 配置 SSL 证书（生产环境）

4. ⏳ 设置监控和告警（Prometheus + Grafana）

5. ⏳ 定期备份数据（C:/DemoPeterTemp/）
