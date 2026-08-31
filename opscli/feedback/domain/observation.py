"""反馈 Observation Schema V2 的规范化与校验。"""

from __future__ import annotations

import math
import platform
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from opscli.feedback.domain.exceptions import InvalidPayloadError


OBSERVATION_SCHEMA_VERSION = "2.0"


def _non_negative_float(value: Any, label: str) -> float | None:
    """把可选数值规范为非负浮点数。"""
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidPayloadError(f"{label} 必须是大于或等于 0 的数字") from exc
    if not math.isfinite(parsed):
        raise InvalidPayloadError(f"{label} 必须是有限的非负数字")
    if parsed < 0:
        raise InvalidPayloadError(f"{label} 必须大于或等于 0")
    return parsed


def _non_negative_int(value: Any, label: str) -> int:
    """把可选数值规范为非负整数。"""
    if value is None or value == "":
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidPayloadError(f"{label} 必须是大于或等于 0 的整数") from exc
    if parsed < 0 or isinstance(value, float) and not value.is_integer():
        raise InvalidPayloadError(f"{label} 必须是大于或等于 0 的整数")
    return parsed


def _optional_text(value: Any, label: str, maximum: int = 200) -> str | None:
    """规范可选短文本，避免观测索引字段被大文本污染。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > maximum:
        raise InvalidPayloadError(f"{label} 不能超过 {maximum} 个字符")
    return text


def _utc_timestamp(value: Any) -> str:
    """校验调用方时间并统一转换为 UTC ISO-8601。"""
    if value is None or value == "":
        parsed = datetime.now(timezone.utc)
    else:
        text = _optional_text(value, "context.observation.occurred_at", 64)
        try:
            parsed = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidPayloadError(
                "context.observation.occurred_at 必须是带时区的 ISO-8601 时间"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise InvalidPayloadError(
                "context.observation.occurred_at 必须是带时区的 ISO-8601 时间"
            )
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_observation(
    *,
    context: dict[str, Any],
    source: str,
    system_alias: str,
    client_name: str,
    client_version: str,
    skill_name: str | None,
    command_name: str | None,
    mcp_tool_name: str | None,
    execution_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """生成后端兼容的标准观测对象。

    Observation 放在既有 ``context`` JSON 内，旧后端无需新增列即可接收。
    调用方可在 ``context.observation`` 或 context 顶层提供链路字段；缺失的
    事件身份、时间、客户端和运行时字段由当前进程补齐。

    Args:
        context: 调用方补充上下文及可选 observation 对象。
        source: 反馈来源。
        system_alias: 目标系统别名。
        client_name: 提交客户端名称。
        client_version: 提交客户端版本。
        skill_name: 可选 Skill 名称。
        command_name: 可选 CLI 命令名称。
        mcp_tool_name: 可选 MCP Tool 名称。
        execution_summary: 可选结构化执行摘要。

    Returns:
        已补齐并规范化的 Observation Schema V2 对象。

    Raises:
        InvalidPayloadError: observation 类型、时间或数值字段不合法。
    """
    raw = context.get("observation")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise InvalidPayloadError("context.observation 必须是 JSON 对象")
    raw = dict(raw)

    for key in (
        "correlation_id",
        "request_id",
        "error_code",
        "duration_ms",
        "retry_count",
        "environment",
        "fingerprint",
        "fingerprint_version",
    ):
        if key not in raw and key in context:
            raw[key] = context[key]

    failed_calls = execution_summary.get("failed_calls") if isinstance(execution_summary, dict) else None
    has_failure = isinstance(failed_calls, list) and bool(failed_calls)
    operation = _optional_text(
        raw.get("operation") or mcp_tool_name or command_name or skill_name or client_name,
        "context.observation.operation",
    )
    observation: dict[str, Any] = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "event_id": _optional_text(raw.get("event_id"), "context.observation.event_id", 128)
        or str(uuid4()),
        "occurred_at": _utc_timestamp(raw.get("occurred_at")),
        "source": source,
        "system_alias": system_alias,
        "operation": operation or "feedback",
        "outcome": _optional_text(raw.get("outcome"), "context.observation.outcome", 32)
        or ("failure" if has_failure else "reported"),
        "retry_count": _non_negative_int(raw.get("retry_count"), "retry_count"),
        "client_name": client_name,
        "client_version": client_version,
        "runtime": {
            "python_version": platform.python_version(),
            "platform": sys.platform,
        },
    }
    duration_ms = _non_negative_float(raw.get("duration_ms"), "duration_ms")
    if duration_ms is not None:
        observation["duration_ms"] = duration_ms
    for key in (
        "correlation_id",
        "request_id",
        "error_code",
        "environment",
        "fingerprint",
        "fingerprint_version",
    ):
        value = _optional_text(raw.get(key), f"context.observation.{key}")
        if value is not None:
            observation[key] = value
    return observation
