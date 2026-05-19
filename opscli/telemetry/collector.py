# opscli/telemetry/collector.py
"""遥测事件收集器。

负责构建标准事件 dict，并管理 CLI 模式下的错误状态
（异常时由 cli.py 通过 set_error() 写入，_report() 读取后上报）。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from opscli.version import get_version

# CLI 模式下，命令异常时写入此 dict，_report() 读取后清空。
# 使用 dict 而非单一变量，便于后续扩展更多错误字段。
_pending_error: dict[str, str] = {}


def set_error(exc: BaseException) -> None:
    """记录 CLI 命令执行中的异常，供 _report() 读取后上报。

    Args:
        exc: 捕获到的异常实例
    """
    _pending_error["error_type"] = type(exc).__name__


def pop_status() -> str:
    """获取当前命令的执行状态。

    有未读异常时返回 "error"，否则返回 "success"。
    不清空状态（由 pop_error_type 负责清空）。

    Returns:
        "success" 或 "error"
    """
    return "error" if _pending_error else "success"


def pop_error_type() -> str | None:
    """获取并清空当前命令的异常类型（pop 语义）。

    Returns:
        异常类名字符串，或 None（无异常时）
    """
    return _pending_error.pop("error_type", None)


def build_event(
    *,
    event_type: str,
    command: str,
    module: str,
    status: str,
    duration_ms: int | None = None,
    error_type: str | None = None,
    user_email: str | None = None,
    skill_name: str | None = None,
) -> dict[str, Any]:
    """构建标准遥测事件 dict。

    Args:
        event_type:  事件类型，"cli_command" 或 "mcp_tool"
        command:     命令路径，如 "query run" 或 "query_simple"（不含参数值）
        module:      所属模块，如 "query" / "auth"
        status:      执行结果，"success" 或 "error"
        duration_ms: 执行耗时（毫秒）
        error_type:  异常类名，仅 status=error 时有值
        user_email:  当前登录用户邮箱，未登录时为 None
        skill_name:  调用方 Skill 名称（MCP 环境变量传入）

    Returns:
        符合后端接口规范的事件 dict
    """
    # 延迟导入避免模块加载时产生副作用（如文件 I/O）
    from opscli.telemetry.device_id import get_device_id

    return {
        "event_type":     event_type,
        "command":        command,
        "module":         module,
        "status":         status,
        "duration_ms":    duration_ms,
        "error_type":     error_type,
        "user_email":     user_email,
        "device_id":      get_device_id(),
        "opscli_version": get_version(),
        "os":             sys.platform,
        "skill_name":     skill_name,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }
