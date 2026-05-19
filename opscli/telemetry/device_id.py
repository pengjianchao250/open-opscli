# opscli/telemetry/device_id.py
"""机器唯一标识管理。

在 ~/.config/opscli/device_id 文件中持久化 UUID v4，
首次运行时自动生成，后续复用（内存缓存 + 文件持久化双层）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from opscli.config import CONFIG_DIR

# 持久化路径：~/.config/opscli/device_id
_DEVICE_ID_FILE: Path = CONFIG_DIR / "device_id"

# 内存缓存，避免每次调用都读文件
_cached: str | None = None


def get_device_id() -> str:
    """获取本机唯一标识。

    优先返回内存缓存，其次读取文件，首次运行时生成并持久化。

    Returns:
        UUID v4 格式的机器唯一标识字符串
    """
    global _cached

    # 1. 内存缓存命中，直接返回
    if _cached:
        return _cached

    # 2. 文件已存在，读取并缓存
    if _DEVICE_ID_FILE.exists():
        content = _DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
        if content:
            _cached = content
            return _cached

    # 3. 首次运行：生成新 UUID 并写入文件
    _cached = str(uuid.uuid4())
    try:
        _DEVICE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DEVICE_ID_FILE.write_text(_cached, encoding="utf-8")
    except OSError:
        # 文件写入失败（权限不足等）不影响本次使用
        pass

    return _cached
