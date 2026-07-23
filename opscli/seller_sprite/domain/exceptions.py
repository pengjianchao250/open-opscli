"""卖家精灵接口直连异常。"""

from __future__ import annotations


class SellerSpriteError(Exception):
    """卖家精灵模块基础异常。"""

    code = "SELLER_SPRITE_ERROR"

    def to_dict(self) -> dict[str, str]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        return {"code": self.code, "message": str(self)}


class SellerSpriteConfigError(SellerSpriteError):
    """卖家精灵配置错误。"""

    code = "SELLER_SPRITE_CONFIG_ERROR"


class SellerSpriteAccountUnavailableError(SellerSpriteError):
    """工作账号失效且没有可用备用账号。"""

    code = "SELLER_SPRITE_ACCOUNT_UNAVAILABLE"


class SellerSpriteTaskTimeoutError(SellerSpriteError):
    """卖家精灵任务超过允许的最长执行时间。"""

    code = "SELLER_SPRITE_TASK_TIMEOUT"


class SellerSpriteApiError(SellerSpriteError):
    """卖家精灵接口请求错误。"""

    code = "SELLER_SPRITE_API_ERROR"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_excerpt: str | None = None,
        api_code: str | None = None,
        api_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_excerpt = response_excerpt
        self.api_code = api_code
        self.api_message = api_message

    def is_session_expired(self) -> bool:
        """判断是否为卖家精灵会话过期类错误。"""
        return self.api_code in {"ERR_GLOBAL_SESSION_EXPIRED"}

    def to_dict(self) -> dict[str, object]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        error: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.status_code is not None:
            error["status_code"] = self.status_code
        if self.api_code:
            error["api_code"] = self.api_code
        if self.api_message:
            error["api_message"] = self.api_message
        if self.response_excerpt:
            error["response_excerpt"] = self.response_excerpt
        return error


class SellerSpriteAuthenticationError(SellerSpriteApiError):
    """卖家精灵账号凭证未通过登录认证。"""

    code = "SELLER_SPRITE_AUTHENTICATION_ERROR"
