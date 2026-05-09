"""MCP 凭证目录隔离模块。

提供基于 API Key 哈希的凭证存储目录映射，实现多用户场景下的
凭证物理隔离。
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def get_credential_dir_for_key(api_key: str, base_root: Path) -> Path:
    """将 API Key 映射为固定长度的目录名。

    使用 SHA256 前 16 位作为目录名，避免特殊字符问题，
    同时保证相同的 API Key 始终映射到相同的目录。

    Args:
        api_key: 明文 API Key
        base_root: 凭证存储根目录（如 ~/.config/opscli/credentials_by_key/）

    Returns:
        该 API Key 对应的凭证隔离目录路径
    """
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    path = base_root / key_hash
    path.mkdir(parents=True, exist_ok=True)
    # 收紧权限：仅所有者可读写执行
    path.chmod(0o700)
    return path
