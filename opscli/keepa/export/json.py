"""把 Keepa 原始业务响应导出为保留嵌套结构的 JSON。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opscli.keepa.domain.models import KeepaExportResult

# 这些字段只描述 Keepa 账号额度，不属于对外业务响应。
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
    """导出 Keepa 原始业务响应。

    Args:
        response: Keepa Endpoint 返回的原始 JSON 对象。
        output_path: JSON 导出文件路径。
        scenario: 当前 Keepa 场景 ID。
        site: Amazon 站点代码。

    Returns:
        已生成文件的路径、格式和 MIME 元数据。
    """
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
