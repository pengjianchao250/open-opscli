"""MCP Tool 上下文辅助函数（无状态模式保留兼容）。

无状态模式下服务器不保存用户凭证，本模块不再承担凭证目录解析职责，
仅保留空操作函数以兼容历史代码路径。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def configure_multi_user(
    *,
    enabled: bool,
    require_auth: bool = False,
    base_dir: Path | None = None,
) -> None:
    """无状态模式下此函数为空操作。"""
    pass


def is_multi_user_enabled() -> bool:
    """无状态模式下始终返回 False。"""
    return False


async def get_credential_dir(ctx: Any | None = None) -> Path | None:
    """无状态模式下始终返回 None，调用方会使用默认单用户路径。"""
    return None
