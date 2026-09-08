# syntax=docker/dockerfile:1.7
# ops-apphub 模板基础镜像，运行阶段仅保留 Python 与已锁定依赖。

ARG PYTHON_IMAGE=docker.io/library/python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.0
ARG VCS_REF=unknown

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS python-base

ENV VIRTUAL_ENV=/opt/venv \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PATH=/opt/venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

FROM python-base AS opscli-builder

ARG DEBIAN_FRONTEND=noninteractive

ENV OPSCLI_SKILL_PROFILE=internal \
    UV_CACHE_DIR=/root/.cache/uv

COPY --from=uv /uv /uvx /usr/local/bin/

# 编译工具仅用于处理缺少预编译 wheel 的依赖。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 锁文件变化才重建第三方运行依赖层，uv 自行创建无 pip 的虚拟环境。
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=opscli-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-dev --no-install-project --no-editable

# 工作区源码只在本步骤挂载；SKIP_CYTHON 保留内部 SDK 的纯 Python 实现。
RUN --mount=type=bind,source=.,target=/workspace,rw \
    --mount=type=cache,id=opscli-uv-cache,target=/root/.cache/uv,sharing=locked \
    cd /workspace \
    && SKIP_CYTHON=1 uv sync --locked --no-dev --no-editable \
    && opscli --version \
    && python -c "import opscli.app"

FROM python-base

ARG VCS_REF

LABEL org.opencontainers.image.revision="${VCS_REF}"

ENV HOME=/home/app \
    PORT=8000 \
    SQLITE_PATH=/data/app.db

# 最终镜像只复制虚拟环境，应用目录交给固定 UID/GID 的非 root 用户。
COPY --from=opscli-builder /opt/venv /opt/venv
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/app app \
    && mkdir -p /app /data \
    && chown -R app:app /home/app /app /data \
    && test ! -e /workspace \
    && test ! -e /src

WORKDIR /app
USER app
EXPOSE 8000

# 以最终运行用户验证入口和应用模块，避免生成 root 用户配置。
RUN test "$(id -u)" = "1000" \
    && opscli --version \
    && python -c "import opscli.app"
