"""MCP 导出文件上传失败时的 JSON 数据兜底。"""

from __future__ import annotations

from typing import Any


def attach_json_data_fallback(payload: dict[str, Any]) -> bool:
    """上传失败且无远端链接时，把完整业务数据挂到 export.json_data。"""
    export = payload.get("export")
    if not isinstance(export, dict):
        return False
    if not has_file_upload_failure(payload.get("warnings")):
        return False
    if _has_remote_url(export):
        return False
    if "data" not in payload:
        return False
    export.setdefault("url", None)
    export["json_data"] = payload["data"]
    return True


def build_export_payload_with_fallback(payload: dict[str, Any]) -> dict[str, Any]:
    """复制导出信息，并按完整任务结果补充 JSON 兜底数据。"""
    export = payload.get("export")
    if not isinstance(export, dict):
        raise ValueError("任务无导出文件")
    normalized = dict(payload)
    normalized["export"] = dict(export)
    attach_json_data_fallback(normalized)
    return normalized["export"]


def has_file_upload_failure(warnings: Any) -> bool:
    """判断 warning 列表是否包含导出文件上传失败。"""
    if not isinstance(warnings, list):
        return False
    return any(
        isinstance(item, dict) and item.get("stage") == "file_upload"
        for item in warnings
    )


def _has_remote_url(export: dict[str, Any]) -> bool:
    for key in ("url", "download_url"):
        value = export.get(key)
        if isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
            return True
    return False
