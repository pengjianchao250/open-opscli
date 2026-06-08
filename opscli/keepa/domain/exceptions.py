"""Keepa API 模块异常。"""

from __future__ import annotations

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
