"""feedback 模块异常定义。"""

from __future__ import annotations

from opscli.shared.exceptions import RemoteError


class FeedbackError(RemoteError):
    """feedback 模块统一异常基类。"""

    code = "FEEDBACK_ERROR"


class InvalidPayloadError(FeedbackError):
    """反馈 payload 不合法。"""

    code = "INVALID_PAYLOAD"


class RemoteHttpError(FeedbackError):
    """远端 HTTP 请求失败。"""

    code = "REMOTE_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class RemoteBusinessError(FeedbackError):
    """远端业务层返回失败。"""

    code = "REMOTE_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class BadRemoteJsonError(FeedbackError):
    """远端返回非法 JSON。"""

    code = "BAD_REMOTE_JSON"


class InsightConfigError(FeedbackError):
    """反馈洞察模型配置不合法。"""

    code = "INSIGHT_CONFIG_ERROR"


class InsightModelError(FeedbackError):
    """反馈洞察模型调用或响应不合法。"""

    code = "INSIGHT_MODEL_ERROR"
