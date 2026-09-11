"""西柚试用期远端 MCP Provider。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import anyio
import httpx

from opscli.api_credentials import ApiCredentialLease, ApiCredentialPool
from opscli.api_credentials.exceptions import ApiCredentialUnavailableError
from opscli.mcp_client import RemoteMcpClient, RemoteMcpToolError


XYDC_MCP_URL = "https://mcp.xydc.com/mcp"
MAX_ACCOUNT_ATTEMPTS = 3
TOTAL_TIMEOUT_SECONDS = 60.0
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

_QUOTA_ERROR_CODES = frozenset(
    {
        "CREDIT_EXHAUSTED",
        "CREDITS_EXHAUSTED",
        "INSUFFICIENT_CREDITS",
        "QUOTA_EXHAUSTED",
        "WEEKLY_QUOTA_EXCEEDED",
    }
)
_INVALID_TOKEN_CODES = frozenset(
    {
        "AUTHENTICATION_FAILED",
        "INVALID_API_KEY",
        "INVALID_TOKEN",
        "TOKEN_EXPIRED",
        "UNAUTHORIZED",
    }
)
_QUOTA_MESSAGES = (
    "insufficient credits",
    "weekly quota exceeded",
    "额度不足",
    "积分不足",
)
_INVALID_TOKEN_MESSAGES = (
    "invalid token",
    "token expired",
    "token无效",
    "token 已失效",
)


class XydcMcpError(Exception):
    """不暴露账号密钥和供应商原始响应的稳定错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        """返回 MCP 可直接使用的错误结构。"""
        return {"code": self.code, "message": str(self)}


class _StructuredXydcFailure(Exception):
    def __init__(self, category: str, payload: dict[str, Any]) -> None:
        super().__init__(category)
        self.category = category
        self.payload = payload


class XydcMcpProvider:
    """使用 MySQL 多账号池调用固定的西柚 MCP Endpoint。"""

    def __init__(
        self,
        credential_pool: ApiCredentialPool | None = None,
        *,
        client_factory: Callable[..., RemoteMcpClient] = RemoteMcpClient,
        max_account_attempts: int = MAX_ACCOUNT_ATTEMPTS,
        timeout_seconds: float = TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        if max_account_attempts <= 0:
            raise ValueError("max_account_attempts 必须大于 0")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self._credential_pool = credential_pool
        self.client_factory = client_factory
        self.max_account_attempts = max_account_attempts
        self.timeout_seconds = timeout_seconds

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用一次西柚工具；仅在明确额度耗尽或 Token 无效时换账号。"""
        attempted_ids: set[int] = set()
        last_switch_reason: str | None = None

        for _attempt in range(self.max_account_attempts):
            try:
                lease = self._pool().acquire(
                    "xydc_mcp",
                    exclude_account_ids=attempted_ids,
                )
            except ApiCredentialUnavailableError as exc:
                message = "西柚 MCP 当前没有可用试用账号"
                if attempted_ids:
                    message = (
                        "西柚 MCP 试用账号额度均已耗尽"
                        if last_switch_reason == "quota_exhausted"
                        else "西柚 MCP 试用账号均不可用"
                    )
                raise XydcMcpError(
                    "XYDC_MCP_ACCOUNTS_UNAVAILABLE",
                    message,
                ) from exc
            except Exception as exc:
                raise XydcMcpError(
                    "XYDC_MCP_CREDENTIAL_POOL_UNAVAILABLE",
                    "西柚 MCP 凭据池不可用",
                ) from exc

            attempted_ids.add(lease.account_id)
            try:
                payload = await self._call_remote(lease, tool_name, arguments)
                failure = _classify_payload_failure(payload)
                if failure is not None:
                    raise _StructuredXydcFailure(failure, payload)
            except Exception as exc:  # noqa: BLE001
                category = _classify_error(exc)
                if category in {"quota_exhausted", "invalid_token"}:
                    last_switch_reason = category
                    self._report_switchable_failure(lease, category, exc)
                    continue
                self._report_call_failure(lease, exc)
                raise _public_call_error(exc) from exc

            safe_payload = _redact_secret(payload, lease.secret)
            self._report_success(lease, safe_payload)
            return _normalize_success(safe_payload)

        message = (
            "西柚 MCP 试用账号额度均已耗尽"
            if last_switch_reason == "quota_exhausted"
            else "西柚 MCP 试用账号均不可用"
        )
        raise XydcMcpError("XYDC_MCP_ACCOUNTS_UNAVAILABLE", message)

    async def _call_remote(
        self,
        lease: ApiCredentialLease,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        client = self.client_factory(
            XYDC_MCP_URL,
            headers={"Authorization": f"Bearer {lease.secret}"},
            follow_redirects=False,
            max_response_bytes=MAX_RESPONSE_BYTES,
        )
        with anyio.fail_after(self.timeout_seconds):
            return await client.call_tool(tool_name, arguments)

    def _pool(self) -> ApiCredentialPool:
        if self._credential_pool is None:
            self._credential_pool = ApiCredentialPool()
        return self._credential_pool

    def _report_switchable_failure(
        self,
        lease: ApiCredentialLease,
        category: str,
        exc: BaseException,
    ) -> None:
        runtime: dict[str, Any] = {}
        reset_at = _safe_reset_at(
            _find_value(_structured_error_payload(exc), "quota_reset_at", "reset_at")
        )
        if reset_at:
            runtime["quota_reset_at"] = reset_at
        try:
            self._pool().report_failure(
                lease,
                error_code=(
                    "xydc_weekly_quota_exhausted"
                    if category == "quota_exhausted"
                    else "xydc_invalid_token"
                ),
                message=(
                    "西柚 MCP 周额度已耗尽"
                    if category == "quota_exhausted"
                    else "西柚 MCP Token 无效"
                ),
                exhausted=category == "quota_exhausted",
                disable=category == "invalid_token",
                runtime=runtime,
            )
        except Exception:
            pass

    def _report_call_failure(self, lease: ApiCredentialLease, exc: BaseException) -> None:
        try:
            self._pool().report_failure(
                lease,
                error_code="xydc_mcp_call_failed",
                message=f"西柚 MCP 调用失败：{type(exc).__name__}",
            )
        except Exception:
            pass

    def _report_success(self, lease: ApiCredentialLease, payload: dict[str, Any]) -> None:
        cost_credits = payload.get("cost_credits")
        runtime = (
            {"provider_metadata": {"last_cost_credits": cost_credits}}
            if cost_credits is not None
            else None
        )
        try:
            self._pool().report_success(lease, runtime=runtime)
        except Exception:
            pass


def _normalize_success(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "data": payload.get("data"),
        "error": None,
        "source": "xydc_mcp",
        "provider_status": payload.get("status"),
        "cost_credits": payload.get("cost_credits"),
    }


def _classify_payload_failure(payload: dict[str, Any]) -> str | None:
    if payload.get("success") is True:
        return None
    status = payload.get("status")
    normalized_status = str(status or "").strip().lower()
    if _is_success_status(status) or normalized_status in {"success", "ok", "succeeded"}:
        return None
    if _status_code(status) == 401:
        return "invalid_token"
    if _status_code(status) == 402:
        return "quota_exhausted"
    if normalized_status or payload.get("success") is False or "error" in payload:
        return _classify_structured_payload(payload) or "call_failed"
    return None


def _is_success_status(value: Any) -> bool:
    status_code = _status_code(value)
    return status_code is not None and 200 <= status_code < 300


def _status_code(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _classify_error(exc: BaseException) -> str:
    if isinstance(exc, _StructuredXydcFailure):
        return exc.category
    status_code = _http_status_code(exc)
    if status_code == 401:
        return "invalid_token"
    if status_code == 402:
        return "quota_exhausted"
    return _classify_structured_payload(_structured_error_payload(exc)) or "call_failed"


def _classify_structured_payload(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    codes = {
        str(value).strip().upper().replace("-", "_")
        for value in _find_values(payload, "code", "error_code", "errorCode")
        if value is not None
    }
    if codes & _QUOTA_ERROR_CODES:
        return "quota_exhausted"
    if codes & _INVALID_TOKEN_CODES:
        return "invalid_token"

    messages = [
        str(value).strip().lower()
        for value in _find_values(payload, "message", "error_message", "errorMessage")
        if value is not None
    ]
    if any(marker in message for message in messages for marker in _QUOTA_MESSAGES):
        return "quota_exhausted"
    if any(marker in message for message in messages for marker in _INVALID_TOKEN_MESSAGES):
        return "invalid_token"
    return None


def _structured_error_payload(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, _StructuredXydcFailure):
        return exc.payload
    if isinstance(exc, RemoteMcpToolError) and isinstance(exc.raw_text, str):
        try:
            payload = json.loads(exc.raw_text)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _http_status_code(exc: BaseException) -> int | None:
    seen: set[int] = set()
    pending = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            return current.response.status_code
        for nested in (
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
        nested_group = getattr(current, "exceptions", None)
        if isinstance(nested_group, (tuple, list)):
            pending.extend(item for item in nested_group if isinstance(item, BaseException))
    return None


def _find_values(payload: Mapping[str, Any], *keys: str) -> list[Any]:
    matches: list[Any] = []
    for key, value in payload.items():
        if key in keys:
            matches.append(value)
        if isinstance(value, Mapping):
            matches.extend(_find_values(value, *keys))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    matches.extend(_find_values(item, *keys))
    return matches


def _find_value(payload: Mapping[str, Any], *keys: str) -> Any:
    values = _find_values(payload, *keys)
    return values[0] if values else None


def _safe_reset_at(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _redact_secret(value: Any, secret: str) -> Any:
    if isinstance(value, dict):
        return {key: _redact_secret(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_secret(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def _public_call_error(exc: BaseException) -> XydcMcpError:
    if _contains_exception(exc, (TimeoutError, httpx.TimeoutException)):
        return XydcMcpError("XYDC_MCP_TIMEOUT", "西柚 MCP 调用超时，未自动切换账号")
    if isinstance(exc, _StructuredXydcFailure):
        return XydcMcpError("XYDC_MCP_CALL_FAILED", "西柚 MCP 返回业务错误，未自动切换账号")
    return XydcMcpError(
        "XYDC_MCP_CALL_FAILED",
        f"西柚 MCP 调用失败：{type(exc).__name__}，未自动切换账号",
    )


def _contains_exception(
    exc: BaseException,
    types: tuple[type[BaseException], ...],
) -> bool:
    seen: set[int] = set()
    pending = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, types):
            return True
        for nested in (
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
        nested_group = getattr(current, "exceptions", None)
        if isinstance(nested_group, (tuple, list)):
            pending.extend(item for item in nested_group if isinstance(item, BaseException))
    return False
