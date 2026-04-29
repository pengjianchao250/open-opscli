"""query 模块异常定义。"""

from __future__ import annotations

from opscli.shared.exceptions import RemoteError


class QueryError(RemoteError):
    """query 模块统一异常基类。"""

    code = "QUERY_ERROR"


class InvalidPayloadError(QueryError):
    """请求 payload 不合法。"""

    code = "INVALID_PAYLOAD"


class DatasetNotFoundError(QueryError):
    """本地 metadata 中找不到目标数据集。"""

    code = "DATASET_NOT_FOUND"


class QueryMetadataNotReadyError(QueryError):
    """本地 query metadata 尚未准备好。"""

    code = "QUERY_METADATA_NOT_READY"


class RemoteHttpError(QueryError):
    """远端 HTTP 请求失败。"""

    code = "REMOTE_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class RemoteBusinessError(QueryError):
    """远端业务层返回失败。"""

    code = "REMOTE_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class BadRemoteJsonError(QueryError):
    """远端返回非法 JSON。"""

    code = "BAD_REMOTE_JSON"
