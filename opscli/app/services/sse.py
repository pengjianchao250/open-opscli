"""AppHub SSE 帧解析。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from opscli.app.domain.exceptions import AppHubHttpError


def parse_sse_lines(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """把 text/event-stream 行解析为 JSON 事件。"""
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                yield _decode_event(event_name, data_lines)
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_name = value or "message"
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        yield _decode_event(event_name, data_lines)


def _decode_event(event_name: str, data_lines: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise AppHubHttpError("APPHUB-SSE-PROTOCOL", "AppHub SSE data 不是有效 JSON。") from exc
    if not isinstance(payload, dict):
        raise AppHubHttpError("APPHUB-SSE-PROTOCOL", "AppHub SSE data 必须是对象。")
    payload["event"] = event_name
    return payload
