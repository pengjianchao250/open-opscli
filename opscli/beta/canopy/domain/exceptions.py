"""beta Canopy API 异常。"""

from __future__ import annotations

from typing import Any


class CanopyError(Exception):
    """Canopy beta 模块基础异常。"""

    code = "CANOPY_ERROR"

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP `_err` 可识别的错误结构。"""
        return {"code": self.code, "message": str(self)}


class CanopyConfigError(CanopyError):
    """Canopy beta 配置错误。"""

    code = "CANOPY_CONFIG_ERROR"


class CanopyApiError(CanopyError):
    """Canopy API 请求错误。"""

    code = "CANOPY_API_ERROR"

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
        if isinstance(self.response_payload, dict):
            for key in ("success", "errors", "error", "message", "code"):
                if key in self.response_payload:
                    error[key] = self.response_payload[key]
        return error
