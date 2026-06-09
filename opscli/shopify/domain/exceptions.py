"""Shopify 刊登异常体系。"""


class ShopifyError(Exception):
    """Shopify 模块基础异常。"""

    code = "SHOPIFY_ERROR"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class ShopifyAuthError(ShopifyError):
    """认证失败（未登录 polaris）。"""

    code = "SHOPIFY_AUTH_ERROR"


class ShopifyNotFoundError(ShopifyError):
    """商品或店铺未找到。"""

    code = "SHOPIFY_NOT_FOUND"


class ShopifyParamsError(ShopifyError):
    """参数错误（缺少必要字段）。"""

    code = "SHOPIFY_PARAMS_ERROR"


class ShopifyTaskError(ShopifyError):
    """工单提交失败。"""

    code = "SHOPIFY_TASK_ERROR"
