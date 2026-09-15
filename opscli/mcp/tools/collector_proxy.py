"""通用 MCP 到 Collector MCP 的共享代理基础设施。"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

from opscli.config import __version__
from opscli.mcp.context import (
    get_current_api_key,
    get_current_auth_mode,
    get_current_jwt,
    get_current_session_id,
    get_current_user_email,
    get_current_user_id,
)
from opscli.mcp_client import RemoteMcpClient, RemoteMcpToolError

from .helpers import _err

ENV_COLLECTOR_MCP_URL = "OPSCLI_COLLECTOR_MCP_URL"
_logger = logging.getLogger(__name__)


class CollectorMcpProxyError(Exception):
    """Collector MCP 代理配置或调用错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        """返回稳定的 MCP 错误结构。"""
        return {"code": self.code, "message": str(self)}


async def call_collector(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    client_factory: Callable[..., RemoteMcpClient] = RemoteMcpClient,
) -> dict[str, Any]:
    """以当前最终用户身份调用 Collector 的同名 Tool。"""
    started = time.monotonic()
    url = os.environ.get(ENV_COLLECTOR_MCP_URL, "").strip()
    headers: dict[str, str] = {}
    forwarded: dict[str, Any] = {}
    stage = "configuration"
    try:
        url = _collector_url()
        stage = "identity"
        headers, apphub_request = _collector_headers()
        stage = "arguments"
        forwarded = _proxy_arguments(
            tool_name, arguments, include_apphub_auth=apphub_request,
        )
        stage = "remote_call"
        client = client_factory(
            url,
            headers=headers,
        )
        result = await client.call_tool(
            tool_name,
            forwarded,
        )
        if isinstance(result, dict) and result.get("success") is not True:
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            _log_collector_failure(
                tool_name, url, headers, forwarded, started, "remote_result",
                result_error=error,
            )
        return result
    except CollectorMcpProxyError as exc:
        _log_collector_failure(
            tool_name, url, headers, forwarded, started, stage,
            exception=exc, mapped_code=exc.code,
        )
        return _err(exc, tool=f"MCP → {tool_name}（Collector 代理）")
    except Exception as exc:  # noqa: BLE001
        if _is_collector_unavailable(exc):
            error = CollectorMcpProxyError(
                "COLLECTOR_MCP_UNAVAILABLE",
                f"数据采集服务不可用：{type(exc).__name__}",
            )
        else:
            error = CollectorMcpProxyError(
                "COLLECTOR_MCP_CALL_FAILED",
                f"数据采集服务调用失败：{type(exc).__name__}",
            )
        _log_collector_failure(
            tool_name, url, headers, forwarded, started, stage,
            exception=exc, mapped_code=error.code,
        )
        return _err(error, tool=f"MCP → {tool_name}（Collector 代理）")


def _safe_diagnostic_text(value: Any, secrets: list[str], *, limit: int = 1024) -> str:
    """只记录标量摘要；先脱敏再截断，避免截断后的凭证逃过匹配。"""
    if not isinstance(value, (str, int, float)):
        return "-"
    text = str(value)
    # 当前请求凭证即使被远端以无字段名文本回显，也不能进入日志。
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"https?://[^\s\"'<>]+", "[REDACTED_URL]", text, flags=re.I)
    text = re.sub(r"\bBearer\s+[^\s\"',;]+", "Bearer [REDACTED]", text, flags=re.I)
    text = re.sub(r"\beyJ[\w-]*\.[\w-]+\.[\w-]+", "[REDACTED]", text)
    # Cookie 可能包含多个以分号分隔的键值，整段删除而非只处理第一个键。
    text = re.sub(
        r"""(?i)\b(?:set-cookie|cookie)["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\r\n]+)""",
        "cookie=[REDACTED]", text,
    )
    text = re.sub(
        r"""(?i)\b([\w-]*(?:token|secret|password|passwd|pwd|jwt|authorization|"""
        r"""api[_-]?key|session[_-]?id)[\w-]*)["']?\s*[:=]\s*"""
        r"""(?:"[^"]*"|'[^']*'|[^\s,;}\]]+)""",
        r"\1=[REDACTED]", text,
    )
    text = re.sub(r"[\w.+-]+@[\w.-]+", "[REDACTED_EMAIL]", text)
    return " ".join(text.split())[:limit] or "-"


def _log_collector_failure(
    tool_name: str,
    url: str,
    headers: dict[str, str],
    forwarded: dict[str, Any],
    started: float,
    stage: str,
    *,
    exception: Exception | None = None,
    mapped_code: str = "-",
    result_error: dict[str, Any] | None = None,
) -> None:
    """记录低敏调用边界和远端错误，保持原有返回信封及 HTTP 映射。"""
    secrets = [
        str(value) for value in (
            get_current_api_key(), get_current_session_id(), get_current_jwt(),
            forwarded.get("session_id"), forwarded.get("jwt"),
        ) if value
    ]
    target = "-"
    try:
        parsed = urlsplit(url)
        secrets.extend(value for value in (parsed.username, parsed.password) if value)
        secrets.extend(value for _, value in parse_qsl(parsed.query) if value)
        # 目标独立记录，仅保留主机/端口/路径，禁止带入 userinfo、查询串或 fragment。
        if parsed.hostname:
            target = f"{parsed.scheme}://{parsed.netloc.rsplit('@', 1)[-1]}{parsed.path}"
    except ValueError:
        target = "[INVALID_URL]"

    remote_error = result_error or {}
    message: Any = remote_error.get("message")
    remote_code: Any = remote_error.get("code")
    downstream_status = None
    message_priority = -1
    pending: list[BaseException] = [exception] if exception else []
    seen: set[int] = set()
    # AnyIO 会把下游错误包在异常组内；沿两种异常链寻找真实 HTTP/工具失败。
    while pending and len(seen) < 32:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            downstream_status = current.response.status_code
        if isinstance(current, RemoteMcpToolError):
            message_priority = 2
            message = current.raw_text or str(current)
            payload = getattr(current.result, "structuredContent", None)
            if current.raw_text:
                try:
                    payload = json.loads(current.raw_text)
                except (ValueError, RecursionError):
                    pass
            if isinstance(payload, dict):
                detail = payload.get("error", payload)
                if isinstance(detail, dict):
                    remote_code = detail.get("code")
                    message = detail.get("message") or "Remote MCP tool returned an error"
                else:
                    message = "Remote MCP tool returned an error"
        else:
            # 工具正文优先于 HTTP 错误，HTTP 错误优先于外层异常组摘要。
            priority = 1 if isinstance(current, httpx.HTTPError) else 0
            if priority >= message_priority:
                message = str(current)
                message_priority = priority
        pending.extend(
            item for item in (current.__cause__, current.__context__)
            if isinstance(item, BaseException)
        )
        pending.extend(
            item for item in getattr(current, "exceptions", ())
            if isinstance(item, BaseException)
        )

    mode = str(get_current_auth_mode() or "")
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            target = target.replace(secret, "[REDACTED]")
    diagnostic = {
        "stage": stage,
        "gateway_version": __version__,
        # 身份模式仅记录已知枚举，身份字段仅记录有无。
        "auth_mode": mode if mode in {
            "remote", "fixed", "internal", "apphub_session", "apphub_viewer", "apphub_local",
        } else "unknown",
        "collector_target": " ".join(target.split())[:512],
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        "identity_forwarded": bool(headers.get("X-AppHub-User-Email")),
        "api_key_forwarded": bool(headers.get("Authorization")),
        "session_forwarded": bool(forwarded.get("session_id")),
        "jwt_forwarded": bool(forwarded.get("jwt")),
        "downstream_status": downstream_status,
        "remote_code": _safe_diagnostic_text(remote_code, secrets, limit=128),
        "remote_message": _safe_diagnostic_text(message, secrets),
    }
    cause = (exception.__cause__ or exception.__context__) if exception else None
    _logger.warning(
        "Collector MCP proxy failed tool=%s error_code=%s error_type=%s "
        "cause_type=%s nested_types=%s mapped_code=%s diagnostic=%s",
        _safe_diagnostic_text(tool_name, secrets, limit=128),
        diagnostic["remote_code"],
        type(exception).__name__ if exception else "-",
        type(cause).__name__ if cause else "-",
        _nested_exception_types(exception) if exception else "-",
        mapped_code,
        json.dumps(diagnostic, ensure_ascii=True),
    )


def collector_proxy_tool(
    module_name: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """标记代理 Tool 的额度归属和稳定 Catalog 模块名。"""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__opscli_skip_quota__ = True
        fn.__opscli_catalog_module__ = module_name
        # 网关和 Collector 都会上报遥测；显式角色让统计只计实际执行入口。
        fn.__opscli_telemetry_role__ = "gateway_proxy"
        return fn

    return decorate


def _collector_url() -> str:
    url = os.environ.get(ENV_COLLECTOR_MCP_URL, "").strip()
    if not url:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_CONFIG_MISSING",
            f"缺少 {ENV_COLLECTOR_MCP_URL}，无法访问数据采集服务",
        )
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_CONFIG_INVALID",
            f"{ENV_COLLECTOR_MCP_URL} 必须是有效的 HTTP(S) MCP 地址",
        )
    query_names = {name.strip().lower() for name, _ in parse_qsl(parsed.query)}
    if "api_key" in query_names:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_CONFIG_INVALID",
            f"{ENV_COLLECTOR_MCP_URL} 不得包含共享 api_key",
        )
    return url


def _current_api_key() -> str:
    api_key = str(get_current_api_key() or "").strip()
    if not api_key:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_IDENTITY_MISSING",
            "当前 MCP 请求缺少用户 API Key，已阻止访问数据采集服务",
        )
    return api_key


def _collector_headers() -> tuple[dict[str, str], bool]:
    auth_mode = str(get_current_auth_mode() or "")
    if auth_mode.startswith("apphub_"):
        email = str(get_current_user_email() or "").strip().lower()
        if not email:
            raise CollectorMcpProxyError(
                "COLLECTOR_MCP_IDENTITY_MISSING",
                "当前 AppHub 请求缺少已验证用户身份",
            )
        headers = {
            "X-AppHub-User-Email": email,
            "X-AppHub-Auth-Mode": auth_mode.removeprefix("apphub_"),
        }
        user_id = str(get_current_user_id() or "").strip()
        if user_id:
            headers["X-AppHub-User-Id"] = user_id
        return headers, True
    return {"Authorization": f"Bearer {_current_api_key()}"}, False


def _proxy_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    include_apphub_auth: bool,
) -> dict[str, Any]:
    forwarded = {
        key: value
        for key, value in arguments.items()
        if value is not None and key not in {"session_id", "jwt"}
    }
    if include_apphub_auth and tool_name in {
        "seller_sprite_run",
        "seller_sprite_listing_analysis_submit",
        "seller_sprite_listing_analysis_status",
        "seller_sprite_listing_analysis_result",
    }:
        session_id = get_current_session_id()
        jwt = get_current_jwt()
        if (
            not session_id
            and not jwt
            and get_current_auth_mode() == "apphub_local"
        ):
            from .helpers import _get_auth_pair

            session_id, jwt = _get_auth_pair("ops", None, None)
        if session_id:
            forwarded["session_id"] = session_id
        if jwt:
            forwarded["jwt"] = jwt
    return forwarded


def _is_collector_unavailable(error: BaseException) -> bool:
    """遍历显式/隐式异常链和异常组，识别连接与超时故障。

    异常链可能形成重复引用，因此按对象 ID 去重；只把网络不可达归为
    unavailable，其他远端执行错误统一保留为 call_failed。
    """
    seen: set[int] = set()
    pending = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (httpx.ConnectError, httpx.TimeoutException)):
            return True
        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        context = getattr(current, "__context__", None)
        if isinstance(context, BaseException):
            pending.append(context)
        nested = getattr(current, "exceptions", None)
        if isinstance(nested, tuple):
            pending.extend(item for item in nested if isinstance(item, BaseException))
    return False


def _nested_exception_types(error: BaseException) -> str:
    """返回异常组和异常链中的类型摘要，不记录异常文本或凭证。"""
    types: list[str] = []
    pending = [error]
    seen: set[int] = set()
    while pending and len(types) < 8:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if current is not error:
            types.append(type(current).__name__)
        cause = current.__cause__ or current.__context__
        if isinstance(cause, BaseException):
            pending.append(cause)
        nested = getattr(current, "exceptions", None)
        if isinstance(nested, tuple):
            pending.extend(item for item in nested if isinstance(item, BaseException))
    return ",".join(types) if types else "-"
