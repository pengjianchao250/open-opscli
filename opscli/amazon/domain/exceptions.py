"""amazon 模块异常定义。"""

from __future__ import annotations

from opscli.shared.exceptions import RemoteError


class AmazonError(RemoteError):
    """amazon 模块统一异常基类。"""

    code = "AMAZON_ERROR"


class InvalidAsinError(AmazonError):
    """ASIN 参数不合法。"""

    code = "INVALID_ASIN"


class ScraperDependencyError(AmazonError):
    """抓取依赖未安装。"""

    code = "SCRAPER_DEPENDENCY_ERROR"


class SubmissionConfigError(AmazonError):
    """提交配置缺失或不合法。"""

    code = "SUBMISSION_CONFIG_ERROR"


class RemoteHttpError(AmazonError):
    """远端 HTTP 请求失败。"""

    code = "REMOTE_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class RemoteBusinessError(AmazonError):
    """远端业务错误。"""

    code = "REMOTE_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class BadRemoteJsonError(AmazonError):
    """远端返回非法 JSON。"""

    code = "BAD_REMOTE_JSON"
