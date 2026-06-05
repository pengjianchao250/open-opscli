from pathlib import Path

from opscli.config import __version__
from opscli.auth.storage.credential_store import CredentialStore
from opscli.auth.core.system_registry import SystemRegistry
from opscli.auth.core.token_manager import TokenManager
from opscli.auth.config import get_builtin_systems, get_ops_url

# 从配置文件读取，不存在则使用默认值（生产环境）
BUILTIN_SYSTEMS = get_builtin_systems()
OPS_URL = get_ops_url()


class AuthClient:
    """供 Skill/Python 代码调用的 SDK 入口"""

    def __init__(self, base_dir: Path | None = None):
        self._store = CredentialStore(base_dir=base_dir)
        self._registry = SystemRegistry(
            base_dir=base_dir,
            builtin_systems=BUILTIN_SYSTEMS,
        )
        self._tm = TokenManager(store=self._store, registry=self._registry)

    def get_token(self, alias: str) -> str:
        """获取指定系统的有效 JWT（自动刷新）"""
        return self._tm.get_token(alias)

    def get_session(self, alias: str | None = None) -> str:
        """获取当前登录态对应的 session_id。

        参数 `alias` 当前仅用于保持调用语义与 `get_token(alias)` 一致，
        session 本身为全局登录态，不区分具体业务系统。
        """
        _ = alias
        return self._tm.get_session_id()

    def get_device_code(self) -> str | None:
        """获取当前登录态对应的 device_code。"""
        data = self._store.load() or {}
        return data.get("device_code")

    def build_request_auth(self, alias: str) -> tuple[dict[str, str], dict[str, str]]:
        """构造统一请求认证参数。

        当前统一返回：
        - Authorization Bearer JWT
        - X-Opscli-Version opscli 版本号（供服务端判断是否需要提示升级）
        - polarisUserToken session cookie
        - opscliDeviceCode cookie（若本地已保存）
        """
        token = self.get_token(alias)
        session_id = self.get_session(alias)
        headers = {"Authorization": f"Bearer {token}", "X-Opscli-Version": __version__}
        cookies = {"polarisUserToken": session_id}
        device_code = self.get_device_code()
        if device_code:
            cookies["opscliDeviceCode"] = device_code
        return headers, cookies

    def build_session_headers(self, alias: str | None = None) -> dict[str, str]:
        """构造基于 session 的请求头。"""
        return {"X-Session-Id": self.get_session(alias)}

    def check_token(self, alias: str) -> dict:
        """检测指定系统 token 是否有效，返回 {valid, expires_in}"""
        return self._tm.check_token(alias)

    def is_authenticated(self) -> bool:
        """是否已登录（session_id 存在且未过期）"""
        try:
            self._tm.get_session_id()
            return True
        except Exception:
            return False

    def refresh_token(self, alias: str) -> str:
        """强制刷新指定系统 JWT"""
        return self._tm.refresh_token(alias)

    def get_token_by_session(self, session_id: str, alias: str) -> str:
        """无状态模式：用外部 session_id 直接向后端请求 JWT，不读取本地存储。"""
        return self._tm.get_token_by_session(session_id, alias)

    def build_request_auth_with_session(
        self, session_id: str, jwt: str | None = None, alias: str = "ops"
    ) -> tuple[dict[str, str], dict[str, str]]:
        """无状态模式：用外部传入的 session_id 和 jwt 构造请求头。

        如果 jwt 未提供，会自动用 session_id 向后端换取。
        """
        if jwt is None:
            jwt = self.get_token_by_session(session_id, alias)
        headers = {"Authorization": f"Bearer {jwt}", "X-Opscli-Version": __version__}
        cookies = {"polarisUserToken": session_id}
        device_code = self.get_device_code()
        if device_code:
            cookies["opscliDeviceCode"] = device_code
        return headers, cookies


__all__ = ["AuthClient", "BUILTIN_SYSTEMS", "OPS_URL"]
