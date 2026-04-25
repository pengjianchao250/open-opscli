"""JWT Token 管理模块。

负责 Token 的获取、缓存、刷新和有效性检测。
采用双层并发锁机制（铁律6）防止多进程/多线程重复获取 JWT：
- Layer 1：threading.Lock（防同进程多线程并发）
- Layer 2：fcntl.flock()（防多 CLI 进程并发，Windows 自动跳过）

Token 生命周期三态：valid / needs_refresh / expired
刷新阈值 REFRESH_THRESHOLD = 300s（距过期 5 分钟内触发）。
"""
import httpx
import threading
from datetime import datetime, timezone, timedelta
from opscli.auth.exceptions import NotAuthenticatedError, TokenFetchError

try:
    import fcntl
    _FCNTL_AVAILABLE = True
except ImportError:
    _FCNTL_AVAILABLE = False  # Windows 不支持 fcntl

# 进程内线程锁：key = system_key
_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_mutex = threading.Lock()


def _get_thread_lock(key: str) -> threading.Lock:
    with _thread_locks_mutex:
        if key not in _thread_locks:
            _thread_locks[key] = threading.Lock()
        return _thread_locks[key]

REFRESH_THRESHOLD = 300   # 距过期 5 分钟内触发刷新（原 30 分钟过于保守）
MAX_JWT_TTL = 86400       # JWT 最大有效期 24 小时（86400 秒）


class TokenManager:
    """JWT Token 管理器，协调凭证存储和系统注册表完成 Token 生命周期管理。"""

    def __init__(self, store, registry):
        """
        Args:
            store: CredentialStore 实例，用于读写凭证
            registry: SystemRegistry 实例，用于查找系统配置
        """
        self._store = store
        self._registry = registry

    def _get_session_id(self) -> str:
        data = self._store.load()
        if not data or not data.get("session_id"):
            raise NotAuthenticatedError("未登录，请运行: opscli auth login")
        exp = datetime.fromisoformat(data["session_expires_at"])
        # 无时区信息时视为 UTC
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise NotAuthenticatedError("登录已过期，请重新运行: opscli auth login")
        return data["session_id"]

    def get_session_id(self) -> str:
        """返回当前有效 session_id。

        对外暴露公共接口，避免 SDK 直接依赖私有实现细节。
        """
        return self._get_session_id()

    def token_status(self, token_data: dict) -> str:
        """返回 Token 三态：valid / needs_refresh / expired"""
        try:
            exp = datetime.fromisoformat(token_data["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            remaining = (exp - datetime.now(timezone.utc)).total_seconds()
            if remaining > REFRESH_THRESHOLD:
                return "valid"
            if remaining > 0:
                return "needs_refresh"
            return "expired"
        except (KeyError, ValueError):
            return "expired"

    def _is_valid(self, token_data: dict) -> bool:
        """判断 Token 是否处于 valid 状态（无需刷新）。"""
        return self.token_status(token_data) == "valid"

    def _fetch_token(self, system_key: str, url: str, endpoint: str) -> str:
        """向后端请求新的 JWT 并保存到凭证存储。"""
        session_id = self.get_session_id()
        try:
            resp = httpx.post(
                f"{url}{endpoint}",
                json={"session_id": session_id},
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()
            # 后端返回的 expires_in 可能超出合理范围，限制为最大 24 小时
            expires_in = min(body.get("expires_in", 7200), MAX_JWT_TTL)
            self._store.save_token(system_key, body["jwt"], expires_in)
            return body["jwt"]
        except httpx.HTTPStatusError as e:
            raise TokenFetchError(f"获取 {system_key} JWT 失败: {e.response.status_code}")
        except Exception as e:
            raise TokenFetchError(f"获取 {system_key} JWT 异常: {e}")

    def get_token(self, alias: str) -> str:
        sys = self._registry.get(alias)
        system_key = sys["system_key"]

        # 层1：进程内线程锁，防止同进程多线程并发重复换取
        thread_lock = _get_thread_lock(system_key)
        with thread_lock:
            # 双重检查：可能其他线程已完成刷新
            data = self._store.load() or {}
            td = data.get("tokens", {}).get(system_key)
            if td and self._is_valid(td):
                return td["jwt"]

            # 层2：跨进程文件锁，防止多个 CLI 进程并发重复换取
            if _FCNTL_AVAILABLE:
                lock_path = self._store.base_dir / f".lock_{system_key}"
                with open(lock_path, "w") as lf:
                    try:
                        fcntl.flock(lf, fcntl.LOCK_EX)
                        # 再次双重检查：其他进程可能已完成刷新
                        data = self._store.load() or {}
                        td = data.get("tokens", {}).get(system_key)
                        if td and self._is_valid(td):
                            return td["jwt"]
                        return self._fetch_token(system_key, sys["url"], sys["token_endpoint"])
                    finally:
                        fcntl.flock(lf, fcntl.LOCK_UN)
            else:
                return self._fetch_token(system_key, sys["url"], sys["token_endpoint"])

    def check_token(self, alias: str) -> dict:
        """检查指定系统 Token 有效性，返回 {valid: bool, expires_in: int}。"""
        sys = self._registry.get(alias)
        data = self._store.load() or {}
        td = data.get("tokens", {}).get(sys["system_key"])
        if not td:
            return {"valid": False, "expires_in": 0}
        try:
            exp = datetime.fromisoformat(td["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            rem = int((exp - datetime.now(timezone.utc)).total_seconds())
            return {"valid": rem > 0, "expires_in": max(0, rem)}
        except (KeyError, ValueError):
            return {"valid": False, "expires_in": 0}

    def refresh_token(self, alias: str) -> str:
        """强制刷新指定系统的 JWT（忽略缓存有效期）。"""
        sys = self._registry.get(alias)
        return self._fetch_token(sys["system_key"], sys["url"], sys["token_endpoint"])

    def refresh_all(self) -> dict:
        """刷新所有已注册系统的 JWT，返回 {alias: "ok"/"失败: 原因"} 字典。"""
        results = {}
        for sys in self._registry.list_all():
            try:
                self._fetch_token(sys["system_key"], sys["url"], sys["token_endpoint"])
                results[sys["alias"]] = "ok"
            except Exception as e:
                results[sys["alias"]] = f"失败: {e}"
        return results

    def get_token_by_session(self, session_id: str, alias: str) -> str:
        """无状态模式：使用外部传入的 session_id 直接向后端请求 JWT。

        不读取本地 CredentialStore，也不保存返回的 JWT。
        适用于远程共享 MCP 服务器场景，由调用方自行管理凭证。

        Args:
            session_id: 用户登录后获得的 session_id
            alias: 系统别名（如 ops、polaris）

        Returns:
            JWT 字符串

        Raises:
            TokenFetchError: 后端请求失败
        """
        sys = self._registry.get(alias)
        try:
            resp = httpx.post(
                f"{sys['url']}{sys['token_endpoint']}",
                json={"session_id": session_id},
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()
            return body["jwt"]
        except httpx.HTTPStatusError as e:
            raise TokenFetchError(f"获取 {alias} JWT 失败: {e.response.status_code}")
        except Exception as e:
            raise TokenFetchError(f"获取 {alias} JWT 异常: {e}")
