"""卖家精灵用户专属账号绑定与加密 SQLite 存储。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from opscli.auth.storage.crypto import Crypto
from opscli.config import CONFIG_DIR
from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.services.account_pool import (
    mask_seller_sprite_username,
    seller_sprite_account_key,
)


DEFAULT_BINDING_DB_PATH = Path(CONFIG_DIR) / "seller_sprite" / "account_bindings.sqlite3"
DEFAULT_BINDING_KEY_PATH = Path(CONFIG_DIR) / "seller_sprite" / ".account_bindings.key"


@dataclass(frozen=True)
class SellerSpriteDedicatedAccount:
    """可用于执行任务的卖家精灵专属账号。"""

    account_id: str
    name: str
    username: str
    password: str

    def to_account(self) -> SellerSpriteAccount:
        """转换为现有卖家精灵执行账号对象。"""
        return SellerSpriteAccount(
            name=self.name,
            username=self.username,
            password=self.password,
        )


@dataclass(frozen=True)
class SellerSpriteAccountBindingReference:
    """不含账号密码、可安全进入额度和任务上下文的绑定引用。"""

    user_email: str
    account_id: str
    account_name: str
    username: str

    @property
    def account_key(self) -> str:
        """返回不含明文凭证的稳定账号键。"""
        return seller_sprite_account_key(
            SellerSpriteAccount(
                name=self.account_name,
                username=self.username,
                password="",
            )
        )


@dataclass(frozen=True)
class SellerSpriteUserAccountBinding:
    """用户邮箱与专属卖家精灵账号的绑定。"""

    user_email: str
    account: SellerSpriteDedicatedAccount
    bound_at: str

    @property
    def account_key(self) -> str:
        """返回不含明文凭证的稳定账号键。"""
        return seller_sprite_account_key(self.account.to_account())

    def to_public_dict(self) -> dict[str, str]:
        """返回不包含账号密码的绑定摘要。"""
        return {
            "user_email": self.user_email,
            "account_id": self.account.account_id,
            "account_name": self.account.name,
            "username": mask_seller_sprite_username(self.account.username),
            "account_key": self.account_key,
            "bound_at": self.bound_at,
        }


class SellerSpriteAccountBindingStore:
    """使用 AES-256-GCM 加密密码的用户专属账号绑定仓储。"""

    def __init__(
        self,
        db_path: str | Path | None = None,
        key_path: str | Path | None = None,
    ) -> None:
        """初始化绑定仓储并确保 SQLite 表结构存在。

        Args:
            db_path: SQLite 文件路径；为空时使用默认配置目录。
            key_path: AES 密钥文件路径；为空时与默认绑定库同目录。
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_BINDING_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path = (
            Path(key_path)
            if key_path
            else self.db_path.parent / DEFAULT_BINDING_KEY_PATH.name
        )
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.crypto = Crypto(self.key_path)
        self._ensure_schema()

    def bind(
        self,
        *,
        user_email: str,
        account_name: str,
        username: str,
        password: str,
    ) -> SellerSpriteUserAccountBinding:
        """新增或更新命名账号，并把用户邮箱绑定到该账号。

        同一用户邮箱只有一个绑定；同一命名账号可以被多个用户复用。更新
        命名账号时会同步更新所有复用该账号的用户所使用的凭证。
        """
        email = _normalize_email(user_email)
        name = _required_text(account_name, "account_name")
        login_username = _required_text(username, "username")
        secret = _required_text(password, "password")
        now = _now_iso()
        encrypted_password = self.crypto.encrypt(secret)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT account_id FROM seller_sprite_dedicated_accounts "
                "WHERE account_name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if row is None:
                account_id = uuid4().hex
                try:
                    conn.execute(
                        """
                        INSERT INTO seller_sprite_dedicated_accounts (
                            account_id, account_name, username, password_ciphertext,
                            created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (account_id, name, login_username, encrypted_password, now, now),
                    )
                except sqlite3.IntegrityError as exc:
                    conn.rollback()
                    raise ValueError("卖家精灵用户名已被其他命名账号使用") from exc
            else:
                account_id = str(row["account_id"])
                try:
                    conn.execute(
                        """
                        UPDATE seller_sprite_dedicated_accounts
                        SET account_name = ?, username = ?, password_ciphertext = ?, updated_at = ?
                        WHERE account_id = ?
                        """,
                        (name, login_username, encrypted_password, now, account_id),
                    )
                except sqlite3.IntegrityError as exc:
                    conn.rollback()
                    raise ValueError("卖家精灵用户名已被其他命名账号使用") from exc

            conn.execute(
                """
                INSERT INTO seller_sprite_user_account_bindings (
                    user_email, account_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_email) DO UPDATE SET
                    account_id = excluded.account_id,
                    updated_at = excluded.updated_at
                """,
                (email, account_id, now, now),
            )
            conn.commit()
        binding = self.get_binding(email)
        if binding is None:
            raise RuntimeError("卖家精灵专属账号绑定写入后无法读取")
        return binding

    def get_binding_reference(
        self,
        user_email: str,
    ) -> SellerSpriteAccountBindingReference | None:
        """按用户邮箱读取不含密码的专属账号绑定引用。"""
        email = _normalize_email(user_email)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT binding.user_email, account.account_id,
                       account.account_name, account.username
                FROM seller_sprite_user_account_bindings AS binding
                JOIN seller_sprite_dedicated_accounts AS account
                  ON account.account_id = binding.account_id
                WHERE binding.user_email = ?
                """,
                (email,),
            ).fetchone()
        if row is None:
            return None
        return SellerSpriteAccountBindingReference(
            user_email=str(row["user_email"]),
            account_id=str(row["account_id"]),
            account_name=str(row["account_name"]),
            username=str(row["username"]),
        )

    def get_binding(self, user_email: str) -> SellerSpriteUserAccountBinding | None:
        """按标准化用户邮箱读取专属账号绑定并解密密码。"""
        email = _normalize_email(user_email)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT binding.user_email, binding.updated_at AS bound_at,
                       account.account_id, account.account_name, account.username,
                       account.password_ciphertext
                FROM seller_sprite_user_account_bindings AS binding
                JOIN seller_sprite_dedicated_accounts AS account
                  ON account.account_id = binding.account_id
                WHERE binding.user_email = ?
                """,
                (email,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_binding(row)

    def get_account(self, account_id: str) -> SellerSpriteDedicatedAccount | None:
        """按内部账号 ID 读取并解密专属账号。"""
        normalized_id = _required_text(account_id, "account_id")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT account_id, account_name, username, password_ciphertext
                FROM seller_sprite_dedicated_accounts
                WHERE account_id = ?
                """,
                (normalized_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_account(row)

    def list_bindings(self) -> list[dict[str, str]]:
        """按用户邮箱列出全部脱敏绑定摘要，列表读取不解密密码。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT binding.user_email, binding.updated_at AS bound_at,
                       account.account_id, account.account_name, account.username
                FROM seller_sprite_user_account_bindings AS binding
                JOIN seller_sprite_dedicated_accounts AS account
                  ON account.account_id = binding.account_id
                ORDER BY binding.user_email
                """
            ).fetchall()
        return [
            {
                "user_email": str(row["user_email"]),
                "account_id": str(row["account_id"]),
                "account_name": str(row["account_name"]),
                "username": mask_seller_sprite_username(str(row["username"])),
                "account_key": SellerSpriteAccountBindingReference(
                    user_email=str(row["user_email"]),
                    account_id=str(row["account_id"]),
                    account_name=str(row["account_name"]),
                    username=str(row["username"]),
                ).account_key,
                "bound_at": str(row["bound_at"]),
            }
            for row in rows
        ]

    def unbind(self, user_email: str) -> bool:
        """解除用户邮箱绑定；复用账号及其他用户绑定保持不变。"""
        email = _normalize_email(user_email)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM seller_sprite_user_account_bindings WHERE user_email = ?",
                (email,),
            )
        return int(cursor.rowcount or 0) == 1

    def _row_to_binding(self, row: sqlite3.Row) -> SellerSpriteUserAccountBinding:
        """将联表查询行转换为绑定对象。"""
        return SellerSpriteUserAccountBinding(
            user_email=str(row["user_email"]),
            bound_at=str(row["bound_at"]),
            account=self._row_to_account(row),
        )

    def _row_to_account(self, row: sqlite3.Row) -> SellerSpriteDedicatedAccount:
        """解密 SQLite 行中的账号密码并构造领域对象。"""
        ciphertext = bytes(row["password_ciphertext"])
        return SellerSpriteDedicatedAccount(
            account_id=str(row["account_id"]),
            name=str(row["account_name"]),
            username=str(row["username"]),
            password=self.crypto.decrypt(ciphertext),
        )

    def _ensure_schema(self) -> None:
        """初始化专属账号与用户绑定表。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_dedicated_accounts (
                    account_id TEXT NOT NULL PRIMARY KEY,
                    account_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_ciphertext BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_user_account_bindings (
                    user_email TEXT NOT NULL COLLATE NOCASE PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id)
                        REFERENCES seller_sprite_dedicated_accounts(account_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_seller_sprite_binding_account "
                "ON seller_sprite_user_account_bindings(account_id)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """创建启用 WAL 与外键约束的 SQLite 连接。"""
        conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _normalize_email(value: str) -> str:
    """标准化并校验用户邮箱。"""
    email = _required_text(value, "user_email").lower()
    if "@" not in email:
        raise ValueError("user_email 不是有效邮箱")
    return email


def _required_text(value: str, field: str) -> str:
    """读取必填文本并拒绝空白值。"""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    return text


def _now_iso() -> str:
    """返回当前本地时区 ISO 时间。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
