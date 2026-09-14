"""REST API 统一错误信封与异常映射。

所有端点的失败响应都是同一形态：`{"success": false, "data": null,
"error": {"code", "message"}}` + 语义化 HTTP 状态码，与 MCP 工具的
success/data/error 结构保持一致，调用方无需为每种端点学一套错误格式。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from opscli.query.domain.exceptions import (
    DatasetNotFoundError,
    InvalidPayloadError,
    QueryError,
    QueryMetadataNotReadyError,
)


class ApiAuthError(Exception):
    """端点依赖抛出的未认证错误，由统一异常处理器渲染成 401 信封。

    不直接用 fastapi.HTTPException：自定义异常类只可能来自本模块的 REST 依赖，
    注册针对性 exception_handler 不会波及合并进来的 MCP ASGI 路由的错误渲染。
    """

    def __init__(
        self,
        *,
        code: str = "authentication_required",
        message: str = "请先完成 AppHub 账号授权",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def success_response(data: object) -> JSONResponse:
    """构造统一成功响应（与 MCP 工具的 success/data/error 结构一致）。"""
    return JSONResponse(
        {
            "success": True,
            "data": data,
            "error": None,
        }
    )


def error_response(*, code: str, message: str, status_code: int) -> JSONResponse:
    """构造统一 API 错误响应。"""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


def safe_exception_message(exc: Exception) -> str:
    """仅向调用方暴露可用于修正请求的业务错误，避免泄漏内部细节。"""
    if isinstance(exc, QueryError):
        # QueryError 家族是面向使用方的业务错误（CLI 同样原文输出），可安全透出
        return str(exc) or "请求参数无效"
    if isinstance(exc, ValueError):
        return str(exc) or "请求参数无效"
    return "查询服务执行失败，请稍后重试"


def query_exception_response(exc: Exception) -> JSONResponse:
    """把 query 业务异常映射为语义化状态码的统一错误响应。

    映射原则：调用方改请求能解决的是 4xx（参数不合法 400 / 数据集不存在 404 /
    元数据未就绪 503），其余一律 502，错误码沿用 domain 异常自带的 code。
    """
    if isinstance(exc, InvalidPayloadError):
        return error_response(code=exc.code, message=str(exc), status_code=400)
    if isinstance(exc, DatasetNotFoundError):
        return error_response(code=exc.code, message=str(exc), status_code=404)
    if isinstance(exc, QueryMetadataNotReadyError):
        return error_response(code=exc.code, message=str(exc), status_code=503)
    if isinstance(exc, QueryError):
        return error_response(code=exc.code, message=str(exc), status_code=502)
    return error_response(
        code=type(exc).__name__,
        message=safe_exception_message(exc),
        status_code=502,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """注册 REST 层统一异常处理器。

    只处理本模块自定义异常与请求校验失败，不覆写 HTTPException / Exception
    的全局渲染，避免影响 wrap_mcp_app 合并进来的 MCP 路由。
    """

    @app.exception_handler(ApiAuthError)
    async def _handle_auth_error(_request: Request, exc: ApiAuthError) -> JSONResponse:
        return error_response(
            code=exc.code,
            message=exc.message,
            status_code=401,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 压缩 pydantic 默认的 detail 列表为一行可读原因，并保持统一信封
        reasons = []
        for item in exc.errors()[:6]:
            loc = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
            text = str(item.get("msg") or "").strip()
            reasons.append(f"{loc}: {text}" if loc else text)
        message = "请求参数验证失败" + (f"（{'；'.join(reasons)}）" if reasons else "")
        return error_response(code="VALIDATION_ERROR", message=message, status_code=422)
