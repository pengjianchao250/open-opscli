r"""MCP Session & JWT 本地持久化存储。

授权成功后的 session_id 和 JWT Token 自动保存到用户本地文件，避免每次重启
MCP 服务或开启新对话时都需要重新走 Device Flow 或向后端换取 JWT。

保存位置（跨平台）：
- macOS / Linux: ~/.config/opscli/mcp_sessions.json
- Windows:       C:\Users\<user>\.config\opscli\mcp_sessions.json

文件权限：600（仅所有者可读写）

设计原则：
- 服务器重启后自动加载已有 session 和 JWT，减少重复授权和重复换取
- 每个系统（ops / polaris 等）独立保存 session + JWT
- 过期/无效 JWT 自动清理，换取新 JWT 时自动覆盖
- 仍保持"服务器不保存 OAuth 凭证"的语义（凭证存用户本地文件，非服务器内存）
"""

from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR

SESSIONS_FILE = Path(CONFIG_DIR) / "mcp_sessions.json"


def _ensure_dir() -> None:
    """确保配置目录存在。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_raw() -> dict[str, Any]:
    """加载原始 session 数据。"""
    if not SESSIONS_FILE.exists():
        return {"version": 2, "sessions": {}}
    try:
        with SESSIONS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"version": 2, "sessions": {}}


def _save_raw(data: dict[str, Any]) -> None:
    """保存 session 数据到本地文件。"""
    _ensure_dir()
    tmp = SESSIONS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(SESSIONS_FILE)
    # 设置文件权限 600（仅所有者可读写）
    try:
        SESSIONS_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows 可能不支持 chmod


# ── session_id 管理 ──────────────────────────────────────────────


def save_session(system: str, session_id: str) -> None:
    """保存指定系统的 session_id 到本地。

    Args:
        system:     系统别名（如 "ops"、"polaris"）
        session_id: OAuth 授权后的 Session ID
    """
    data = _load_raw()
    data.setdefault("sessions", {})
    entry = data["sessions"].get(system, {})
    entry["session_id"] = session_id
    entry["saved_at"] = datetime.now(timezone.utc).isoformat()
    data["sessions"][system] = entry
    _save_raw(data)


def get_session(system: str = "ops") -> str | None:
    """获取指定系统保存的 session_id。

    Args:
        system: 系统别名（默认 "ops"）

    Returns:
        session_id 字符串，不存在则返回 None
    """
    data = _load_raw()
    entry = data.get("sessions", {}).get(system)
    if not entry:
        return None
    return entry.get("session_id")


# ── JWT 管理 ─────────────────────────────────────────────────────


def save_jwt(system: str, jwt: str) -> None:
    """保存指定系统的 JWT 到本地。

    Args:
        system: 系统别名（如 "ops"、"polaris"）
        jwt:    JWT Token 字符串
    """
    data = _load_raw()
    data.setdefault("sessions", {})
    entry = data["sessions"].get(system, {})
    entry["jwt"] = jwt
    entry["jwt_saved_at"] = datetime.now(timezone.utc).isoformat()
    data["sessions"][system] = entry
    _save_raw(data)


def get_jwt(system: str = "ops") -> str | None:
    """获取指定系统保存的 JWT。

    Args:
        system: 系统别名（默认 "ops"）

    Returns:
        JWT 字符串，不存在则返回 None
    """
    data = _load_raw()
    entry = data.get("sessions", {}).get(system)
    if not entry:
        return None
    return entry.get("jwt")


def clear_jwt(system: str) -> bool:
    """清除指定系统保存的 JWT（保留 session_id）。

    Args:
        system: 系统别名

    Returns:
        是否成功清除
    """
    data = _load_raw()
    entry = data.get("sessions", {}).get(system)
    if entry and "jwt" in entry:
        del entry["jwt"]
        del entry["jwt_saved_at"]
        _save_raw(data)
        return True
    return False


# ── 统一获取（自动组合 session_id + JWT）───────────────────────────


def get_auth_pair(system: str = "ops") -> tuple[str | None, str | None]:
    """获取指定系统的 session_id 和 JWT（均从本地加载）。

    Args:
        system: 系统别名（默认 "ops"）

    Returns:
        (session_id, jwt) 元组，任一不存在则为 None
    """
    data = _load_raw()
    entry = data.get("sessions", {}).get(system)
    if not entry:
        return None, None
    return entry.get("session_id"), entry.get("jwt")


# ── 完整会话管理 ─────────────────────────────────────────────────


def list_sessions() -> dict[str, dict[str, Any]]:
    """列出所有已保存的 session（含 session_id 和 JWT）。

    Returns:
        {system: {"session_id": ..., "jwt": ..., "saved_at": ...}, ...}
    """
    data = _load_raw()
    return dict(data.get("sessions", {}))


def remove_session(system: str) -> bool:
    """移除指定系统的本地 session（session_id + JWT 一并删除）。

    Args:
        system: 系统别名

    Returns:
        是否成功移除（session 存在且已删除）
    """
    data = _load_raw()
    sessions = data.get("sessions", {})
    if system in sessions:
        del sessions[system]
        _save_raw(data)
        return True
    return False


def clear_all_sessions() -> None:
    """清除所有本地保存的 session 和 JWT。"""
    _save_raw({"version": 2, "sessions": {}})


# ── 辅助：JWT 本地有效性检查 ─────────────────────────────────────


def is_jwt_valid_locally(jwt: str, leeway: int = 60) -> bool:
    """本地解析 JWT payload 检查是否过期（不验证签名）。

    Args:
        jwt:     JWT 字符串
        leeway:  允许的时钟偏差秒数（默认 60s）

    Returns:
        True 如果 JWT 未过期或无法判断，False 如果已明确过期
    """
    try:
        parts = jwt.split(".")
        if len(parts) != 3:
            return False
        payload_b64 = parts[1]
        # 补齐 base64url padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        import base64

        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if not exp:
            return True  # 无 exp 视为长期有效
        remaining = int(exp - datetime.now(timezone.utc).timestamp())
        return remaining > leeway
    except Exception:
        return False  # 解析失败视为无效
