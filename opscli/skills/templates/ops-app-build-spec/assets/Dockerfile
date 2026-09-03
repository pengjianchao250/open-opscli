# 前端阶段只安装锁定依赖并构建 Vite 产物。
FROM docker.io/library/node:24-alpine AS frontend-build

WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/
RUN corepack enable && pnpm --dir frontend install --frozen-lockfile
COPY frontend ./frontend
RUN pnpm --dir frontend run build

# 运行阶段由单个 FastAPI 进程托管页面和 API。
FROM docker.io/library/python:3.11-slim AS runtime

ENV APP_DB_PATH=/data/app.db \
    PORT=8000 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
RUN python -c "import opscli.app"
COPY backend ./backend
COPY migrations ./migrations
COPY app.yaml ./app.yaml
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/__apphub_healthz', timeout=2)" || exit 1
CMD ["sh", "-c", "python -m opscli.app.migrate && exec uvicorn backend.app:app --host 0.0.0.0 --port 8000"]
