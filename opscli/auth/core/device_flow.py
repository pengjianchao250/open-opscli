"""OAuth2 Device Flow 授权模块（RFC 8628）。

实现 CLI 场景下的设备授权流程：
1. 向后端请求设备码（device_code）和验证 URL
2. 用户在浏览器中打开验证 URL 并输入验证码
3. CLI 以固定间隔轮询后端，等待用户完成授权
4. 授权成功后自动保存 session 到本地凭证存储
"""
import time
import httpx
from opscli.auth.exceptions import DeviceFlowExpiredError, DeviceFlowDeniedError


class DeviceFlow:
    """OAuth2 Device Flow 授权器，管理设备码获取与轮询等待。"""

    def __init__(self, ops_url: str, store):
        """
        Args:
            ops_url: 运营系统后端地址（如 https://ops.aukeys.com）
            store: CredentialStore 实例，用于授权成功后持久化 session
        """
        self._url = ops_url.rstrip("/")
        self._store = store

    def request_device_code(self) -> dict:
        """向后端请求设备码和验证信息。

        Returns:
            dict: 包含 device_code、user_code、verification_url、expires_in 等字段
        """
        resp = httpx.post(f"{self._url}/v1/cli/device/code", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def poll(self, device_code: str, interval: int = 3, max_wait: int = 300) -> dict:
        """轮询后端等待用户完成授权。

        以 interval 为间隔持续轮询，直到用户授权、拒绝或超时。
        授权成功后自动调用 store.save_session() 持久化凭证。

        Args:
            device_code: 设备码，由 request_device_code() 返回
            interval: 轮询间隔（秒），默认 3 秒，由后端返回的值决定
            max_wait: 最大等待时间（秒），默认 300 秒（5 分钟）

        Returns:
            dict: 包含 session_id、email、expires_at 等授权信息

        Raises:
            DeviceFlowExpiredError: 设备码超时或等待超时
            DeviceFlowDeniedError: 用户在浏览器中拒绝授权
        """
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(interval)
            elapsed += interval
            resp = httpx.get(
                f"{self._url}/v1/cli/device/poll",
                params={"device_code": device_code},
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()
            status = body.get("status")
            if status == "authorized":
                # 授权成功，保存 session 到本地凭证存储
                self._store.save_session(
                    body["session_id"],
                    body.get("email", ""),
                    body.get("expires_at", ""),
                    device_code=device_code,
                )
                return body
            elif status == "expired":
                raise DeviceFlowExpiredError("设备码已超时，请重新运行: opscli auth login")
            elif status == "denied":
                raise DeviceFlowDeniedError("用户拒绝授权")
        # 超过最大等待时间仍未授权
        raise DeviceFlowExpiredError("等待超时，请重新运行: opscli auth login")
