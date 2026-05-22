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


class SellerSpriteApiError(SellerSpriteError):
    """卖家精灵接口请求错误。"""

    code = "SELLER_SPRITE_API_ERROR"

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
