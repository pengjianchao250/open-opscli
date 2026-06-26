"""asin_review 模块异常定义。"""

from __future__ import annotations

from opscli.shared.exceptions import RemoteError


class AsinReviewError(RemoteError):
    """asin_review 模块统一异常基类。"""

    code = "ASIN_REVIEW_ERROR"


class InvalidParamsError(AsinReviewError):
    """请求参数不合法。"""

    code = "INVALID_PARAMS"


class ReviewHttpError(AsinReviewError):
    """远端 HTTP 请求失败。"""

    code = "REVIEW_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class ReviewBusinessError(AsinReviewError):
    """远端业务层返回失败。"""

    code = "REVIEW_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class ReviewBadJsonError(AsinReviewError):
    """远端返回非法 JSON。"""

    code = "REVIEW_BAD_JSON"
