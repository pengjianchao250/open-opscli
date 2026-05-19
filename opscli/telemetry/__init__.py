# opscli/telemetry/__init__.py
"""opscli 遥测模块。

自动采集 CLI 命令和 MCP Tool 的执行遥测数据，异步上报到后端。
此模块为内部基础设施，不注册为 CLI 子命令，用户不可见。
"""
from opscli.telemetry.collector import (
    build_event,
    pop_error_type,
    pop_status,
    set_error,
)
from opscli.telemetry.reporter import TelemetryReporter

__all__ = [
    "TelemetryReporter",
    "build_event",
    "pop_error_type",
    "pop_status",
    "set_error",
]
