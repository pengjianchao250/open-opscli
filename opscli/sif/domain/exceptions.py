"""Sif 平台异常。"""

from __future__ import annotations


class SifError(Exception):
    """Sif 基础异常。"""

    code = "SIF_ERROR"

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": str(self)}


class SifLoginRequiredError(SifError):
    """缺少登录态。"""

    code = "SIF_LOGIN_REQUIRED"


class SifLoginError(SifError):
    """Sif 账号密码登录失败。"""

    code = "SIF_LOGIN_FAILED"


class SifConfigError(SifError):
    """Sif 本地或集成配置错误。"""

    code = "SIF_CONFIG_ERROR"


class SifApiRequestError(SifError):
    """Sif API 请求失败。"""

    code = "SIF_API_REQUEST_FAILED"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_excerpt: str | None = None,
        request_payload: dict[str, object] | None = None,
        request_query: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_excerpt = response_excerpt
        self.request_payload = request_payload
        self.request_query = request_query

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.response_excerpt:
            payload["response_excerpt"] = self.response_excerpt
        if self.request_payload is not None:
            payload["request_payload"] = self.request_payload
        if self.request_query is not None:
            payload["request_query"] = self.request_query
        return payload


class SifDownloadError(SifError):
    """Sif XLSX 下载失败。"""

    code = "SIF_DOWNLOAD_FAILED"


class SifNormalizeError(SifError):
    """Sif 响应规范化失败。"""

    code = "SIF_NORMALIZE_FAILED"
