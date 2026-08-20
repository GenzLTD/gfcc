# gfcc RAG 知识库 — DemoPeter
# 构建（在仓库根执行）：
#   docker build -f services/demopeter/Dockerfile -t gfcc/demopeter .
#
# 说明：
# - ethos 为 monorepo 内共享安全底座，editable 安装（requirements.txt 中的 ../ethos）
# - .env* 由 .dockerignore 排除，密钥一律经 compose 注入

FROM python:3.12-slim

# 系统依赖（pdfplumber 需要 libstdc++ 等）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ethos 安全底座（monorepo 同级，供 requirements.txt 的 -e ../ethos 使用）
COPY services/ethos /ethos

# 先装依赖（利用 Docker 缓存层）
COPY services/demopeter/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

# 复制项目代码
COPY services/demopeter/ .

# 兼容 static/src 布局，保持 gunicorn 入口 src.web_dashboard:app
RUN ln -sf /app/static/src /app/src

EXPOSE 5220

# 使用 Gunicorn 运行 Flask（生产模式）
CMD ["gunicorn", "--bind", "0.0.0.0:5220", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "src.web_dashboard:app"]
