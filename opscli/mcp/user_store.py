"""MCP 多用户注册表。

本模块负责管理 `~/.config/opscli/mcp_users.json`，为团队共享 MCP Server
提供 API Key 到独立凭证目录的映射。注册表只保存 API Key 哈希，原始 Key
仅在创建或轮换时展示一次。
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import secrets
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import ascii_letters, digits
from typing import Iterator

try:
    import fcntl
    _FCNTL_AVAILABLE = True
except ImportError:
    _FCNTL_AVAILABLE = False


API_KEY_PREFIX = "opscli-mcp-"
API_KEY_RANDOM_LENGTH = 32


def generate_api_key() -> str:
    """生成固定格式的高熵 API Key（模块级公共接口）。

    格式：opscli-mcp-<32位随机字母数字>
    供 server.py 和 MCPUserStore 共用，避免重复实现。

    Returns:
        高熵 API Key 字符串
    """
    alphabet = ascii_letters + digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(API_KEY_RANDOM_LENGTH))
    return API_KEY_PREFIX + random_part


@dataclass(frozen=True)
class MCPUser:
    """MCP 用户记录，包含凭证隔离目录。"""

    user_id: str
    description: str
    created_at: str
    credential_dir: Path

    def to_dict(self) -> dict:
        """转换为对外展示的 JSON 结构，不包含 API Key 哈希。"""
        return {
            "user_id": self.user_id,
            "description": self.description,
            "created_at": self.created_at,
            "credential_dir": str(self.credential_dir),
        }


class MCPUserStore:
    """MCP 用户注册表管理器。"""

    def __init__(self, base_dir: Path | None = None):
        from opscli.config import CONFIG_DIR

        self.base_dir = Path(base_dir or CONFIG_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir = self.base_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self.path = self.base_dir / "mcp_users.json"
        self.lock_path = self.base_dir / ".mcp_users.lock"

    def list_users(self) -> list[MCPUser]:
        """列出所有 MCP 用户，不返回 API Key 哈希。"""
        return [
            MCPUser(
                user_id=item["user_id"],
                description=item.get("description", ""),
                created_at=item.get("created_at", ""),
                credential_dir=self.credential_dir(item["user_id"]),
            )
            for item in self._load()
        ]

    def add_user(self, description: str = "") -> dict:
        """创建 MCP 用户，并返回只展示一次的明文 API Key。"""
        with self._locked():
            users = self._load()
            user_id = self._new_user_id(users)
            api_key = self._new_api_key()
            now = datetime.now(timezone.utc).isoformat()
            users.append(
                {
                    "user_id": user_id,
                    "api_key_hash": self.hash_api_key(api_key),
                    "description": description,
                    "created_at": now,
                }
            )
            self._save(users)
            self._ensure_credential_dir(user_id)
        return {
            "user_id": user_id,
            "api_key": api_key,
            "description": description,
            "created_at": now,
            "credential_dir": str(self.credential_dir(user_id)),
        }

    def remove_user(self, user_id: str, *, keep_credentials: bool = False) -> bool:
        """删除 MCP 用户，默认同步删除该用户的隔离凭证目录。"""
        with self._locked():
            users = self._load()
            kept = [item for item in users if item.get("user_id") != user_id]
            if len(kept) == len(users):
                return False
            self._save(kept)
            if not keep_credentials:
                self._remove_credential_dir(user_id)
            return True

    def rotate_api_key(self, user_id: str) -> dict:
        """轮换指定用户的 API Key，返回新 Key 明文。"""
        with self._locked():
            users = self._load()
            api_key = self._new_api_key()
            rotated_at = datetime.now(timezone.utc).isoformat()
            for item in users:
                if item.get("user_id") == user_id:
                    item["api_key_hash"] = self.hash_api_key(api_key)
                    item["rotated_at"] = rotated_at
                    self._save(users)
                    return {
                        "user_id": user_id,
                        "api_key": api_key,
                        "rotated_at": rotated_at,
                        "credential_dir": str(self.credential_dir(user_id)),
                    }
        raise ValueError(f"未找到 MCP 用户: {user_id}")

    def verify_api_key(self, api_key: str | None) -> MCPUser | None:
        """校验 API Key，成功时返回对应 MCP 用户。"""
        if not api_key:
            return None
        normalized = self.normalize_api_key(api_key)
        expected = self.hash_api_key(normalized)
        for item in self._load():
            if hmac.compare_digest(str(item.get("api_key_hash", "")), expected):
                user_id = str(item["user_id"])
                self._ensure_credential_dir(user_id)
                return MCPUser(
                    user_id=user_id,
                    description=item.get("description", ""),
                    created_at=item.get("created_at", ""),
                    credential_dir=self.credential_dir(user_id),
                )
        return None

    def credential_dir(self, user_id: str) -> Path:
        """返回指定用户的凭证隔离目录。"""
        return self.users_dir / user_id

    @classmethod
    def normalize_api_key(cls, raw: str) -> str:
        """兼容 Bearer 头与纯 API Key 两种输入。"""
        value = raw.strip()
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        return value

    @classmethod
    def hash_api_key(cls, api_key: str) -> str:
        """计算 API Key 的 SHA256 哈希。"""
        return "sha256:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def _load(self) -> list[dict]:
        """读取用户注册表，文件不存在时返回空列表。"""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCP 用户注册表 JSON 损坏: {self.path}") from exc
        if not isinstance(data, list):
            raise ValueError(f"MCP 用户注册表必须是数组: {self.path}")
        return data

    def _save(self, users: list[dict]) -> None:
        """原子写入用户注册表，避免并发写导致 JSON 损坏。"""
        temp = self.path.with_suffix(f".tmp-{time.time_ns()}")
        temp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temp.replace(self.path)
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """写操作文件锁；Windows 无 fcntl 时退化为单进程锁语义。"""
        self.lock_path.touch(exist_ok=True)
        with self.lock_path.open("w") as lock_file:
            if _FCNTL_AVAILABLE:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if _FCNTL_AVAILABLE:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _ensure_credential_dir(self, user_id: str) -> None:
        """创建并收紧用户凭证目录权限。"""
        path = self.credential_dir(user_id)
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    def _remove_credential_dir(self, user_id: str) -> None:
        """删除用户凭证目录，避免残留可复用登录态。"""
        path = self.credential_dir(user_id)
        if not path.exists():
            return
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()

    def _new_user_id(self, users: list[dict]) -> str:
        """生成不冲突的短用户 ID。"""
        existing = {str(item.get("user_id")) for item in users}
        while True:
            user_id = "u_" + secrets.token_hex(4)
            if user_id not in existing:
                return user_id

    def _new_api_key(self) -> str:
        """生成固定前缀的高熵 API Key（委托给模块级 generate_api_key）。"""
        return generate_api_key()
