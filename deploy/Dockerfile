# CTMS 应用镜像
FROM python:3.13-slim
WORKDIR /app
# V2.3：同时安装 PostgreSQL 驱动（psycopg2-binary），使镜像可直接连 PostgreSQL
# （`psycopg2-binary` 为预编译 wheel，slim 镜像无需额外系统依赖）
COPY app/requirements.txt app/requirements-pg.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-pg.txt
COPY app/ ./app/
EXPOSE 8000
# 默认 SQLite（挂载 app/data 与 app/uploads）；连 PostgreSQL 时设置：
#   CTMS_DB_URL=postgresql+psycopg2://ctms:CHANGE_ME@db:5432/ctms
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
