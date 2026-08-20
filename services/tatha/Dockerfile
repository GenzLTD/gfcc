# gfcc 中央大脑 — Tatha
# 构建（在仓库根执行）：
#   docker build -f services/tatha/Dockerfile -t gfcc/tatha .
#
# 说明：
# - 密钥不写死（DEEPSEEK_API_KEY / ETHOS_AUTH_SECRET 由 compose 环境注入）
# - ethos / tenet 为 monorepo 内共享内核，editable 安装（相对路径 ../ 与 requirements.txt 一致）
# - 精简依赖集（与运行路径一致）；完整依赖见 pyproject.toml

FROM python:3.13-slim

WORKDIR /opt/tatha

# 共享内核：ethos 安全底座 + tenet 内核
COPY services/ethos /opt/ethos
COPY services/tenet /opt/tenet

# 项目源码
COPY services/tatha /opt/tatha

# 先装共享内核（零依赖，快），再装运行依赖
RUN pip install --no-cache-dir -e /opt/ethos -e /opt/tenet \
    && pip install --no-cache-dir \
        fastapi uvicorn pydantic chromadb litellm openai httpx \
        python-jose pyyaml python-multipart markitdown

ENV TATHA_DEFAULT_MODEL=deepseek/deepseek-chat
ENV TATHA_USE_LLM_INTENT=false
ENV PYTHONPATH=/opt/tatha/src

EXPOSE 5210

CMD ["uvicorn", "tatha.api.app:app", "--host", "0.0.0.0", "--port", "5210"]
