"""把 Keepa 原始业务响应导出为保留嵌套结构的 JSON。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opscli.keepa.domain.models import KeepaExportResult

_QUOTA_FIELDS = {
    "tokensleft",
    "tokensconsumed",
    "refillin",
    "refillrate",
    "tokenflowreduction",
}


def export_response_to_json(
    *,
    response: dict[str, Any],
    output_path: Path,
    scenario: str,
    site: str = "US",
) -> KeepaExportResult:
    """导出 Keepa 原始业务响应，同时移除仅供内部额度管理使用的字段。"""
    payload = {
        "schema_version": "2.0",
        "scenario": scenario,
        "site": site,
        "response": _without_quota_fields(response),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    resolved = output_path.resolve()
    return KeepaExportResult(
        path=str(resolved),
        filename=resolved.name,
        url=resolved.as_uri(),
        format="json",
        mime_type="application/json",
    )


def _without_quota_fields(value: Any) -> Any:
    """递归复制响应，避免公开导出携带 Keepa 账号额度信息。"""
    if isinstance(value, list):
        return [_without_quota_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _without_quota_fields(item)
        for key, item in value.items()
        if str(key).casefold() not in _QUOTA_FIELDS
    }
