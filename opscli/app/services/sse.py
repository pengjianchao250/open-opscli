"""AppHub Server-Sent Events 解析器。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

from opscli.app.domain.exceptions import AppHubProtocolError
from opscli.app.domain.models import SSEFrame


def parse_sse(lines: Iterable[str]) -> Iterator[SSEFrame]:
    """解析 SSE 文本行，忽略心跳注释并支持多行 data。"""
    event = "message"
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if data_lines or event != "message":
                yield _build_frame(event, data_lines)
            event = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value or "message"
        elif field == "data":
            data_lines.append(value)
    if data_lines or event != "message":
        yield _build_frame(event, data_lines)


def _build_frame(event: str, data_lines: list[str]) -> SSEFrame:
    text = "\n".join(data_lines) or "{}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppHubProtocolError(
            "APPHUB-PROTOCOL",
            "AppHub 返回了无法解析的 SSE JSON。",
        ) from exc
    if not isinstance(data, dict):
        raise AppHubProtocolError("APPHUB-PROTOCOL", "SSE data 必须是 JSON 对象。")
    return SSEFrame(event=event, data=data)

