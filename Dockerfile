# CTMS 单容器镜像（仓库根入口；与 deploy/Dockerfile.single 等价）
#
# 用途：面向"从 Git 仓库自动构建"的平台（宝塔 Docker 项目 / CI 等）——它们在
# 仓库根找 Dockerfile 与 docker-compose.yml，因此这里提供根级入口。
# 手动构建：docker build -t ctms:2.6.1 .
# 导出：docker save ctms:2.6.1 | gzip > ctms-image-2.6.1-core.tar.gz

# ---------- 阶段 1：构建前端 ----------
FROM node:20-alpine AS fe
ARG NPM_REGISTRY=https://registry.npmmirror.com
WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm config set registry ${NPM_REGISTRY} && \
    (npm ci --no-audit --no-fund || npm install --no-audit --no-fund)
COPY web/ ./
RUN npm run build && ls -la /build/dist

# ---------- 阶段 2：运行（Python） ----------
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    CTMS_DB_URL=sqlite:////data/ctms.db \
    CTMS_UPLOAD_DIR=/data/uploads \
    CTMS_LOG_DIR=/data/logs \
    CTMS_SERVE_STATIC=1 \
    CTMS_WEB_DIST=/srv/web/dist

# 国内网络：pip 走镜像（可用 --build-arg PIP_INDEX_URL 覆盖）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
COPY app/requirements.txt app/requirements-pg.txt /app/
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} \
        -r /app/requirements.txt -r /app/requirements-pg.txt

COPY app/ /app/app/
COPY --from=fe /build/dist /srv/web/dist

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
