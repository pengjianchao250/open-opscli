"""Keepa MCP 工具模块。

将 Keepa API 能力暴露为 MCP 工具：
- keepa_spec_must_read — 读取 Keepa MCP 使用规范
- keepa_scenarios      — 列出 Keepa 场景
- keepa_quota_status   — 读取 Keepa 每日额度快照
- keepa_run            — 执行 Keepa 场景并保存请求/响应/导出
- keepa_job_status     — 读取任务结果
- keepa_export         — 读取导出文件信息
- keepa_history        — 按历史任务 ID 或条件读取数据库沉淀
"""

from __future__ import annotations

import asyncio
import inspect
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from opscli.keepa.api.scenarios import (
    telemetry_dimensions as _keepa_telemetry_dimensions,
)
from opscli.keepa.summary import KEEPA_SUMMARY_ROW_LIMIT, summarize_rows
from opscli.mcp.quota import get_quota_limiter
from opscli.skills.packaging import get_builtin_templates_dir

from .export_fallback import attach_json_data_fallback, build_export_payload_with_fallback
from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg

_KEEPA_API_MODE: ContextVar[bool] = ContextVar("keepa_api_mode", default=False)


def _keepa_skill_dir() -> Path:
    """返回 Keepa Skill 模板目录。"""
    return get_builtin_templates_dir() / "ops-keepa"


def _get_current_mcp_user_email() -> str | None:
    """读取当前 MCP 请求对应的用户邮箱。"""
    from opscli.mcp.context import get_current_user_email

    return get_current_user_email()


def _load_keepa_settings():
    """读取 Keepa 运行配置。"""
    from opscli.keepa.config import load_settings

    return load_settings()


async def _try_auto_mcp_login() -> dict:
    """在 HTTP/SSE MCP 模式下尝试一步登录并缓存 session。"""
    from .auth import auth_mcp_login

    return await auth_mcp_login()


async def keepa_spec_must_read() -> dict:
    """读取 Keepa MCP 使用规范与官方参考。

    规范内容统一收口到 opscli 内置 Skill 模板：
    - opscli/skills/templates/ops-keepa/SKILL_MCP.md
    - opscli/skills/templates/ops-keepa/references/OFFICIAL.md
    """
    skill_dir = _keepa_skill_dir()
    spec_path = skill_dir / "SKILL_MCP.md"
    official_path = skill_dir / "references" / "OFFICIAL.md"
    required_paths = [spec_path, official_path]

    for path in required_paths:
        if not path.exists():
            return _err(
                FileNotFoundError(f"Keepa MCP 规范文档不存在：{path}。请检查 opscli 安装是否完整。"),
                tool="MCP → keepa_spec_must_read()",
            )
    try:
        content = "\n\n".join(path.read_text(encoding="utf-8") for path in required_paths)
        return _ok(
            {
                "spec": content,
                "source": str(spec_path),
                "sources": [str(path) for path in required_paths],
            }
        )
    except Exception as exc:
        return _err(exc, tool="MCP → keepa_spec_must_read()")


async def keepa_scenarios() -> dict:
    """列出 Keepa API 支持的接口场景。"""
    try:
        from opscli.keepa.services import KeepaApiManager

        return _ok(KeepaApiManager().scenarios())
    except Exception as exc:
        return _err(exc, tool="MCP → keepa_scenarios()")


async def keepa_quota_status() -> dict:
    """读取当前 MCP 用户的 Keepa 每日额度快照。"""
    user_email = _get_current_mcp_user_email()
    if not user_email:
        return _err(
            ValueError("当前 MCP 用户邮箱缺失，无法读取 Keepa 额度"),
            tool="MCP → keepa_quota_status()",
        )

    try:
        identity = f"email:{user_email.strip().lower()}"
        snapshot = get_quota_limiter().quota_snapshot("keepa_run", identity)
        if inspect.isawaitable(snapshot):
            snapshot = await snapshot
        return _ok(snapshot)
    except Exception as exc:
        return _err(exc, tool="MCP → keepa_quota_status()")


async def keepa_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    export_format: str = "xls",
    output_dir: str | None = None,
    job_id: str | None = None,
    reserve_tokens: int | None = None,
    force: bool = False,
    wait: bool = False,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """执行 Keepa 场景并保存请求参数、原始响应、规范化结果和 XLSX/JSON 导出。

    如果未提供 session_id / jwt，会自动尝试从当前 MCP 会话隔离凭证中加载。
    若无 OPS 登录态但设置了 OPSCLI_KEEPA_API_KEY，也可直接执行。
    """
    return await _keepa_run_impl(
        scenario=scenario,
        params=params,
        site=site,
        export_format=export_format,
        output_dir=output_dir,
        job_id=job_id,
        reserve_tokens=reserve_tokens,
        force=force,
        wait=wait,
        session_id=session_id,
        jwt=jwt,
        collection_submitter=None,
    )


setattr(keepa_run, "__opscli_telemetry_dimension_resolver__", _keepa_telemetry_dimensions)


async def _keepa_run_impl(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    export_format: str = "xls",
    output_dir: str | None = None,
    job_id: str | None = None,
    reserve_tokens: int | None = None,
    force: bool = False,
    wait: bool = False,
    session_id: str | None = None,
    jwt: str | None = None,
    collection_submitter=None,
) -> dict:
    """执行 Keepa，并允许 MCP Runtime 注入内部沉淀提交器。"""
    api_mode = _KEEPA_API_MODE.get()
    call_params = {
        "scenario": scenario,
        "site": site,
        "export_format": export_format,
        "reserve_tokens": reserve_tokens,
        "force": force,
        "wait": wait,
        "job_id": job_id,
    }
    try:
        export_format = _normalize_mcp_export_format(export_format)
        call_params["export_format"] = export_format
        sid, jw = _get_auth_pair("ops", session_id, jwt)
        keepa_settings = _load_keepa_settings()
        if not sid and not keepa_settings.api_key:
            login_result = await _try_auto_mcp_login()
            if login_result.get("success"):
                sid, jw = _get_auth_pair("ops", session_id, jwt)
            if not sid:
                login_error = (login_result.get("error") or {}).get("message")
                message = "无 session_id：请完成授权登录，或传入有效的 session_id"
                if login_error:
                    message = f"{message}。自动执行 auth_mcp_login 失败：{login_error}"
                raise ValueError(message)
        from opscli.keepa.domain.models import KeepaScenarioRequest
        from opscli.keepa.services import KeepaApiManager

        parsed_params = _parse_json_arg(params, dict) or {}
        request = KeepaScenarioRequest(
            scenario=scenario,
            site=site,
            params=parsed_params,
            output_dir=output_dir,
            job_id=job_id,
            export_format=export_format,
            reserve_tokens=reserve_tokens,
            force=force,
            wait=wait,
            upload_export=not api_mode,
        )
        manager_kwargs: dict[str, Any] = {"jwt": jw, "session_id": sid}
        if collection_submitter is not None:
            manager_kwargs["collection_submitter"] = collection_submitter
        result = await KeepaApiManager(**manager_kwargs).run(request)
        public_result = _public_api_result(result.to_dict()) if api_mode else _public_result(result.to_dict())
        return _ok(public_result)
    except ValueError as exc:
        return _err(exc, tool="MCP → keepa_run(...)", call_params=call_params, auto_feedback=False)
    except Exception as exc:
        return _err(exc, tool="MCP → keepa_run(...)", call_params=call_params)


async def keepa_job_status(job_id: str) -> dict:
    """读取 Keepa 任务结果。"""
    try:
        from opscli.keepa.services import KeepaApiManager

        return _ok(_public_result(KeepaApiManager().job_status(job_id)))
    except Exception as exc:
        return _err(exc, tool="MCP → keepa_job_status(...)", call_params={"job_id": job_id})


async def keepa_export(job_id: str) -> dict:
    """读取 Keepa 任务导出文件信息。"""
    try:
        from opscli.keepa.services import KeepaApiManager

        status = KeepaApiManager().job_status(job_id)
        public_status = _strip_sensitive(status)
        if not isinstance(public_status, dict):
            raise ValueError("任务导出结构不合法")
        export = _public_export_payload(build_export_payload_with_fallback(public_status))
        if not export.get("url") and "json_data" not in export:
            raise ValueError(f"任务导出文件没有可下载地址：{job_id}")
        return _ok(export)
    except Exception as exc:
        return _err(exc, tool="MCP → keepa_export(...)", call_params={"job_id": job_id})


async def keepa_history(
    job_id: str | None = None,
    scenario: str | None = None,
    site: str | None = None,
    params: dict[str, Any] | str | None = None,
    completed_after: str | None = None,
    completed_before: str | None = None,
    limit: int = 20,
    offset: int = 0,
    dataset_code: str | None = None,
    record_limit: int = 100,
    record_offset: int = 0,
    include_records: bool = True,
) -> dict:
    """读取已沉淀的 Keepa 历史任务和数据明细。

    可传 ``job_id`` 精确读取任务，也可按 ``scenario``、``site`` 和 params
    条件匹配历史任务。params 支持与 keepa_run 相同的参数别名，例如
    ``{"asin": "B0088PUEPK"}`` 或 ``{"keyword": "flashlight"}``。
    ``include_records=false`` 时只返回任务与 Dataset 摘要，适合历史列表；
    大任务可用 ``dataset_code``、``record_offset`` 和 ``record_limit`` 分页。
    """
    call_params = {
        "job_id": job_id,
        "scenario": scenario,
        "site": site,
        "params": params,
        "completed_after": completed_after,
        "completed_before": completed_before,
        "limit": limit,
        "offset": offset,
        "dataset_code": dataset_code,
        "record_limit": record_limit,
        "record_offset": record_offset,
        "include_records": include_records,
    }
    try:
        parsed_params = _parse_json_arg(params, dict) if params is not None else None
        normalized_scenario = str(scenario or "").strip().lower() or None
        normalized_site = str(site or "").strip().upper() or None
        if not any(
            str(value or "").strip()
            for value in (
                job_id,
                normalized_scenario,
                normalized_site,
                completed_after,
                completed_before,
            )
        ) and not parsed_params:
            raise ValueError("至少提供 job_id、scenario/site、params 或时间范围之一")
        normalized_params = _normalize_history_params(
            scenario=normalized_scenario,
            site=normalized_site,
            params=parsed_params,
        )
        call_params["scenario"] = normalized_scenario
        call_params["site"] = normalized_site
        call_params["normalized_params"] = normalized_params
        site_aliases = _history_site_aliases(normalized_site)
        from opscli.shared.collection_storage.config import load_storage_settings
        from opscli.shared.collection_storage.mysql_repository import (
            MySqlCollectionRepository,
        )

        settings = load_storage_settings("mcp")
        if not settings.enabled:
            raise ValueError("共享采集数据沉淀未启用，无法读取 Keepa 历史数据")
        repository = MySqlCollectionRepository(settings=settings.mysql)
        page = await asyncio.to_thread(
            repository.query_history_page,
            source_system="keepa",
            source_job_id=job_id,
            scenario=normalized_scenario,
            site=normalized_site,
            site_aliases=site_aliases,
            request_params=normalized_params,
            original_request_params=parsed_params,
            completed_after=completed_after,
            completed_before=completed_before,
            limit=limit,
            offset=offset,
            dataset_code=dataset_code,
            record_limit=record_limit,
            record_offset=record_offset,
            include_records=include_records,
        )
        return _ok(_public_history_result(page, call_params=call_params))
    except ValueError as exc:
        return _err(exc, tool="MCP → keepa_history(...)", call_params=call_params, auto_feedback=False)
    except Exception as exc:
        return _err(exc, tool="MCP → keepa_history(...)", call_params=call_params)


_ALL_TOOLS = [
    keepa_spec_must_read,
    keepa_scenarios,
    keepa_quota_status,
    keepa_run,
    keepa_job_status,
    keepa_export,
    keepa_history,
]


def _public_history_result(
    page: dict[str, Any],
    *,
    call_params: dict[str, Any],
) -> dict[str, Any]:
    """构造历史查询的稳定公开合同，不暴露账户、路径和内部 token。"""
    runs = page.get("runs")
    if not isinstance(runs, list):
        runs = []
    public_runs: list[dict[str, Any]] = []
    for run in runs:
        item = _strip_sensitive(run)
        if not isinstance(item, dict):
            continue
        request_payload = item.get("request_params")
        if isinstance(request_payload, dict):
            # 只返回用于匹配的 Keepa 参数，隐藏 params.json 中的请求/账户信息。
            item["request_params"] = request_payload.get("normalized_params") or {}
        public_runs.append(item)
    return {
        "query": _strip_sensitive(call_params),
        "found": bool(public_runs),
        "total": int(page.get("total") or 0),
        "run_count": len(public_runs),
        "limit": int(page.get("limit") or 0),
        "offset": int(page.get("offset") or 0),
        "has_more": bool(page.get("has_more")),
        "runs": public_runs,
    }


def _normalize_history_params(
    *,
    scenario: str | None,
    site: str | None,
    params: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """复用 Keepa 场景合同归一化历史查询条件。"""
    if not params:
        return None
    if not scenario:
        return params
    from opscli.keepa.api.scenarios import get_scenario

    normalized = get_scenario(scenario).build_params(
        params=params,
        site=site or "US",
    )
    if site is None:
        # 未限定站点时，不让默认 US domain 缩窄历史查询范围。
        normalized.pop("domain", None)
    return normalized


def _history_site_aliases(site: str | None) -> tuple[str, ...]:
    """返回同一 Keepa domain 的站点别名，兼容 GB/UK 和数字站点。"""
    if not site:
        return ()
    from opscli.keepa.api.scenarios import DOMAIN_CODES, normalize_domain

    domain = int(normalize_domain(site))
    aliases = [code for code, value in DOMAIN_CODES.items() if value == domain]
    aliases.append(str(domain))
    return tuple(dict.fromkeys(alias for alias in aliases if alias != site))


def _public_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return MCP-safe task data without Keepa account or quota internals."""
    public = _strip_sensitive(payload)
    if isinstance(public, dict):
        public.pop("quota", None)
        public.pop("account", None)
        public.pop("root_dir", None)
        public.pop("params_path", None)
        public.pop("raw_path", None)
        public.pop("result_path", None)
        attach_json_data_fallback(public)
        _sanitize_public_export(public)
        _compact_public_data(public)
        public["warnings"] = _public_warnings(public.get("warnings"))
    return public


def _public_api_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return REST-safe formatted rows without MCP preview compaction or upload metadata."""
    public = _strip_sensitive(payload)
    if not isinstance(public, dict):
        return {}
    public.pop("quota", None)
    public.pop("account", None)
    public.pop("root_dir", None)
    public.pop("params_path", None)
    public.pop("raw_path", None)
    public.pop("result_path", None)
    public.pop("export", None)
    public["request_source"] = "api"
    public["response_mode"] = "formatted_data"
    public["warnings"] = _public_warnings(public.get("warnings"))
    return public


def _normalize_mcp_export_format(value: str) -> str:
    """校验 MCP 对外导出格式。"""
    text = (value or "").strip().lower()
    if text in {"", "xls", "xlsx"}:
        return "xls"
    if text == "json":
        return "json"
    raise ValueError(f"不支持的导出格式：{value}。Keepa MCP 当前支持 xls/xlsx/json 导出。")


def _sanitize_public_export(public: dict[str, Any]) -> None:
    export = public.get("export")
    if not isinstance(export, dict):
        return
    export.pop("path", None)
    url = export.get("url")
    if isinstance(url, str) and url.startswith("file://"):
        export["url"] = None
        url = None
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
    payload = _strip_sensitive(export)
    if not isinstance(payload, dict):
        raise ValueError("任务导出结构不合法")
    payload.pop("path", None)
    url = payload.get("url")
    if isinstance(url, str) and url.startswith("file://"):
        payload["url"] = None
    return payload


def _compact_public_data(public: dict[str, Any]) -> None:
    data = public.get("data")
    if not isinstance(data, list):
        return
    scenario = public.get("scenario")
    preview_rows = summarize_rows(
        data,
        limit=KEEPA_SUMMARY_ROW_LIMIT,
        scenario=scenario if isinstance(scenario, str) else None,
    )
    public["data_preview"] = preview_rows
    row_count = public.get("row_count")
    total_rows = row_count if isinstance(row_count, int) else len(data)
    public["data_omitted"] = max(0, total_rows - len(preview_rows))
    public.pop("data", None)
    warnings = public.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings.append(
        {
            "stage": "mcp_response_compact",
            "message": "MCP 响应仅保留少量字段摘要，请通过 export.url 对应的 JSON/XLSX 导出文件查看完整数据。",
        }
    )
    public["warnings"] = warnings
def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    if not isinstance(value, dict):
        return value
    blocked = {
        "api_key",
        "apikey",
        "token",
        "tokensleft",
        "tokensconsumed",
        "tokenflowreduction",
        "estimated_tokens",
        "reserve_tokens",
        "tokens_left",
        "refill_in_ms",
        "refill_rate",
        "refillin",
        "refillrate",
        "before_quota",
        "before_status",
        "after_status",
        "raw_response",
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
        if stage in {"quota_precheck", "quota_wait"}:
            warnings.append(
                {
                    "stage": stage,
                    "message": "Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。",
                }
            )
        elif stage == "file_upload":
            warnings.append(
                {
                    "stage": stage,
                    "message": item.get("message") or "导出文件上传失败，已保留服务端本地文件",
                }
            )
        else:
            message = item.get("message")
            if message:
                warnings.append({"stage": stage, "message": message})
    return warnings


def register(mcp) -> None:
    """向 FastMCP 实例注册 Keepa 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
