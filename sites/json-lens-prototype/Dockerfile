# syntax=docker/dockerfile:1.7
ARG APPHUB_BASE_IMAGE=120.79.133.243:7531/ops-apphub/opscli-base-release:latest
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.0

FROM ${UV_IMAGE} AS uv

FROM docker.io/library/node:24-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/vite.config.js frontend/app.js frontend/styles.css frontend/table-utils.js ./
RUN npm run build

FROM ${APPHUB_BASE_IMAGE} AS runtime

USER root
WORKDIR /app

COPY requirements-app.txt ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,id=test-keepa-python,target=/root/.cache/uv,sharing=locked \
    export UV_CACHE_DIR=/root/.cache/uv \
    && uv pip install --python /opt/venv/bin/python -r requirements-app.txt \
    && uv pip check --python /opt/venv/bin/python \
    && /opt/venv/bin/python -c "import opscli.keepa.api.scenarios; import opscli.mcp.tools.keepa"

COPY --chown=app:app backend ./backend
COPY --from=frontend-build --chown=app:app /app/frontend/dist ./frontend/dist

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/__apphub_healthz', timeout=2)" || exit 1

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
