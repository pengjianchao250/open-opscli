"""Xiyou domain exceptions."""

from __future__ import annotations


class XiyouError(Exception):
    """Base exception for Xiyou module."""

    code = "XIYOU_ERROR"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class XiyouConfigError(XiyouError):
    """Invalid user input or unsupported local configuration."""

    code = "XIYOU_CONFIG_ERROR"


class XiyouApiError(XiyouError):
    """HTTP/API request failure."""

    code = "XIYOU_API_ERROR"

    def __init__(self, message: str, *, status_code: int | None = None, response_excerpt: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_excerpt = response_excerpt

    def to_dict(self) -> dict[str, object]:
        error: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.status_code is not None:
            error["status_code"] = self.status_code
        if self.response_excerpt:
            error["response_excerpt"] = self.response_excerpt
        return error


class XiyouCredentialExpiredError(XiyouError):
    """Xiyou business credential has expired and needs operator refresh."""

    code = "XIYOU_CREDENTIAL_EXPIRED"

    def __init__(
        self,
        message: str = (
            "西柚凭据已过期，已发送企微补登通知，请等待运维在运营后台补登后重试。"
        ),
        *,
        reason: str,
        expires_at: str | None = None,
        notify_result: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.expires_at = expires_at
        self.notify_result = notify_result or {}

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "auth_system": "xiyou",
            "retryable": False,
            "terminal": True,
            "reason": self.reason,
            "expires_at": self.expires_at,
            "notify_result": self.notify_result,
            "user_action": "等待运维在运营系统后台补登西柚 token/cookie 后，再重新发起西柚任务。",
            "agent_action": (
                "停止当前西柚任务，不要调用 auth_mcp_login/auth_get_token/auth_token_refresh；"
                "这些工具只刷新 OPS 登录，不能修复西柚凭据。"
            ),
            "do_not_call_tools": ["auth_mcp_login", "auth_get_token", "auth_token_refresh"],
        }


class XiyouUnsupportedExportError(XiyouError):
    """The Xiyou website has no official export API for this scenario."""

    code = "XIYOU_UNSUPPORTED_EXPORT"

    def __init__(
        self,
        message: str = (
            "西柚官方暂未提供该场景的下载接口，请停止当前下载任务，不要继续尝试其他导出路径。"
        ),
        *,
        function: str,
    ) -> None:
        super().__init__(message)
        self.function = function

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "function": self.function,
            "retryable": False,
            "terminal": True,
            "next_action": "STOP_AND_WAIT_FOR_OFFICIAL_DOWNLOAD_API",
            "user_action": "西柚官方当前未开放该场景下载接口，请勿继续尝试下载，等待官方后续支持。",
            "agent_action": "立即停止当前任务，不要重试，不要切换其他接口或推测替代下载路径。",
        }
