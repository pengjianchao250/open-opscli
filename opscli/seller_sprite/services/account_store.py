"""卖家精灵账号凭据存储。"""

from __future__ import annotations

import json
import stat
from pathlib import Path

from opscli.config import CONFIG_DIR
from opscli.seller_sprite.domain.exceptions import InvalidCollectOptionError, SellerSpriteDependencyError

try:
    import keyring
    import keyring.errors

    _KEYRING_AVAILABLE = True
except Exception:
    _KEYRING_AVAILABLE = False


_KEYRING_SERVICE = "opscli-seller-sprite"


class SellerSpriteAccountStore:
    """保存卖家精灵账号名与用户名，密码存入系统凭据管理器。"""

    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir or CONFIG_DIR) / "seller_sprite"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.base_dir / "accounts.json"

    def save(self, *, name: str, username: str, password: str) -> dict:
        """保存命名账号。"""
        self._validate_name(name)
        if not username:
            raise InvalidCollectOptionError("必须提供卖家精灵用户名")
        if not password:
            raise InvalidCollectOptionError("必须提供卖家精灵密码")
        self._set_password(name, password)
        accounts = self._load_accounts()
        accounts[name] = {"username": username}
        self._save_accounts(accounts)
        return {"name": name, "username": username}

    def list(self) -> list[dict]:
        """列出已保存账号，不返回密码。"""
        accounts = self._load_accounts()
        return [{"name": name, "username": item.get("username")} for name, item in accounts.items()]

    def delete(self, *, name: str) -> bool:
        """删除命名账号。"""
        self._validate_name(name)
        accounts = self._load_accounts()
        existed = name in accounts
        if existed:
            del accounts[name]
            self._save_accounts(accounts)
        self._delete_password(name)
        return existed

    def get(self, *, name: str) -> dict:
        """读取命名账号和密码。"""
        self._validate_name(name)
        accounts = self._load_accounts()
        account = accounts.get(name)
        if not account:
            raise InvalidCollectOptionError(f"卖家精灵账号 `{name}` 不存在，请先执行 account save")
        password = self._get_password(name)
        if not password:
            raise InvalidCollectOptionError(f"卖家精灵账号 `{name}` 缺少密码，请重新执行 account save")
        return {
            "name": name,
            "username": account.get("username"),
            "password": password,
        }

    def _load_accounts(self) -> dict:
        """读取账号元数据。"""
        if not self.meta_path.exists():
            return {}
        try:
            payload = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_accounts(self, accounts: dict) -> None:
        """保存账号元数据。"""
        self.meta_path.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
        self.meta_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def _validate_name(self, name: str) -> None:
        """校验账号别名。"""
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise InvalidCollectOptionError("账号名称只能包含字母、数字、下划线和中划线")

    def _keyring_account(self, name: str) -> str:
        """生成 keyring account。"""
        return f"account:{name}"

    def _require_keyring(self):
        """获取 keyring 模块。"""
        if not _KEYRING_AVAILABLE:
            raise SellerSpriteDependencyError("当前环境缺少 keyring，无法安全保存卖家精灵密码")
        return keyring

    def _set_password(self, name: str, password: str) -> None:
        """写入系统凭据管理器。"""
        kr = self._require_keyring()
        try:
            kr.set_password(_KEYRING_SERVICE, self._keyring_account(name), password)
        except keyring.errors.NoKeyringError as exc:
            raise SellerSpriteDependencyError("当前系统 keyring 不可用，无法安全保存卖家精灵密码") from exc

    def _get_password(self, name: str) -> str | None:
        """读取系统凭据管理器密码。"""
        kr = self._require_keyring()
        try:
            return kr.get_password(_KEYRING_SERVICE, self._keyring_account(name))
        except keyring.errors.NoKeyringError as exc:
            raise SellerSpriteDependencyError("当前系统 keyring 不可用，无法读取卖家精灵密码") from exc

    def _delete_password(self, name: str) -> None:
        """删除系统凭据管理器密码。"""
        if not _KEYRING_AVAILABLE:
            return
        try:
            keyring.delete_password(_KEYRING_SERVICE, self._keyring_account(name))
        except Exception:
            pass
