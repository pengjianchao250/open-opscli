"""Amazon 商品数据 MCP 工具模块。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from opscli.skills.packaging import get_builtin_templates_dir

from .export_fallback import attach_json_data_fallback, build_export_payload_with_fallback
from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg

MAX_PUBLIC_DATA_PREVIEW_ROWS = 20


def _scrape_do_skill_dir() -> Path:
    """返回 Amazon 商品数据 Skill 模板目录。"""
    return get_builtin_templates_dir() / "ops-amazon-product-data"


async def scrape_do_spec_must_read() -> dict:
    """读取 Amazon 商品数据 MCP 使用规范。"""
    spec_path = _scrape_do_skill_dir() / "SKILL_MCP.md"
    if not spec_path.exists():
        return _safe_err(
            FileNotFoundError("Amazon 商品数据 MCP 规范文档不存在：ops-amazon-product-data/SKILL_MCP.md。请检查 opscli 安装是否完整。"),
            tool="MCP → scrape_do_spec_must_read()",
        )
    try:
        content = spec_path.read_text(encoding="utf-8")
        source = "ops-amazon-product-data/SKILL_MCP.md"
        return _ok({"spec": content, "source": source, "sources": [source]})
    except Exception as exc:
        return _safe_err(exc, tool="MCP → scrape_do_spec_must_read()")


async def scrape_do_scenarios() -> dict:
    """列出 Amazon 商品数据 支持的接口场景。"""
    try:
        from opscli.scrape_do.services import ScrapeDoApiManager

        return _ok(_public_scenarios(ScrapeDoApiManager().scenarios()))
    except Exception as exc:
        return _safe_err(exc, tool="MCP → scrape_do_scenarios()")


async def scrape_do_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    export_format: str = "xls",
    output_dir: str | None = None,
    job_id: str | None = None,
    timeout_seconds: int | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """执行 Amazon 商品数据 场景并保存请求参数、原始响应、规范化结果和导出 XLSX。"""
    call_params = {
        "scenario": scenario,
        "site": site,
        "export_format": export_format,
        "job_id": job_id,
        "timeout_seconds": timeout_seconds,
    }
    try:
        sid, jw = _get_auth_pair("ops", session_id, jwt)
        from opscli.scrape_do.domain.models import ScrapeDoScenarioRequest
        from opscli.scrape_do.services import ScrapeDoApiManager

        parsed_params = _parse_json_arg(params, dict) or {}
        request = ScrapeDoScenarioRequest(
            scenario=scenario,
            site=site,
            params=parsed_params,
            output_dir=output_dir,
            job_id=job_id,
            export_format=export_format,
            timeout_seconds=timeout_seconds,
        )
        result = await ScrapeDoApiManager(jwt=jw, session_id=sid).run(request)
        return _ok(_public_result(result.to_dict()))
    except Exception as exc:
        return _safe_err(exc, tool="MCP → scrape_do_run(...)", call_params=call_params)


async def scrape_do_job_status(job_id: str) -> dict:
    """读取 Amazon 商品数据 任务结果。"""
    try:
        from opscli.scrape_do.services import ScrapeDoApiManager

        return _ok(_public_result(ScrapeDoApiManager().job_status(job_id)))
    except Exception as exc:
        return _safe_err(exc, tool="MCP → scrape_do_job_status(...)", call_params={"job_id": job_id})


async def scrape_do_export(job_id: str) -> dict:
    """读取 Amazon 商品数据 任务导出文件信息。"""
    try:
        from opscli.scrape_do.services import ScrapeDoApiManager

        status = ScrapeDoApiManager().job_status(job_id)
        public_status = _sanitize_public_strings(_scrub_public_payload(status))
        if not isinstance(public_status, dict):
            raise ValueError("任务导出结构不合法")
        export = _public_export_payload(build_export_payload_with_fallback(public_status))
        if not export.get("url") and "json_data" not in export:
            raise ValueError(f"任务导出文件没有可下载地址：{job_id}")
        return _ok(export)
    except Exception as exc:
        return _safe_err(exc, tool="MCP → scrape_do_export(...)", call_params={"job_id": job_id})


_ALL_TOOLS = [
    scrape_do_spec_must_read,
    scrape_do_scenarios,
    scrape_do_run,
    scrape_do_job_status,
    scrape_do_export,
]


def _safe_err(exc: Exception, *, tool: str | None = None, call_params: dict | None = None) -> dict:
    """返回 Amazon 商品数据 MCP 安全错误，不暴露本地路径、endpoint 和敏感字段。"""
    safe_message = _sanitize_public_text(str(exc)) or "Amazon 商品数据 MCP 工具调用失败。"
    safe_exc = type(exc)(safe_message)
    result = _err(safe_exc, tool=tool, call_params=_safe_call_params(call_params))
    return _sanitize_error_payload(result)


def _safe_call_params(call_params: dict | None) -> dict | None:
    if call_params is None:
        return None
    cleaned = _scrub_public_payload(call_params)
    return cleaned if isinstance(cleaned, dict) else {}


def _sanitize_error_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = _sanitize_error_text(_scrub_public_payload(payload))
    return cleaned if isinstance(cleaned, dict) else {"success": False, "data": None, "error": {"code": "Error", "message": "Amazon 商品数据 MCP 工具调用失败。"}}


def _sanitize_error_text(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_error_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_error_text(item) for key, item in value.items()}
    if isinstance(value, str):
        return _sanitize_public_text(value)
    return value


def _sanitize_public_text(value: str) -> str:
    cleaned = re.sub(r"<[^>]*>", "", value)
    cleaned = re.sub(r"file://\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"/plugin/amazon\S*", "", cleaned)
    cleaned = re.sub(r"(?<!\w)[A-Za-z]:[\\/]\S+", "", cleaned)
    cleaned = re.sub(r"(?<![:/\w])(?:~[\\/]|/{1,2})\S+", "", cleaned)
    cleaned = re.sub(r"\b\S*(?:token|secret)\S*\b", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip()


def _public_scenarios(payload: Any) -> list[dict[str, Any]]:
    """返回不包含内部 endpoint 的 MCP 场景列表。"""
    public = _sanitize_public_strings(_scrub_public_payload(payload))
    if not isinstance(public, list):
        return []
    return [item for item in public if isinstance(item, dict)]


def _public_result(payload: dict[str, Any]) -> dict[str, Any]:
    """返回 MCP 安全任务数据，不暴露本地路径、原始响应和敏感字段。"""
    public = _sanitize_public_strings(_scrub_public_payload(payload))
    if isinstance(public, dict):
        attach_json_data_fallback(public)
        _sanitize_public_export(public)
        _compact_public_data(public)
        public["warnings"] = _public_warnings(public.get("warnings"))
    return public if isinstance(public, dict) else {}


def _compact_public_data(public: dict[str, Any]) -> None:
    data = public.get("data")
    if isinstance(data, list):
        public["data_preview"] = data[:MAX_PUBLIC_DATA_PREVIEW_ROWS]
        public.pop("data", None)


def _sanitize_public_export(public: dict[str, Any]) -> None:
    export = public.get("export")
    if not isinstance(export, dict):
        return
    url = export.get("url")
    if url or "json_data" in export:
        return

    warnings = public.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings.append(
        {
            "stage": "export_url_unavailable",
            "message": "当前任务导出文件没有可下载地址，请稍后重试或联系管理员检查上传链路。",
        }
    )
    public["warnings"] = warnings


def _public_export_payload(export: Any) -> dict[str, Any]:
    if not isinstance(export, dict):
        raise ValueError("任务无导出文件")
    payload = _sanitize_public_strings(_scrub_public_payload(export))
    if not isinstance(payload, dict):
        raise ValueError("任务导出结构不合法")
    return payload


def _sanitize_public_strings(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_public_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_public_strings(item) for key, item in value.items()}
    if isinstance(value, str):
        cleaned = _sanitize_public_text(value)
        return cleaned if cleaned else None
    return value


_DROP = object()


def _scrub_public_payload(value: Any) -> Any:
    cleaned = _scrub_public_value(value)
    if cleaned is _DROP:
        return None
    return cleaned


def _scrub_public_value(value: Any) -> Any:
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, list):
        result = []
        for item in value:
            cleaned = _scrub_public_value(item)
            if cleaned is not _DROP:
                result.append(cleaned)
        return result
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = _normalize_public_key(key)
            if _is_blocked_public_field(normalized):
                continue
            cleaned = _scrub_public_value(item)
            if cleaned is _DROP:
                continue
            result[key] = cleaned
        return result
    if isinstance(value, str):
        if _is_file_url(value):
            return None
        if _is_local_path(value) or _is_internal_endpoint(value):
            return _DROP
    return value


def _normalize_public_key(key: Any) -> str:
    return str(key).replace("-", "_").lower()


def _is_blocked_public_field(normalized_key: str) -> bool:
    return (
        normalized_key
        in {
            "artifact",
            "endpoint",
            "normalized_params",
            "raw_response",
            "request_params",
            "response",
            "root_dir",
            "settings",
        }
        or normalized_key in {"path", "paths"}
        or normalized_key.endswith("_dir")
        or normalized_key.endswith("_dirs")
        or normalized_key.endswith("_path")
        or normalized_key.endswith("_paths")
        or "html" in normalized_key
        or _is_sensitive_field(normalized_key)
    )


def _is_sensitive_field(normalized_key: str) -> bool:
    return (
        normalized_key in {"token", "api_key", "authorization"}
        or normalized_key.endswith("_token")
        or "token" in normalized_key
        or "secret" in normalized_key
    )


def _is_file_url(value: str) -> bool:
    return value.strip().lower().startswith("file://")


def _is_internal_endpoint(value: str) -> bool:
    return value.startswith("/plugin/amazon")


def _is_local_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith(("~/", "~\\", "\\\\")):
        return True
    if text.startswith("/") and not _is_internal_endpoint(text):
        return True
    return len(text) >= 3 and text[1] == ":" and text[0].isalpha() and text[2] in {"/", "\\"}


def _public_warnings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    warnings: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        stage = item.get("stage")
        message = item.get("message")
        if stage == "file_upload":
            warnings.append({"stage": stage, "message": message or "导出文件上传失败，已保留服务端本地文件"})
        elif message:
            warnings.append({"stage": stage, "message": message})
    return warnings


def register(mcp) -> None:
    """向 FastMCP 实例注册 Amazon 商品数据 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
