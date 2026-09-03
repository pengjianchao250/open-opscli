"""佰易产品信息查询异常定义。"""

from __future__ import annotations

from opscli.shared.exceptions import RemoteError


class BaiyiProductInfoError(RemoteError):
    """佰易产品信息查询统一异常基类。"""

    code = "BAIYI_PRODUCT_INFO_ERROR"


class InvalidBaiyiCompanySkuError(BaiyiProductInfoError):
    """公司 SKU 输入不合法。"""

    code = "INVALID_BAIYI_COMPANY_SKU"


class BaiyiProductInfoBadJsonError(BaiyiProductInfoError):
    """远端 JSON 或 data 结构不合法。"""

    code = "BAIYI_PRODUCT_INFO_BAD_JSON"


class BaiyiProductInfoHttpError(BaiyiProductInfoError):
    """佰易产品信息接口返回 HTTP 错误。"""

    code = "BAIYI_PRODUCT_INFO_HTTP_ERROR"

    def __init__(self, status_code: int, message: str) -> None:
        """保存 HTTP 状态码与错误消息。"""
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        """序列化 HTTP 错误并保留状态码。"""
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class BaiyiProductInfoBusinessError(BaiyiProductInfoError):
    """佰易产品信息接口返回业务错误。"""

    code = "BAIYI_PRODUCT_INFO_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str) -> None:
        """保存业务状态码与错误消息。"""
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        """序列化业务错误并保留业务码。"""
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class BaiyiProductInfoNetworkError(BaiyiProductInfoError):
    """佰易产品信息接口发生超时或连接错误。"""

    code = "BAIYI_PRODUCT_INFO_NETWORK_ERROR"
