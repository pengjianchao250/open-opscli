"""MCP 凭证目录隔离模块。

提供基于 API Key 哈希的凭证存储目录映射，实现多用户场景下的
凭证物理隔离。
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def get_credential_dir_for_key(
    api_key: str,
    base_root: Path,
    agent_name: str | None = None,
) -> Path:
    """将 API Key（+ 可选 agent_name）映射为固定长度的目录名。

    传入 agent_name 时联合计算 SHA256，实现 Agent 级别的凭证物理隔离：
    同一 API Key 在不同 Agent 工具（Claude Code / Cursor 等）下各自独立。

    分隔符 "::" 防止 api_key 与 agent_name 拼接时产生哈希碰撞。
    不传 agent_name 时退回纯 api_key 哈希，向后兼容旧目录结构。

    Args:
        api_key:    明文 API Key
        base_root:  凭证存储根目录（如 ~/.config/opscli/credentials_by_key/）
        agent_name: 可选，标准化后的 Agent 名称（如 "claude-code"、"cursor"）

    Returns:
        该 API Key + Agent 对应的凭证隔离目录路径
    """
    # agent_name 存在时联合计算，否则退回纯 api_key（向后兼容）
    combined = f"{api_key}::{agent_name}" if agent_name else api_key
    key_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]
    path = base_root / key_hash
    path.mkdir(parents=True, exist_ok=True)
    # 收紧权限：仅所有者可读写执行
    path.chmod(0o700)
    return path
