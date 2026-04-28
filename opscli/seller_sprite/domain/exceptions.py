"""卖家精灵模块异常定义。"""

from __future__ import annotations


class SellerSpriteError(Exception):
    """卖家精灵模块统一异常基类。"""

    code = "SELLER_SPRITE_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict:
        """转换为 CLI 统一错误输出结构。"""
        return {
            "code": self.code,
            "message": self.message,
        }


class InvalidAsinError(SellerSpriteError):
    """ASIN 参数不合法。"""

    code = "SELLER_SPRITE_INVALID_ASIN"


class InvalidCollectOptionError(SellerSpriteError):
    """采集参数不合法。"""

    code = "SELLER_SPRITE_INVALID_COLLECT_OPTION"


class SellerSpriteDependencyError(SellerSpriteError):
    """采集依赖未安装。"""

    code = "SELLER_SPRITE_DEPENDENCY_ERROR"


class SellerSpriteCaptchaRequiredError(SellerSpriteError):
    """页面触发验证码，需要人工或打码服务处理。"""

    code = "SELLER_SPRITE_CAPTCHA_REQUIRED"


class SellerSpriteLoginRequiredError(SellerSpriteError):
    """页面未登录，需要先建立卖家精灵登录态。"""

    code = "SELLER_SPRITE_LOGIN_REQUIRED"


class SellerSpriteResponseError(SellerSpriteError):
    """卖家精灵接口响应缺失或结构不符合预期。"""

    code = "SELLER_SPRITE_RESPONSE_ERROR"
