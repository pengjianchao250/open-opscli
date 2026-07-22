"""Google Trends 模块异常。"""

from __future__ import annotations

from typing import Any


class GoogleTrendsError(Exception):
    """Google Trends 模块基础异常。"""

    code = "GOOGLE_TRENDS_ERROR"

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        return {"code": self.code, "message": str(self)}


class GoogleTrendsConfigError(GoogleTrendsError):
    """Google Trends 配置错误。"""

    code = "GOOGLE_TRENDS_CONFIG_ERROR"


class GoogleTrendsApiKeysExhaustedError(GoogleTrendsError):
    """全部 SerpApi API Key 均不可用或已耗尽。"""

    code = "GOOGLE_TRENDS_API_KEYS_EXHAUSTED"


class GoogleTrendsApiError(GoogleTrendsError):
    """Google Trends API 请求错误。"""

    code = "GOOGLE_TRENDS_API_ERROR"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_excerpt: str | None = None,
        response_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_excerpt = response_excerpt
        self.response_payload = response_payload

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        error: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.status_code is not None:
            error["status_code"] = self.status_code
        if self.response_excerpt:
            error["response_excerpt"] = self.response_excerpt
        if self.response_payload:
            error["response_payload"] = self.response_payload
        return error
