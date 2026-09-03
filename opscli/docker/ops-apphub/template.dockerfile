# syntax=docker/dockerfile:1.7
# ops-apphub 模板基础镜像，包含 opscli、Python 3.11、Node.js 24、pnpm、uv 等运行环境。

ARG NODE_IMAGE=docker.io/library/node:24-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.0

FROM ${UV_IMAGE} AS uv
FROM ${NODE_IMAGE} AS system

ARG PNPM_VERSION=10.14.0
ARG DEBIAN_FRONTEND=noninteractive

ENV VIRTUAL_ENV=/opt/venv \
    COREPACK_HOME=/opt/corepack \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    HOME=/home/app \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    APP_DB_PATH=/data/app.db \
    PATH=/opt/venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Python 3.11 与编译工具用于构建 opscli，并支持模板应用安装缺少 wheel 的依赖。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        pkg-config \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

FROM system AS opscli-builder

ENV OPSCLI_SKILL_PROFILE=internal

WORKDIR /src

# 使用锁文件构建当前提交，保证 Jenkins 产物与仓库版本一致。
COPY pyproject.toml setup.py README.md MANIFEST.in uv.lock ./
COPY opscli ./opscli
RUN python3 -m venv "${VIRTUAL_ENV}" \
    && uv sync --locked --no-editable \
    && opscli --version \
    && python -c "import opscli.app"

# Cython 默认携带调试符号，剥离后显著减少内部基础镜像体积。
RUN find "${VIRTUAL_ENV}" -type f -name '*.so' -exec strip --strip-unneeded {} +

FROM system

COPY --from=opscli-builder /opt/venv /opt/venv

# pnpm 与模板 packageManager 保持一致，运行目录统一交给非 root 用户。
RUN mkdir -p "${COREPACK_HOME}" \
    && corepack enable \
    && corepack install --global "pnpm@${PNPM_VERSION}" \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /app /data \
    && chown -R app:app /app /data "${VIRTUAL_ENV}" "${COREPACK_HOME}" \
    && python --version \
    && node --version \
    && pnpm --version \
    && uv --version \
    && opscli --version

WORKDIR /app
USER app
EXPOSE 8000
