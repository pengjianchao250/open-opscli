"""西柚洞察接口直连异常。"""

from __future__ import annotations


class XiyouError(Exception):
    """西柚洞察模块基础异常。"""

    code = "XIYOU_ERROR"

    def to_dict(self) -> dict[str, str]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        return {"code": self.code, "message": str(self)}


class XiyouConfigError(XiyouError):
    """西柚洞察配置错误。"""

    code = "XIYOU_CONFIG_ERROR"


class XiyouApiError(XiyouError):
    """西柚洞察接口请求错误。"""

    code = "XIYOU_API_ERROR"

    def __init__(self, message: str, *, status_code: int | None = None, response_excerpt: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_excerpt = response_excerpt

    def to_dict(self) -> dict[str, object]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        error: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.status_code is not None:
            error["status_code"] = self.status_code
        if self.response_excerpt:
            error["response_excerpt"] = self.response_excerpt
        return error


class XiyouCredentialExpiredError(XiyouError):
    """西柚业务凭据已失效，需要运维补登。"""

    code = "XIYOU_CREDENTIAL_EXPIRED"

    def __init__(
        self,
        message: str = "西柚凭据已过期，已发送企微补登通知，请等待运维在运营后台补登后重试。",
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
        """转换为 MCP `_err` 可识别的终态错误结构。"""
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
            "agent_action": "停止当前西柚任务，不要调用 auth_mcp_login/auth_get_token/auth_token_refresh；这些工具只刷新 OPS 登录，不能修复西柚凭据。",
            "do_not_call_tools": ["auth_mcp_login", "auth_get_token", "auth_token_refresh"],
        }
