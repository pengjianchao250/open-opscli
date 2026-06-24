"""卖家精灵 MCP 工具模块。

将卖家精灵服务能力暴露为 MCP 工具：
- seller_sprite_spec_must_read — 读取卖家精灵 MCP 使用规范和参数手册
- seller_sprite_scenarios      — 列出卖家精灵场景
- seller_sprite_run            — 执行卖家精灵场景并导出 XLS/JSON
- seller_sprite_job_status     — 读取卖家精灵任务结果
- seller_sprite_export         — 读取卖家精灵任务导出文件信息
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.mcp.quota import get_quota_limiter

from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg

SELLER_SPRITE_RUN_POLL_INTERVAL_SECONDS = 5.0
SELLER_SPRITE_RUN_RUNNING_TIMEOUT_SECONDS = 8 * 60


def _seller_sprite_skill_dir() -> Path:
    """返回卖家精灵 Skill 模板目录。"""
    return Path(__file__).resolve().parents[2] / "skills" / "templates" / "ops-seller-sprite"


def _get_task_scheduler(*, jwt: str | None = None, session_id: str | None = None):
    """返回卖家精灵任务调度器。"""
    from opscli.seller_sprite.services import get_task_scheduler

    return get_task_scheduler(jwt=jwt, session_id=session_id)


def _get_task_queue_store():
    """返回卖家精灵任务队列仓储。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    return SellerSpriteTaskQueueStore()


def _get_current_mcp_user_email() -> str | None:
    """读取当前 MCP 请求对应的用户邮箱。"""
    from opscli.mcp.context import get_current_user_email

    return get_current_user_email()


def _build_request(
    *,
    scenario: str,
    params: dict[str, Any] | str | None,
    site: str,
    period: str,
    page_size: int,
    export_format: str,
    page_prepare: bool | None,
    task_interval_seconds: float | None,
    cooldown_seconds: float | None,
    output_dir: str | None,
    job_id: str | None,
):
    """构造卖家精灵场景请求对象。"""
    from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest

    parsed_params = _parse_json_arg(params, dict) or {}
    return SellerSpriteScenarioRequest(
        scenario=scenario,
        site=site,
        period=period,
        params=parsed_params,
        page_size=page_size,
        job_id=job_id,
        output_dir=output_dir,
        export_format=export_format,
        mode="browser-route",
        page_prepare=page_prepare,
        task_interval_seconds=task_interval_seconds,
        cooldown_seconds=cooldown_seconds,
    )


def _build_mcp_job_id(request, site: str, period: str) -> str:
    """为 MCP 入口生成最终 job_id。"""
    from opscli.seller_sprite.services.api_manager import _build_job_id

    return _build_job_id(request, site, period)


def _prepare_request_for_enqueue(request):
    """在 MCP 入口层完成 site、period 和 job_id 规范化。"""
    from opscli.seller_sprite.config import load_settings

    settings = load_settings()
    normalized_site = (request.site or settings.default_site).upper()
    normalized_period = request.period or settings.default_period
    normalized_job_id = request.job_id or _build_mcp_job_id(
        request, normalized_site, normalized_period
    )
    return replace(
        request,
        site=normalized_site,
        period=normalized_period,
        job_id=normalized_job_id,
    )


async def _wait_for_seller_sprite_run_result(
    *,
    scheduler,
    job_id: str,
    initial_status: dict[str, Any],
) -> dict[str, Any]:
    """等待公开 run 入口的最终可返回状态。"""
    status = dict(initial_status)
    while True:
        state = str(status.get("state") or "").strip().lower()
        if state in {"succeeded", "failed"}:
            return status

        now = datetime.now(timezone.utc).astimezone()
        if state == "running" and _running_timed_out(status, now=now):
            return _build_timeout_status(status, now=now)

        await asyncio.sleep(max(SELLER_SPRITE_RUN_POLL_INTERVAL_SECONDS, 0))
        status = dict(scheduler.job_status(job_id))


def _running_timed_out(status: dict[str, Any], *, now: datetime) -> bool:
    """判断任务是否已经超过运行态同步等待上限。"""
    started_at = _parse_status_time(status.get("started_at"))
    if started_at is None:
        return False
    return _duration_seconds(started_at, now) >= SELLER_SPRITE_RUN_RUNNING_TIMEOUT_SECONDS


def _build_timeout_status(status: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """在运行态超时后补充排队与运行时长摘要。"""
    payload = dict(status)
    created_at = _parse_status_time(status.get("created_at"))
    started_at = _parse_status_time(status.get("started_at"))

    payload["queue_duration"] = (
        _duration_seconds(created_at, started_at) if created_at and started_at else None
    )
    payload["running_duration"] = _duration_seconds(started_at, now) if started_at else None
    return payload


def _parse_status_time(value: Any) -> datetime | None:
    """解析状态里的 ISO 时间字符串。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _duration_seconds(start: datetime, end: datetime) -> int:
    """返回两个时间点之间的非负秒数。"""
    return max(0, int((end - start).total_seconds()))


async def seller_sprite_spec_must_read() -> dict:
    """读取卖家精灵 MCP 使用规范与参数手册。

    【首次使用提示】首次调用卖家精灵服务前，应先调用本工具读取完整规范，
    了解可用场景、参数格式、站点/周期约束、导出格式和任务查询流程。

    规范内容来自 opscli 内置 Skill 模板：
    - opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md
    - opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md

    Returns:
        {"success": true, "data": {"spec": "<Markdown 文档内容>", "source": "<主文件路径>", "sources": ["<文件路径>", ...]}}
        或 {"success": false, "error": "<错误原因>"}
    """
    skill_dir = _seller_sprite_skill_dir()
    spec_path = skill_dir / "SKILL_MCP.md"
    params_path = skill_dir / "SCENARIO_PARAMS_ZH.md"
    required_paths = [spec_path, params_path]

    for path in required_paths:
        if not path.exists():
            return _err(
                FileNotFoundError(
                    f"卖家精灵 MCP 规范文档不存在：{path}。请检查 opscli 安装是否完整。"
                ),
                tool="MCP → seller_sprite_spec_must_read()",
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
        return _err(exc, tool="MCP → seller_sprite_spec_must_read()")


async def seller_sprite_scenarios() -> dict:
    """列出卖家精灵场景。"""
    try:
        from opscli.seller_sprite.services import SellerSpriteApiManager

        return _ok(SellerSpriteApiManager().scenarios())
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_scenarios()")


async def seller_sprite_quota_status() -> dict:
    """读取当前 MCP 用户的卖家精灵每日额度快照。"""
    user_email = _get_current_mcp_user_email()
    if not user_email:
        return _err(
            ValueError("当前 MCP 用户邮箱缺失，无法读取卖家精灵额度"),
            tool="MCP → seller_sprite_quota_status()",
        )

    try:
        identity = f"email:{user_email.strip().lower()}"
        snapshot = get_quota_limiter().quota_snapshot("seller_sprite_run", identity)
        if inspect.isawaitable(snapshot):
            snapshot = await snapshot
        return _ok(snapshot)
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_quota_status()")


async def seller_sprite_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    period: str = "30d",
    page_size: int = 100,
    export_format: str = "xls",
    page_prepare: bool | None = None,
    task_interval_seconds: float | None = None,
    cooldown_seconds: float | None = None,
    output_dir: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """执行卖家精灵场景并导出 XLS/JSON。

    如果未提供 session_id / jwt，会自动尝试从当前 MCP 会话隔离凭证中加载。
    """
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(
            ValueError("无 session_id：请完成 OPS 授权，或传入有效的 session_id"),
            tool="MCP → seller_sprite_run(...)",
            call_params={
                "scenario": scenario,
                "site": site,
                "period": period,
                "page_size": page_size,
                "export_format": export_format,
                "page_prepare": page_prepare,
                "task_interval_seconds": task_interval_seconds,
                "cooldown_seconds": cooldown_seconds,
                "job_id": job_id,
            },
        )

    user_email = _get_current_mcp_user_email()
    if not user_email:
        return _err(
            ValueError("当前 MCP 用户邮箱缺失，无法创建卖家精灵调用记录"),
            tool="MCP → seller_sprite_run(...)",
            call_params={
                "scenario": scenario,
                "site": site,
                "period": period,
                "page_size": page_size,
                "export_format": export_format,
                "page_prepare": page_prepare,
                "task_interval_seconds": task_interval_seconds,
                "cooldown_seconds": cooldown_seconds,
                "job_id": job_id,
            },
        )

    created_job_id: str | None = None
    mcp_run_created = False
    try:
        raw_request = _build_request(
            scenario=scenario,
            params=params,
            site=site,
            period=period,
            page_size=page_size,
            export_format=export_format,
            page_prepare=page_prepare,
            task_interval_seconds=task_interval_seconds,
            cooldown_seconds=cooldown_seconds,
            output_dir=output_dir,
            job_id=job_id,
        )
        request = _prepare_request_for_enqueue(raw_request)
        created_job_id = str(request.job_id)
        store = _get_task_queue_store()
        scheduler = _get_task_scheduler(jwt=jw, session_id=sid)

        # 入队前先落一条 MCP 调用记录，确保调度失败时也能追踪。
        store.create_mcp_run(request, user_email)
        mcp_run_created = True
        queued_status = await scheduler.enqueue(request)
        return _ok(
            await _wait_for_seller_sprite_run_result(
                scheduler=scheduler,
                job_id=created_job_id,
                initial_status=queued_status,
            )
        )
    except Exception as exc:
        if mcp_run_created and created_job_id:
            try:
                from opscli.seller_sprite.services.task_status import error_to_dict

                _get_task_queue_store().finish_mcp_run_failed(created_job_id, error_to_dict(exc))
            except Exception:
                # 入口层保留原始入队异常，避免记录补偿失败覆盖主错误。
                pass
        return _err(
            exc,
            tool="MCP → seller_sprite_run(...)",
            call_params={
                "scenario": scenario,
                "site": site,
                "period": period,
                "page_size": page_size,
                "export_format": export_format,
                "page_prepare": page_prepare,
                "task_interval_seconds": task_interval_seconds,
                "cooldown_seconds": cooldown_seconds,
                "job_id": job_id,
            },
        )


async def seller_sprite_start(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    period: str = "30d",
    page_size: int = 100,
    export_format: str = "xls",
    page_prepare: bool | None = None,
    task_interval_seconds: float | None = None,
    cooldown_seconds: float | None = None,
    output_dir: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """创建卖家精灵异步任务并立即返回 job_id。"""
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(
            ValueError("无 session_id：请完成 OPS 授权，或传入有效的 session_id"),
            tool="MCP → seller_sprite_start(...)",
            call_params={
                "scenario": scenario,
                "site": site,
                "period": period,
                "page_size": page_size,
                "export_format": export_format,
                "job_id": job_id,
            },
        )

    try:
        request = _build_request(
            scenario=scenario,
            params=params,
            site=site,
            period=period,
            page_size=page_size,
            export_format=export_format,
            page_prepare=page_prepare,
            task_interval_seconds=task_interval_seconds,
            cooldown_seconds=cooldown_seconds,
            output_dir=output_dir,
            job_id=job_id,
        )
        scheduler = _get_task_scheduler(jwt=jw, session_id=sid)
        return _ok(await scheduler.enqueue(request))
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_start(...)",
            call_params={
                "scenario": scenario,
                "site": site,
                "period": period,
                "page_size": page_size,
                "export_format": export_format,
                "job_id": job_id,
            },
        )


async def seller_sprite_job_status(job_id: str) -> dict:
    """读取卖家精灵任务结果。"""
    try:
        return _ok(_get_task_scheduler().job_status(job_id))
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_job_status(...)", call_params={"job_id": job_id})


async def seller_sprite_export(job_id: str) -> dict:
    """读取卖家精灵任务导出文件信息。"""
    try:
        status = _get_task_scheduler().job_status(job_id)
        export = status.get("export")
        if not export:
            raise ValueError(f"任务无导出文件：{job_id}")
        if export.get("path") and not export.get("url"):
            export["url"] = Path(export["path"]).expanduser().resolve().as_uri()
        return _ok(export)
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_export(...)", call_params={"job_id": job_id})


_ALL_TOOLS = [
    seller_sprite_spec_must_read,
    seller_sprite_scenarios,
    seller_sprite_quota_status,
    seller_sprite_run,
    seller_sprite_job_status,
    seller_sprite_export,
]


def register(mcp) -> None:
    """向 FastMCP 实例注册卖家精灵工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
