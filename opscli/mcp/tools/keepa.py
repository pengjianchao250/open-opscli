"""Keepa MCP 工具模块。

将 Keepa API 能力暴露为 MCP 工具：
- keepa_spec_must_read — 读取 Keepa MCP 使用规范
- keepa_scenarios      — 列出 Keepa 场景
- keepa_quota_status   — 读取 Keepa 每日额度快照
- keepa_run            — 执行 Keepa 场景并保存请求/响应/导出
- keepa_job_status     — 读取任务结果
- keepa_export         — 读取导出文件信息
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from opscli.mcp.quota import get_quota_limiter
from opscli.skills.packaging import get_builtin_templates_dir

from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg

MAX_PUBLIC_DATA_PREVIEW_ROWS = 5
PUBLIC_DATA_PREVIEW_FIELDS = (
    "asin",
    "title",
    "brand",
    "sellerId",
    "sellerName",
    "categoryId",
    "catId",
    "name",
    "dealId",
    "dealState",
    "totalResults",
    "bestSellerRank",
)


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
        )
        manager_kwargs: dict[str, Any] = {"jwt": jw, "session_id": sid}
        if collection_submitter is not None:
            manager_kwargs["collection_submitter"] = collection_submitter
        result = await KeepaApiManager(**manager_kwargs).run(request)
        return _ok(_public_result(result.to_dict()))
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
        export = _public_export_payload(status.get("export"))
        if not export.get("url"):
            raise ValueError(f"任务导出文件没有可下载地址：{job_id}")
        return _ok(export)
    except Exception as exc:
        return _err(exc, tool="MCP → keepa_export(...)", call_params={"job_id": job_id})


_ALL_TOOLS = [
    keepa_spec_must_read,
    keepa_scenarios,
    keepa_quota_status,
    keepa_run,
    keepa_job_status,
    keepa_export,
]


def _public_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return MCP-safe task data without Keepa account or quota internals."""
    public = _strip_sensitive(payload)
    if isinstance(public, dict):
        public.pop("quota", None)
        public.pop("account", None)
        public.pop("params_path", None)
        public.pop("raw_path", None)
        _sanitize_public_export(public)
        _compact_public_data(public)
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


def _compact_public_data(public: dict[str, Any]) -> None:
    data = public.get("data")
    if not isinstance(data, list):
        return
    preview_rows = data[:MAX_PUBLIC_DATA_PREVIEW_ROWS]
    public["data_preview"] = [_public_data_preview(row) for row in preview_rows]
    public["data_omitted"] = max(0, len(data) - len(preview_rows))
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


def _public_data_preview(row: Any) -> Any:
    """只保留 Agent 判断结果所需的稳定标识字段，避免嵌套明细进入上下文。"""
    if not isinstance(row, dict):
        return row
    return {
        field: row[field]
        for field in PUBLIC_DATA_PREVIEW_FIELDS
        if field in row and not isinstance(row[field], (dict, list))
    }


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
