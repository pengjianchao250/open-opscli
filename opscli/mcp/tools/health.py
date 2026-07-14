"""MCP 服务健康检查工具。"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from opscli.config import CONFIG_DIR, __version__

from .helpers import _err, _get_auth_pair, _get_credential_dir, _ok


async def ops_health_check(check_auth: bool = False) -> dict:
    """检查 MCP 服务基础健康状态。

    Args:
        check_auth: 是否额外检查当前 MCP 隔离凭证中是否存在 ops 登录态。
            默认 False，避免健康检查依赖用户登录状态。
    """
    started = time.perf_counter()
    try:
        credential_dir = _get_credential_dir()
        data = {
            "service": "opscli-mcp",
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "config_dir": str(CONFIG_DIR),
            "credential_dir": str(credential_dir) if credential_dir else None,
            "config_dir_writable": _is_writable(Path(CONFIG_DIR)),
            "asin_data_limiter": _asin_data_limiter_status(),
            "metrics": _metrics_status(),
            "auth": {"checked": False},
        }
        if check_auth:
            sid, jwt = _get_auth_pair("ops")
            data["auth"] = {
                "checked": True,
                "has_session_id": bool(sid),
                "has_jwt": bool(jwt),
            }
        data["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        return _ok(data)
    except Exception as exc:
        return _err(exc, tool="MCP → ops_health_check(...)", call_params={"check_auth": check_auth})


def _is_writable(path: Path) -> bool:
    """检查目录是否可写，不留下探测文件。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return os.access(path, os.W_OK)
    except Exception:
        return False


def _asin_data_limiter_status() -> dict:
    """读取 ASIN MCP 限流状态，失败时返回空状态。"""
    try:
        from opscli.mcp.asin_data_limit import get_limiter_status

        return get_limiter_status()
    except Exception as exc:
        return {"error": str(exc)}


def _metrics_status() -> dict:
    """返回本地指标日志配置。"""
    from opscli.asin_data.services.live_metrics import (
        DEFAULT_METRICS_PATH,
        ENV_ASIN_DATA_METRICS_DISABLED,
        ENV_ASIN_DATA_METRICS_PATH,
    )

    path = os.getenv(ENV_ASIN_DATA_METRICS_PATH) or DEFAULT_METRICS_PATH
    return {
        "enabled": os.getenv(ENV_ASIN_DATA_METRICS_DISABLED) != "1",
        "path": path,
    }


def register(mcp) -> None:
    """注册 MCP 健康检查工具。"""
    mcp.tool()(ops_health_check)
