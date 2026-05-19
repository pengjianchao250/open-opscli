"""凭证存储模块。

采用双层存储策略（铁律5）：
- 优先使用系统 Keychain（macOS 钥匙串 / Linux Secret Service）
- Keychain 不可用时兜底使用 AES-256-GCM 加密文件（credentials.bin）

存储结构（JSON）：
{
    "session_id": "...",          # 登录 session
    "device_code": "...",         # Device Flow 设备码
    "email": "...",               # 用户邮箱
    "session_expires_at": "...",  # session 过期时间（ISO 格式）
    "tokens": {                   # 各系统 JWT
        "<system_key>": {
            "jwt": "...",
            "expires_at": "...",  # JWT 过期时间（ISO 格式）
            "saved_at": 1234567890
        }
    }
}
"""
import json
import logging
import threading
import time
import stat
from datetime import datetime, timezone, timedelta
from pathlib import Path
from cryptography.exceptions import InvalidTag
from opscli.auth.storage.crypto import Crypto

# Keychain 单次操作超时（秒）：超时后自动降级到加密文件，避免命令卡住
_KEYRING_TIMEOUT = 3


def _keyring_call(fn, *args):
    """在 daemon 线程中执行 keyring 操作，超时后放弃并返回 None。

    keyring.get_password / set_password 在 macOS Keychain 弹框或系统挂起时会无限阻塞。
    使用 daemon 线程：超时后主线程继续，被放弃的线程不会阻塞进程退出。
    """
    result: list = [None]
    exc: list = [None]

    def _run():
        try:
            result[0] = fn(*args)
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=_KEYRING_TIMEOUT)
    if t.is_alive():
        # 线程仍在运行，说明 Keychain 操作卡住了，放弃并降级
        return None, "timeout"
    if exc[0] is not None:
        raise exc[0]
    return result[0], "ok"

_logger = logging.getLogger("opscli.auth.storage")

try:
    import keyring
    import keyring.errors
    _KEYRING_AVAILABLE = True
except Exception:
    _KEYRING_AVAILABLE = False

# Keychain 服务名和账户名（铁律5：不可随意更改，否则用户凭证丢失）
_KEYRING_SERVICE = "opscli-auth"
_KEYRING_ACCOUNT = "credentials"


class CredentialStore:
    """凭证存储管理器，负责 session 和 JWT 的持久化读写。

    存储策略：Keychain 优先，AES-256-GCM 加密文件兜底。
    测试环境通过传入 base_dir 参数跳过 Keychain（铁律8）。
    """

    def __init__(self, base_dir: Path | None = None):
        """
        Args:
            base_dir: 存储目录，传入时跳过 Keychain（用于测试），
                      默认使用 CONFIG_DIR（~/.config/opscli/）
        """
        # 仅默认路径启用 Keychain；显式传入 base_dir（如测试）走文件存储
        self._use_keyring = _KEYRING_AVAILABLE and base_dir is None
        from opscli.config import CONFIG_DIR
        self._dir = Path(base_dir or CONFIG_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        if base_dir is not None:
            self._dir.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self._path = self._dir / "credentials.bin"
        self._crypto = Crypto(self._dir / ".key")

    @property
    def base_dir(self) -> Path:
        """返回存储目录路径，供 TokenManager 构建文件锁路径。"""
        return self._dir

    def load(self) -> dict | None:
        """加载凭证数据，返回完整凭证字典或 None（无凭证时）。

        读取优先级：系统 Keychain > AES-256-GCM 加密文件。
        加密文件解密失败（密钥不匹配）时自动清除损坏文件。
        """
        # 优先从系统 Keychain 读取，设置超时防止 Keychain 弹框或挂起时命令卡死
        if self._use_keyring:
            try:
                raw, _status = _keyring_call(keyring.get_password, _KEYRING_SERVICE, _KEYRING_ACCOUNT)
                if _status == "timeout":
                    _logger.debug("Keychain 读取超时（%ds），降级到文件存储", _KEYRING_TIMEOUT)
                elif raw:
                    return json.loads(raw)
            except keyring.errors.NoKeyringError:
                pass
            except Exception as _kr_exc:
                _logger.debug("Keychain 读取失败，降级到文件存储: %s", _kr_exc)

        # 兜底：从加密文件读取
        if not self._path.exists():
            return None
        try:
            return json.loads(self._crypto.decrypt(self._path.read_bytes()))
        except (InvalidTag, Exception):
            # 密钥与密文不匹配（如密钥轮换/环境变更），清除损坏的凭证文件重新开始
            self._path.unlink(missing_ok=True)
            return None

    def _save(self, data: dict):
        """持久化凭证数据，写入 Keychain 或加密文件。"""
        raw = json.dumps(data)
        # 优先写入系统 Keychain，设置超时防止挂起
        if self._use_keyring:
            try:
                _, _status = _keyring_call(keyring.set_password, _KEYRING_SERVICE, _KEYRING_ACCOUNT, raw)
                if _status == "timeout":
                    _logger.debug("Keychain 写入超时（%ds），降级到文件存储", _KEYRING_TIMEOUT)
                else:
                    return
            except keyring.errors.NoKeyringError:
                pass
            except Exception as _kr_exc:
                _logger.debug("Keychain 写入失败，降级到文件存储: %s", _kr_exc)
        self._path.write_bytes(self._crypto.encrypt(raw))
        self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def save_session(
        self,
        session_id: str,
        email: str,
        expires_at: str,
        device_code: str | None = None,
    ):
        """保存登录 session 信息。

        当登录态切换（如重新登录其他账号或新的 session）时，必须清空旧 JWT，
        避免后续请求继续复用上一位用户的缓存 token。
        """
        data = self.load() or {}
        session_changed = (
            (data.get("session_id") and data.get("session_id") != session_id)
            or (data.get("email") and data.get("email") != email)
        )
        data.update({
            "session_id": session_id,
            "email": email,
            "session_expires_at": expires_at,
            "tokens": {} if session_changed else data.get("tokens", {}),
        })
        # device_code 缺失时保留旧值，兼容历史凭证数据
        if device_code is not None:
            data["device_code"] = device_code
        self._save(data)

    def save_token(self, system_key: str, jwt: str, expires_in: int):
        """保存指定系统的 JWT，将 expires_in（秒）转换为 ISO 格式的 expires_at。"""
        data = self.load() or {}
        data.setdefault("tokens", {})
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
        data["tokens"][system_key] = {
            "jwt": jwt,
            "expires_at": expires_at,
            "saved_at": int(time.time()),
        }
        self._save(data)

    def remove_token(self, system_key: str) -> bool:
        """移除指定系统的 JWT 缓存。

        Args:
            system_key: 系统唯一键

        Returns:
            是否成功移除（token 存在且已删除）
        """
        data = self.load() or {}
        tokens = data.get("tokens", {})
        if system_key in tokens:
            del tokens[system_key]
            data["tokens"] = tokens
            self._save(data)
            return True
        return False

    def clear(self):
        # 清除 Keychain
        if self._use_keyring:
            try:
                keyring.delete_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
            except Exception as _kr_exc:
                _logger.debug("Keychain 清除失败（可能无存储记录）: %s", _kr_exc)
        # 清除加密文件
        if self._path.exists():
            self._path.unlink()
