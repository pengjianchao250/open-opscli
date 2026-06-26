"""Google Trends MCP 工具模块。

将 Google Trends 能力暴露为 MCP 工具：
- google_trends_spec_must_read — 读取 Google Trends MCP 使用规范
- google_trends_scenarios      — 列出 Google Trends 场景
- google_trends_run            — 执行 Google Trends 场景并保存请求/响应/导出
- google_trends_job_status     — 读取任务结果
- google_trends_export         — 读取导出文件信息
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opscli.skills.packaging import get_builtin_templates_dir

from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg


def _google_trends_skill_dir() -> Path:
    """返回 Google Trends Skill 模板目录。"""
    return get_builtin_templates_dir() / "ops-google-trends"


async def google_trends_spec_must_read() -> dict:
    """读取 Google Trends MCP 使用规范。

    规范内容统一收口到 opscli 内置 Skill 模板：
    - opscli/skills/templates/ops-google-trends/SKILL_MCP.md
    """
    spec_path = _google_trends_skill_dir() / "SKILL_MCP.md"
    if not spec_path.exists():
        return _err(
            FileNotFoundError(f"Google Trends MCP 规范文档不存在：{spec_path}。请检查 opscli 安装是否完整。"),
            tool="MCP → google_trends_spec_must_read()",
        )
    try:
        content = spec_path.read_text(encoding="utf-8")
        return _ok({"spec": content, "source": str(spec_path), "sources": [str(spec_path)]})
    except Exception as exc:
        return _err(exc, tool="MCP → google_trends_spec_must_read()")


async def google_trends_scenarios() -> dict:
    """列出 Google Trends 支持的接口场景。"""
    try:
        from opscli.google_trends.services import GoogleTrendsApiManager

        return _ok(GoogleTrendsApiManager().scenarios())
    except Exception as exc:
        return _err(exc, tool="MCP → google_trends_scenarios()")


async def google_trends_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    geo: str = "US",
    export_format: str = "xls",
    output_dir: str | None = None,
    job_id: str | None = None,
    hl: str | None = None,
    tz: int | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """执行 Google Trends 场景并保存请求参数、原始响应、规范化结果和导出 XLSX。"""
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    call_params = {
        "scenario": scenario,
        "geo": geo,
        "export_format": export_format,
        "job_id": job_id,
        "hl": hl,
        "tz": tz,
    }
    try:
        from opscli.google_trends.domain.models import GoogleTrendsScenarioRequest
        from opscli.google_trends.services import GoogleTrendsApiManager

        parsed_params = _parse_json_arg(params, dict) or {}
        request = GoogleTrendsScenarioRequest(
            scenario=scenario,
            geo=geo,
            params=parsed_params,
            output_dir=output_dir,
            job_id=job_id,
            export_format=export_format,
            hl=hl,
            tz=tz,
        )
        result = await GoogleTrendsApiManager(jwt=jw, session_id=sid).run(request)
        return _ok(_public_result(result.to_dict()))
    except Exception as exc:
        return _err(exc, tool="MCP → google_trends_run(...)", call_params=call_params)


async def google_trends_job_status(job_id: str) -> dict:
    """读取 Google Trends 任务结果。"""
    try:
        from opscli.google_trends.services import GoogleTrendsApiManager

        return _ok(_public_result(GoogleTrendsApiManager().job_status(job_id)))
    except Exception as exc:
        return _err(exc, tool="MCP → google_trends_job_status(...)", call_params={"job_id": job_id})


async def google_trends_export(job_id: str) -> dict:
    """读取 Google Trends 任务导出文件信息。"""
    try:
        from opscli.google_trends.services import GoogleTrendsApiManager

        status = GoogleTrendsApiManager().job_status(job_id)
        export = _public_export_payload(status.get("export"))
        if not export.get("url"):
            raise ValueError(f"任务导出文件没有可下载地址：{job_id}")
        return _ok(export)
    except Exception as exc:
        return _err(exc, tool="MCP → google_trends_export(...)", call_params={"job_id": job_id})


_ALL_TOOLS = [
    google_trends_spec_must_read,
    google_trends_scenarios,
    google_trends_run,
    google_trends_job_status,
    google_trends_export,
]


def _public_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return MCP-safe task data without internal raw/params paths."""
    public = _strip_sensitive(payload)
    if isinstance(public, dict):
        public.pop("params_path", None)
        public.pop("raw_path", None)
        _sanitize_public_export(public)
        public["warnings"] = _public_warnings(public.get("warnings"))
    return public


def _sanitize_public_export(public: dict[str, Any]) -> None:
    export = public.get("export")
    if not isinstance(export, dict):
        return
    export.pop("path", None)
    url = export.get("url")
    if isinstance(url, str) and url.startswith("file://"):
        export["url"] = None
        url = None
    if url:
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
    payload = _strip_sensitive(export)
    if not isinstance(payload, dict):
        raise ValueError("任务导出结构不合法")
    payload.pop("path", None)
    url = payload.get("url")
    if isinstance(url, str) and url.startswith("file://"):
        payload["url"] = None
    return payload


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    if not isinstance(value, dict):
        return value
    blocked = {
        "raw_response",
        "request_params",
        "normalized_params",
        "response",
        "settings",
    }
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).replace("-", "_").lower()
        if normalized in blocked:
            continue
        result[key] = _strip_sensitive(item)
    return result


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
            warnings.append(
                {
                    "stage": stage,
                    "message": message or "导出文件上传失败，已保留服务端本地文件",
                }
            )
        elif message:
            warnings.append({"stage": stage, "message": message})
    return warnings


def register(mcp) -> None:
    """向 FastMCP 实例注册 Google Trends 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
