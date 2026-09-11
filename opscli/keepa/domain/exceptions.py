"""Keepa API 模块异常。"""

from __future__ import annotations

import math
from typing import Any


class KeepaError(Exception):
    """Keepa 模块基础异常。"""

    code = "KEEPA_ERROR"

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        return {"code": self.code, "message": str(self)}


class KeepaConfigError(KeepaError):
    """Keepa 配置错误。"""

    code = "KEEPA_CONFIG_ERROR"


class KeepaQuotaError(KeepaConfigError):
    """Keepa 可用 token 不足，调用方可根据重试时间稍后重试。"""

    code = "KEEPA_QUOTA_INSUFFICIENT"

    def __init__(
        self,
        message: str,
        *,
        tokens_left: int | None = None,
        estimated_tokens: int | None = None,
        reserve_tokens: int | None = None,
        refill_in_ms: int | float | None = None,
        refill_rate: int | float | None = None,
    ) -> None:
        super().__init__(message)
        self.tokens_left = tokens_left
        self.estimated_tokens = estimated_tokens
        self.reserve_tokens = reserve_tokens
        self.refill_in_ms = refill_in_ms
        self.refill_rate = refill_rate

    @property
    def retry_after_seconds(self) -> int | None:
        """返回建议的最短重试等待秒数。"""
        if self.refill_in_ms is None:
            return None
        try:
            return max(1, math.ceil(float(self.refill_in_ms) / 1000.0) + 1)
        except (TypeError, ValueError):
            return None

    def to_dict(self) -> dict[str, Any]:
        """转换为稳定的 MCP 错误信封。"""
        error = super().to_dict()
        quota = {
            "tokens_left": self.tokens_left,
            "estimated_tokens": self.estimated_tokens,
            "reserve_tokens": self.reserve_tokens,
            "refill_in_ms": self.refill_in_ms,
            "refill_rate": self.refill_rate,
            "retry_after_seconds": self.retry_after_seconds,
        }
        error.update({key: value for key, value in quota.items() if value is not None})
        return error


class KeepaApiError(KeepaError):
    """Keepa API 请求错误。"""

    code = "KEEPA_API_ERROR"

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
        self.code = _classify_api_error(status_code, response_payload)

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        error: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.status_code is not None:
            error["status_code"] = self.status_code
        if self.response_payload:
            for key in ("tokensLeft", "refillIn", "refillRate", "tokensConsumed", "error"):
                if key in self.response_payload:
                    error[key] = self.response_payload[key]
        if self.response_excerpt:
            error["response_excerpt"] = self.response_excerpt
        return error


def _classify_api_error(status_code: int | None, payload: dict[str, Any] | None) -> str:
    """把 Keepa HTTP/业务错误映射为稳定的调用方错误码。"""
    if status_code == 401:
        return "KEEPA_AUTH_ERROR"
    if status_code == 403:
        return "KEEPA_FORBIDDEN"
    if status_code == 429:
        return "KEEPA_RATE_LIMITED"

    text = str(payload or {}).lower()
    if any(marker in text for marker in ("invalid key", "key is invalid", "unauthorized")):
        return "KEEPA_AUTH_ERROR"
    if any(marker in text for marker in ("token", "quota", "insufficient credit")):
        return "KEEPA_QUOTA_INSUFFICIENT"
    if any(marker in text for marker in ("rate limit", "too many request", "throttle")):
        return "KEEPA_RATE_LIMITED"
    return "KEEPA_API_ERROR"
