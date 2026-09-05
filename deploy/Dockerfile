# CTMS 应用镜像
FROM python:3.13-slim
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
EXPOSE 8000
# 注意：uploads 与 sqlite/data 默认在 app 内，请把 app/uploads、app/data 挂载为卷；
# 使用 PostgreSQL 时无需挂 data。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
