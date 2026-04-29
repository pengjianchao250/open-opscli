"""MCP Tool 上下文辅助函数（无状态模式保留兼容）。

无状态模式下服务器不保存用户凭证，本模块仅保留空操作函数以兼容历史代码路径。
所有函数均标记为待废弃，新代码不应调用这些函数。
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any


def configure_multi_user(
    *,
    enabled: bool,
    require_auth: bool = False,
    base_dir: Path | None = None,
) -> None:
    """无状态模式下此函数为空操作。"""
    warnings.warn(
        "configure_multi_user 已废弃，无状态下为空操作",
        DeprecationWarning,
        stacklevel=2,
    )


def is_multi_user_enabled() -> bool:
    """无状态模式下始终返回 False。"""
    warnings.warn(
        "is_multi_user_enabled 已废弃，无状态下始终返回 False",
        DeprecationWarning,
        stacklevel=2,
    )
    return False


async def get_credential_dir(ctx: Any | None = None) -> Path | None:
    """无状态模式下始终返回 None，调用方会使用默认单用户路径。"""
    warnings.warn(
        "get_credential_dir 已废弃，无状态下始终返回 None",
        DeprecationWarning,
        stacklevel=2,
    )
    return None
