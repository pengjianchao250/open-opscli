"""卖家精灵 MCP 工具模块。

将卖家精灵服务能力暴露为 MCP 工具：
- seller_sprite_spec_must_read — 读取卖家精灵 MCP 使用规范和参数手册
- seller_sprite_scenarios      — 列出卖家精灵场景
- seller_sprite_run            — 执行卖家精灵场景并导出 XLS/JSON
- seller_sprite_job_status     — 读取单个卖家精灵任务结果
- seller_sprite_jobs_status    — 批量读取普通卖家精灵任务结果
- seller_sprite_export         — 读取卖家精灵任务导出文件信息
"""

from __future__ import annotations

import inspect
from asyncio import sleep as _status_wait_sleep
from dataclasses import replace
from pathlib import Path
from time import monotonic as _status_wait_monotonic
from typing import Any

from opscli.mcp.ops_credentials import (
    OpsCredentialBinding,
    ensure_ops_credentials,
)
from opscli.mcp.quota import get_quota_limiter

from .helpers import _err, _ok, _parse_json_arg

# 状态接口单次等待最多 30 秒，避免 MCP 请求长期占用连接。
SELLER_SPRITE_STATUS_MAX_WAIT_SECONDS = 30
# 状态轮询固定最多间隔 5 秒，并在最后一次等待时服从剩余时限。
SELLER_SPRITE_STATUS_POLL_INTERVAL_SECONDS = 5
# 当前持久队列只使用 succeeded 和 failed 两种终态。
SELLER_SPRITE_TERMINAL_STATES = frozenset({"succeeded", "failed"})


def _seller_sprite_skill_dir() -> Path:
    """返回卖家精灵 Skill 模板目录。"""
    return Path(__file__).resolve().parents[2] / "skills" / "templates" / "ops-seller-sprite"


def _get_task_scheduler():
    """返回卖家精灵任务调度器。"""
    from opscli.seller_sprite.mcp_bundle import require_ready
    from opscli.seller_sprite.services import get_task_scheduler

    require_ready()
    return get_task_scheduler()


def _get_task_queue_store():
    """返回卖家精灵任务队列仓储。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    return SellerSpriteTaskQueueStore()


def _get_account_binding_store():
    """返回卖家精灵用户专属账号绑定仓储。"""
    from opscli.seller_sprite.services.account_bindings import (
        SellerSpriteAccountBindingStore,
    )

    return SellerSpriteAccountBindingStore()


async def _enqueue_task_with_auth(
    scheduler: Any,
    request: Any,
    *,
    binding: OpsCredentialBinding,
) -> dict[str, Any]:
    """按可信凭证和额度切面确认的账号路由提交任务。"""
    from opscli.mcp.quota import get_quota_access_context
    from opscli.seller_sprite.services.task_queue_store import (
        ACCOUNT_ROUTE_USER_BINDING,
    )

    access_context = get_quota_access_context()
    dedicated = bool(access_context and access_context.mode == "unlimited")
    if dedicated and (
        access_context.user_email != binding.user_email
        or not access_context.account_id
        or not access_context.account_key
    ):
        raise ValueError("卖家精灵专属账号访问上下文与当前用户不一致")
    kwargs: dict[str, Any] = {
        "credential_scope": binding.credential_scope,
        "expected_user_email": binding.user_email,
        "mcp_user_email": binding.user_email,
    }
    if dedicated:
        kwargs.update(
            {
                "account_route": ACCOUNT_ROUTE_USER_BINDING,
                "requested_account_id": access_context.account_id,
                "requested_account_key": access_context.account_key,
            }
        )
    if binding.runtime_auth is not None:
        kwargs["session_id"], kwargs["jwt"] = binding.runtime_auth
    return await scheduler.enqueue(request, **kwargs)




def _get_current_mcp_user_email() -> str | None:
    """通过共享认证解析器读取当前 MCP 用户邮箱。"""
    from opscli.mcp.tools.helpers import _get_authenticated_user_email

    return _get_authenticated_user_email()


def _is_remote_mcp_request() -> bool:
    """判断当前 Tool 是否由 HTTP/SSE API Key 请求触发。"""
    from opscli.mcp.context import get_current_api_key

    return bool(get_current_api_key())


def _validate_output_dir(output_dir: str | None) -> None:
    """禁止远端调用方把客户端路径解释为服务器输出目录。"""
    if output_dir and _is_remote_mcp_request():
        raise ValueError("HTTP/SSE 模式不接受 output_dir，导出目录由数据采集服务统一管理")


def _sanitize_export(export: dict[str, Any]) -> dict[str, Any]:
    """远端仅返回 HTTPS 导出地址，stdio 保留本地文件兼容行为。"""
    normalized = dict(export)
    if not _is_remote_mcp_request():
        if normalized.get("path") and not normalized.get("url"):
            normalized["url"] = Path(normalized["path"]).expanduser().resolve().as_uri()
        return normalized

    url = str(normalized.get("url") or "").strip()
    if not url.lower().startswith("https://"):
        raise ValueError("导出文件尚未上传到 HTTPS 地址，请稍后重试")
    normalized.pop("path", None)
    normalized["url"] = url
    return normalized


def _sanitize_status(status: dict[str, Any]) -> dict[str, Any]:
    """移除远端任务状态中的服务器路径并校验成功态导出地址。"""
    normalized = dict(status)
    if not _is_remote_mcp_request():
        return normalized
    export = normalized.get("export")
    if isinstance(export, dict):
        normalized["export"] = _sanitize_export(export)
    for key in (
        "root_dir",
        "params_path",
        "raw_path",
        "result_path",
        "attempt_output_dir",
    ):
        normalized.pop(key, None)
    return normalized


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


def _extract_listing_analysis_task_id(status: dict[str, Any]) -> str | None:
    """从本地任务状态或结果行中提取 SellerSprite AI taskId。"""
    for row in status.get("data") or status.get("rows") or []:
        if not isinstance(row, dict):
            continue
        task_id = row.get("taskId") or row.get("task_id")
        if task_id:
            return str(task_id)
    response = ((status.get("raw") or {}).get("response") or {}) if isinstance(status.get("raw"), dict) else {}
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        task_id = data.get("taskId") or data.get("task_id")
        if task_id:
            return str(task_id)
    return None


def _extract_listing_analysis_asin(status: dict[str, Any], owner_record: dict[str, Any] | None = None) -> str | None:
    """从本地状态或 MCP 调用记录中提取 Listing Analysis ASIN。"""
    for row in status.get("data") or status.get("rows") or []:
        if isinstance(row, dict) and row.get("asin"):
            return str(row["asin"]).strip().upper()
    response = ((status.get("raw") or {}).get("response") or {}) if isinstance(status.get("raw"), dict) else {}
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict) and data.get("asin"):
        return str(data["asin"]).strip().upper()
    params = owner_record.get("params_json") if isinstance(owner_record, dict) else None
    if isinstance(params, dict) and params.get("asin"):
        return str(params["asin"]).strip().upper()
    return None


def _select_listing_analysis_history_item(response: dict[str, Any], *, asin: str) -> dict[str, Any] | None:
    """从历史任务列表中选择匹配 ASIN 的 Listing Analysis 任务。"""
    data = response.get("data") if isinstance(response, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    asin_text = str(asin or "").strip().upper()
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("module") or "").strip().upper() != "LA":
            continue
        title = str(item.get("tabTitle") or item.get("aliasTitle") or "").upper()
        if asin_text and asin_text not in title:
            continue
        return item
    return None


def _listing_analysis_analyzing(response: dict[str, Any]) -> bool:
    """判断 Listing Analysis 报告页是否仍在分析中。"""
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False
    status = str(data.get("taskStatus") or data.get("status") or "").strip().upper()
    return bool(data.get("analyzing") is True or status in {"RUNNING", "PENDING", "PROCESSING", "ANALYZING"})


def _listing_analysis_ready(response: dict[str, Any]) -> bool:
    """判断 Listing Analysis 远端任务是否已经返回可消费内容。"""
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False
    if _listing_analysis_analyzing(response) or _listing_analysis_failed(response):
        return False
    if data.get("content") or data.get("htmlContent"):
        return True
    return bool(data and not (data.get("taskId") and len(data) <= 4))


def _listing_analysis_failed(response: dict[str, Any]) -> bool:
    """判断 Listing Analysis 远端任务是否失败。"""
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False
    status = str(data.get("taskStatus") or data.get("status") or "").strip().lower()
    return status in {"failed", "fail", "error", "canceled", "cancelled"}


def _validate_seller_sprite_job_owner_record(
    job_id: str,
    record: dict[str, Any],
    user_email: str,
    expected_scenario: str | None = None,
) -> dict[str, Any]:
    """校验已读取的任务记录所有者与可选场景，不负责访问队列仓储。"""
    owner_email = str(record.get("user_email") or "").strip().lower()
    if not owner_email:
        raise ValueError(f"卖家精灵任务所有者邮箱缺失：{job_id}")
    if owner_email != user_email:
        raise PermissionError(f"无权读取卖家精灵任务：{job_id}")
    if expected_scenario is not None:
        scenario = str(record.get("scenario") or "listing-analysis")
        if scenario != expected_scenario:
            if expected_scenario == "listing-analysis":
                raise ValueError(f"任务不是 Listing Analysis：{job_id}")
            raise ValueError(f"任务场景不匹配：{job_id}")
    return record


def _ensure_seller_sprite_job_owner(
    job_id: str,
    expected_scenario: str | None = None,
) -> dict[str, Any]:
    """确认当前 MCP 用户是指定任务所有者，并可选校验任务场景。"""
    user_email = str(_get_current_mcp_user_email() or "").strip().lower()
    if not user_email:
        raise ValueError("当前 MCP 用户邮箱缺失，无法读取卖家精灵任务")
    record = _get_task_queue_store().get_mcp_run(job_id)
    return _validate_seller_sprite_job_owner_record(
        job_id,
        record,
        user_email,
        expected_scenario,
    )


def _ensure_listing_analysis_job_owner(job_id: str) -> dict[str, Any]:
    """确认当前 MCP 用户有权读取 Listing Analysis 任务且场景匹配。"""
    return _ensure_seller_sprite_job_owner(job_id, expected_scenario="listing-analysis")


def _get_listing_analysis_account_binding(job_id: str, status: dict[str, Any]) -> dict[str, str | None]:
    """读取 Listing Analysis 执行账号绑定，并兼容未实现绑定接口的旧仓储替身。"""
    store = _get_task_queue_store()
    getter = getattr(store, "get_task_account_binding", None)
    if callable(getter):
        return getter(job_id)
    return {
        "assigned_account": status.get("assigned_account"),
        "assigned_account_key": status.get("assigned_account_key"),
        "account_route": None,
        "requested_account_id": None,
        "requested_account_key": None,
    }


def _resolve_listing_analysis_account(manager: Any, binding: dict[str, str | None] | None):
    """按持久化绑定恢复原账号，无法唯一确认时禁止回退到其他账号。"""
    from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError
    from opscli.seller_sprite.services.account_pool import seller_sprite_account_key
    from opscli.seller_sprite.services.task_queue_store import (
        ACCOUNT_ROUTE_USER_BINDING,
    )

    account_route = str((binding or {}).get("account_route") or "").strip()
    if account_route == ACCOUNT_ROUTE_USER_BINDING:
        account_id = str((binding or {}).get("requested_account_id") or "").strip()
        expected_key = str(
            (binding or {}).get("requested_account_key")
            or (binding or {}).get("assigned_account_key")
            or ""
        ).strip()
        if not account_id or not expected_key:
            raise SellerSpriteConfigError(
                "Listing Analysis 专属账号任务缺少可确认的账号绑定"
            )
        dedicated = _get_account_binding_store().get_account(account_id)
        if dedicated is None:
            raise SellerSpriteConfigError("Listing Analysis 专属账号已不可用")
        account = dedicated.to_account()
        if seller_sprite_account_key(account) != expected_key:
            raise SellerSpriteConfigError("Listing Analysis 专属账号绑定已变更")
        return account

    provider = manager.account_provider
    list_accounts = getattr(provider, "list_accounts", None)
    if not callable(list_accounts):
        # 兼容只提供单账号接口的旧式 provider。
        return provider.get_default()

    accounts = list_accounts()
    assigned_key = str((binding or {}).get("assigned_account_key") or "").strip()
    assigned_name = str((binding or {}).get("assigned_account") or "").strip()
    if assigned_key:
        for account in accounts:
            if seller_sprite_account_key(account) == assigned_key:
                return account
        raise SellerSpriteConfigError(f"Listing Analysis 绑定账号已不可用：{assigned_name or assigned_key[:12]}")

    if assigned_name:
        matches = [account for account in accounts if account.name.strip().casefold() == assigned_name.casefold()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise SellerSpriteConfigError(f"Listing Analysis 历史任务账号名称不唯一：{assigned_name}")

    if len(accounts) == 1:
        return accounts[0]
    raise SellerSpriteConfigError("Listing Analysis 历史任务缺少可确认的账号绑定，禁止在多账号间自动续查")


def _listing_analysis_failure_payload(status: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    """构造 Listing Analysis 远端失败状态。"""
    response = remote.get("remote") if isinstance(remote.get("remote"), dict) else {}
    data = response.get("data") if isinstance(response, dict) else None
    message = "Listing Analysis 远端 AI 任务失败"
    remote_status = ""
    if isinstance(data, dict):
        remote_status = str(data.get("taskStatus") or data.get("status") or "")
        message = str(data.get("message") or data.get("msg") or data.get("error") or message)
    error_payload = {
        "code": "SELLER_SPRITE_LISTING_ANALYSIS_FAILED",
        "message": message,
        "task_id": remote.get("task_id"),
        "task_status": remote_status,
    }
    payload = {**status, **remote}
    payload.update(
        {
            "state": "failed",
            "stage": "failed",
            "ready": False,
            "failed": True,
            "error": error_payload,
        }
    )
    return payload


def _mark_listing_analysis_remote_failed(job_id: str, status: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    """将 Listing Analysis 远端失败同步回本地队列和 MCP 记录。"""
    payload = _listing_analysis_failure_payload(status, remote)
    error_payload = payload["error"]
    store = _get_task_queue_store()
    store.fail_task(job_id=job_id, error_payload=error_payload)
    store.finish_mcp_run_failed(job_id, error_payload)
    return payload


async def _fetch_listing_analysis_history_status(
    *,
    asin: str,
    session_id: str | None,
    jwt: str | None,
    account_binding: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """通过历史任务接口读取 Listing Analysis 任务状态。"""
    from opscli.seller_sprite.api.client import SellerSpriteApiClient
    from opscli.seller_sprite.services import SellerSpriteApiManager
    from opscli.seller_sprite.services.api_manager import _request_with_session_retry

    manager = SellerSpriteApiManager(jwt=jwt, session_id=session_id)
    account = _resolve_listing_analysis_account(manager, account_binding)
    async with SellerSpriteApiClient(account=account) as client:
        if not client.has_login_cookies():
            await client.login()
        # Cookie 名存在不代表服务端 Session 仍有效，过期时重新登录并仅重试一次。
        response = await _request_with_session_retry(
            client=client,
            warnings=[],
            stage="listing_analysis_history",
            action=lambda: client.get_json(
                "/v3/api/ai-analysis/task/history",
                {"page": 1, "pageSize": 20, "keywords": "", "modules": ""},
                referer="https://www.sellersprite.com/v3/ai-history?module=LA",
            ),
        )
    item = _select_listing_analysis_history_item(response, asin=asin)
    task_status = str((item or {}).get("taskStatus") or "").strip().upper()
    task_id = str((item or {}).get("taskId") or "").strip() or None
    return {
        "task_id": task_id,
        "ready": task_status in {"COMPLETED", "COMPLETE", "SUCCESS", "SUCCEEDED", "FINISHED", "DONE"},
        "failed": task_status in {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "EXPIRED"},
        "remote_status": task_status,
        "history_item": item,
        "remote": response,
    }


async def _fetch_listing_analysis_report_result(
    *,
    task_id: str,
    session_id: str | None,
    jwt: str | None,
    account_binding: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """通过 browser-route 报告详情页读取 Listing Analysis 最终结果。"""
    from opscli.seller_sprite.browser_route import fetch_listing_analysis_report_with_browser_route
    from opscli.seller_sprite.config import load_settings
    from opscli.seller_sprite.services import SellerSpriteApiManager

    settings = load_settings()
    manager = SellerSpriteApiManager(settings=settings, jwt=jwt, session_id=session_id)
    account = _resolve_listing_analysis_account(manager, account_binding)
    root_dir = settings.output_dir / f"listing-analysis-report-{task_id}"
    browser_result = await fetch_listing_analysis_report_with_browser_route(
        settings=settings,
        account=account,
        task_id=task_id,
        root_dir=root_dir,
    )
    response = browser_result.response
    return {
        "task_id": task_id,
        "ready": _listing_analysis_ready(response),
        "failed": _listing_analysis_failed(response),
        "analyzing": _listing_analysis_analyzing(response),
        "remote": response,
        "warnings": browser_result.warnings,
        "login": browser_result.login,
    }


async def _fetch_listing_analysis_remote_status(
    *,
    task_id: str,
    session_id: str | None,
    jwt: str | None,
    account_binding: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """兼容旧测试的 Listing Analysis 远端状态读取入口。"""
    return await _fetch_listing_analysis_report_result(
        task_id=task_id,
        session_id=session_id,
        jwt=jwt,
        account_binding=account_binding,
    )


def _persist_listing_analysis_remote_result(
    *,
    job_id: str,
    status: dict[str, Any],
    remote: dict[str, Any],
    export_format: str,
    session_id: str | None,
    jwt: str | None,
) -> dict[str, Any]:
    """将 Listing Analysis 远端完成结果写回本地结果和导出文件。"""
    from opscli.seller_sprite.config import load_settings
    from opscli.seller_sprite.domain.models import SellerSpriteScenarioResult
    from opscli.seller_sprite.export.xlsx import export_rows_to_xlsx
    from opscli.seller_sprite.services.api_manager import (
        _export_output_path,
        _export_rows_to_json,
        _extract_items,
        _normalize_export_format,
        _upload_export_if_enabled,
        _write_json,
    )

    response = remote.get("remote") if isinstance(remote.get("remote"), dict) else {}
    rows = _extract_items(response, scenario="listing-analysis")
    settings = load_settings()
    root_dir = Path(str(status.get("root_dir") or (settings.output_dir / job_id))).expanduser().resolve()
    site = str(status.get("site") or "US")
    period = str(status.get("period") or "30d")
    params_path = root_dir / "params.json"
    raw_path = root_dir / "remote-result-raw.json"
    result_path = root_dir / "result.json"
    warnings = list(status.get("warnings") or [])

    _write_json(
        raw_path,
        {
            "job_id": job_id,
            "scenario": "listing-analysis",
            "remote_task_id": remote.get("task_id"),
            "response": response,
            "previous_status": status,
        },
    )
    export_kind = _normalize_export_format(export_format)
    if export_kind == "xlsx":
        export = export_rows_to_xlsx(
            rows=rows,
            output_path=_export_output_path(root_dir, job_id, "xlsx"),
            scenario="listing-analysis",
            site=site,
            period=period,
            params={},
        )
    else:
        export = _export_rows_to_json(
            output_path=_export_output_path(root_dir, job_id, "json"),
            job_id=job_id,
            scenario="listing-analysis",
            site=site,
            period=period,
            rows=rows,
            high_frequency_rows=[],
            warnings=warnings,
        )
    _upload_export_if_enabled(
        export=export,
        job_id=job_id,
        scenario="listing-analysis",
        site=site,
        period=period,
        warnings=warnings,
        jwt=jwt,
        session_id=session_id,
    )
    result = SellerSpriteScenarioResult(
        job_id=job_id,
        scenario="listing-analysis",
        site=site,
        period=period,
        row_count=len(rows),
        root_dir=str(root_dir),
        params_path=str(params_path),
        raw_path=str(raw_path),
        result_path=str(result_path),
        export=export,
        data=rows,
        warnings=warnings,
    )
    payload = result.to_dict()
    payload["ready"] = True
    payload["task_id"] = remote.get("task_id")
    payload["remote"] = response
    _write_json(result_path, payload)

    store = _get_task_queue_store()
    export_payload = export.to_dict()
    store.finish_task(
        job_id=job_id,
        result_path=str(result_path),
        row_count=len(rows),
        export_payload=export_payload,
    )
    store.finish_mcp_run_success(job_id, len(rows), export_payload)
    return payload


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


async def _wait_for_preauthorized_seller_sprite_job_statuses(
    *,
    scheduler,
    job_ids: list[str],
    wait_seconds: int,
) -> list[dict[str, Any]]:
    """读取已完成完整集合预授权的任务状态；本原语不执行授权。"""
    statuses = [dict(scheduler.job_status(job_id)) for job_id in job_ids]
    bounded_wait = max(0, min(int(wait_seconds), SELLER_SPRITE_STATUS_MAX_WAIT_SECONDS))
    if bounded_wait == 0 or all(
        str(status.get("state") or "").strip().lower() in SELLER_SPRITE_TERMINAL_STATES
        for status in statuses
    ):
        return statuses

    # 状态查询只观察既有持久任务；正数等待不得取得或改变 scheduler 生命周期。
    deadline = _status_wait_monotonic() + bounded_wait
    while True:
        remaining = deadline - _status_wait_monotonic()
        if remaining <= 0:
            return statuses
        await _status_wait_sleep(min(SELLER_SPRITE_STATUS_POLL_INTERVAL_SECONDS, remaining))
        # 休眠可能晚于预期恢复；超过截止点时禁止再读取，避免到期后访问 scheduler。
        if _status_wait_monotonic() > deadline:
            return statuses
        statuses = [dict(scheduler.job_status(job_id)) for job_id in job_ids]
        if all(
            str(status.get("state") or "").strip().lower() in SELLER_SPRITE_TERMINAL_STATES
            for status in statuses
        ):
            return statuses


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

    HTTP/SSE 模式按 X-MCP-API-Key 自动确保隔离 OPS 凭证；旧客户端传入的
    session_id / jwt 仅保留参数兼容并会被忽略。stdio 模式继续兼容本机凭证。
    """
    try:
        _validate_output_dir(output_dir)
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_run(...)",
            call_params={"scenario": scenario, "job_id": job_id},
        )

    # Listing Analysis 有独立的三段式入口，必须在认证和队列副作用前拒绝通用提交。
    if str(scenario or "").strip().lower() == "listing-analysis":
        return _err(
            ValueError(
                "seller_sprite_run 不接受 listing-analysis；"
                "请改用 seller_sprite_listing_analysis_submit"
            ),
            tool="MCP → seller_sprite_run(...)",
            call_params={"scenario": scenario, "job_id": job_id},
        )

    try:
        binding = await ensure_ops_credentials(
            provided_session=session_id,
            provided_jwt=jwt,
        )
    except Exception as exc:
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
        scheduler = _get_task_scheduler()
        queued_status = await _enqueue_task_with_auth(
            scheduler,
            request,
            binding=binding,
        )
        return _ok(_sanitize_status(queued_status))
    except Exception as exc:
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
    try:
        binding = await ensure_ops_credentials(
            provided_session=session_id,
            provided_jwt=jwt,
        )
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
        scheduler = _get_task_scheduler()
        return _ok(
            await _enqueue_task_with_auth(
                scheduler,
                request,
                binding=binding,
            )
        )
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


async def seller_sprite_listing_analysis_submit(
    asin: str,
    station: str = "GLOBAL",
    site: str = "US",
    export_format: str = "json",
    page_prepare: bool | None = None,
    task_interval_seconds: float | None = None,
    cooldown_seconds: float | None = None,
    output_dir: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """提交 Listing Analysis AI 任务并立即返回本地 job_id。"""
    try:
        _validate_output_dir(output_dir)
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_listing_analysis_submit(...)",
            call_params={"asin": asin, "station": station, "site": site, "job_id": job_id},
        )

    try:
        binding = await ensure_ops_credentials(
            provided_session=session_id,
            provided_jwt=jwt,
        )
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_listing_analysis_submit(...)",
            call_params={"asin": asin, "station": station, "site": site, "job_id": job_id},
        )
    parsed_asin = str(asin or "").strip().upper()
    parsed_station = str(station or "GLOBAL").strip().upper()
    if not parsed_asin:
        return _err(
            ValueError("listing-analysis 必须提供 asin"),
            tool="MCP → seller_sprite_listing_analysis_submit(...)",
            call_params={"asin": asin, "station": station, "site": site, "job_id": job_id},
        )

    try:
        raw_request = _build_request(
            scenario="listing-analysis",
            params={"asin": parsed_asin, "station": parsed_station},
            site=site,
            period="30d",
            page_size=1,
            export_format=export_format,
            page_prepare=page_prepare,
            task_interval_seconds=task_interval_seconds,
            cooldown_seconds=cooldown_seconds,
            output_dir=output_dir,
            job_id=job_id,
        )
        request = _prepare_request_for_enqueue(raw_request)
        scheduler = _get_task_scheduler()
        return _ok(
            await _enqueue_task_with_auth(
                scheduler,
                request,
                binding=binding,
            )
        )
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_listing_analysis_submit(...)",
            call_params={"asin": asin, "station": station, "site": site, "job_id": job_id},
        )


async def seller_sprite_listing_analysis_status(
    job_id: str,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """读取 Listing Analysis 本地提交状态，并在可用时续查远端任务状态。"""
    try:
        owner_record = _ensure_listing_analysis_job_owner(job_id)
        binding = await ensure_ops_credentials(
            provided_session=session_id,
            provided_jwt=jwt,
        )
        sid, jw = binding.session_id, binding.jwt
        status = dict(_get_task_scheduler().job_status(job_id))
        account_binding = _get_listing_analysis_account_binding(job_id, status)
        if status.get("state") == "queued" and not account_binding.get(
            "assigned_account_key"
        ):
            status["ready"] = False
            return _ok(_sanitize_status(status))
        task_id = _extract_listing_analysis_task_id(status)
        asin = _extract_listing_analysis_asin(status, owner_record)
        if asin:
            remote = await _fetch_listing_analysis_history_status(
                asin=asin,
                session_id=sid,
                jwt=jw,
                account_binding=account_binding,
            )
        elif task_id:
            remote = await _fetch_listing_analysis_remote_status(
                task_id=task_id,
                session_id=sid,
                jwt=jw,
                account_binding=account_binding,
            )
        else:
            status["ready"] = False
            return _ok(_sanitize_status(status))
        if remote.get("failed"):
            return _ok(
                _sanitize_status(_listing_analysis_failure_payload(status, remote))
            )
        return _ok(_sanitize_status({**status, **remote}))
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_listing_analysis_status(...)",
            call_params={"job_id": job_id},
        )


async def seller_sprite_listing_analysis_result(
    job_id: str,
    export_format: str = "json",
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """读取 Listing Analysis 远端任务结果；未完成时返回 ready=false。"""
    try:
        owner_record = _ensure_listing_analysis_job_owner(job_id)
        binding = await ensure_ops_credentials(
            provided_session=session_id,
            provided_jwt=jwt,
        )
        sid, jw = binding.session_id, binding.jwt
        status = dict(_get_task_scheduler().job_status(job_id))
        account_binding = _get_listing_analysis_account_binding(job_id, status)
        if status.get("state") == "queued" and not account_binding.get(
            "assigned_account_key"
        ):
            status["ready"] = False
            return _ok(_sanitize_status(status))
        task_id = _extract_listing_analysis_task_id(status)
        asin = _extract_listing_analysis_asin(status, owner_record)
        if asin:
            history = await _fetch_listing_analysis_history_status(
                asin=asin,
                session_id=sid,
                jwt=jw,
                account_binding=account_binding,
            )
            if history.get("failed"):
                return _ok(
                    _sanitize_status(
                        _mark_listing_analysis_remote_failed(job_id, status, history)
                    )
                )
            if not history.get("task_id"):
                return _ok(
                    _sanitize_status(
                        {**status, **history, "ready": False, "export_format": export_format}
                    )
                )
            task_id = str(history["task_id"])
            if not history.get("ready"):
                return _ok(
                    _sanitize_status(
                        {**status, **history, "ready": False, "export_format": export_format}
                    )
                )
        if not task_id:
            status["ready"] = False
            return _ok(_sanitize_status(status))
        remote = await _fetch_listing_analysis_report_result(
            task_id=task_id,
            session_id=sid,
            jwt=jw,
            account_binding=account_binding,
        )
        if remote.get("failed"):
            return _ok(
                _sanitize_status(
                    _mark_listing_analysis_remote_failed(job_id, status, remote)
                )
            )
        if not remote.get("ready"):
            return _ok(
                _sanitize_status({**status, **remote, "export_format": export_format})
            )
        persisted = _persist_listing_analysis_remote_result(
            job_id=job_id,
            status=status,
            remote=remote,
            export_format=export_format,
            session_id=sid,
            jwt=jw,
        )
        return _ok(_sanitize_status(persisted))
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_listing_analysis_result(...)",
            call_params={"job_id": job_id, "export_format": export_format},
        )


async def seller_sprite_job_status(job_id: str, wait_seconds: int = 0) -> dict:
    """读取卖家精灵任务结果，可在 0 至 30 秒内等待任务终态。"""
    try:
        _ensure_seller_sprite_job_owner(job_id)
        scheduler = _get_task_scheduler()
        statuses = await _wait_for_preauthorized_seller_sprite_job_statuses(
            scheduler=scheduler,
            job_ids=[job_id],
            wait_seconds=wait_seconds,
        )
        return _ok(_sanitize_status(statuses[0]))
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_job_status(...)",
            call_params={"job_id": job_id, "wait_seconds": wait_seconds},
        )


async def seller_sprite_jobs_status(job_ids: list[str], wait_seconds: int = 0) -> dict:
    """批量读取 1 至 50 个普通卖家精灵任务状态，可有界等待全部终态。"""
    try:
        if not job_ids:
            raise ValueError("至少提供 1 个 job_id")
        if len(job_ids) > 50:
            raise ValueError("最多提供 50 个 job_id")

        # 先规范化完整输入并去重保序，任何空白 ID 都整批拒绝。
        normalized_job_ids: list[str] = []
        seen_job_ids: set[str] = set()
        for raw_job_id in job_ids:
            job_id = str(raw_job_id or "").strip()
            if not job_id:
                raise ValueError("job_id 不能为空")
            if job_id not in seen_job_ids:
                normalized_job_ids.append(job_id)
                seen_job_ids.add(job_id)

        # 使用同一仓储扫描全部唯一 ID；只在完整集合校验后统一拒绝，避免泄露失败位置和类型。
        user_email = str(_get_current_mcp_user_email() or "").strip().lower()
        if not user_email:
            raise ValueError("当前 MCP 用户邮箱缺失，无法读取卖家精灵任务")
        store = _get_task_queue_store()
        unavailable_job_ids: list[str] = []
        for job_id in normalized_job_ids:
            try:
                record = store.get_mcp_run(job_id)
                _validate_seller_sprite_job_owner_record(job_id, record, user_email)
                scenario = str(record.get("scenario") or "").strip().lower()
                if scenario == "listing-analysis":
                    unavailable_job_ids.append(job_id)
            except (ValueError, PermissionError):
                unavailable_job_ids.append(job_id)
        if unavailable_job_ids:
            raise ValueError("一个或多个卖家精灵任务不可用")

        scheduler = _get_task_scheduler()
        statuses = await _wait_for_preauthorized_seller_sprite_job_statuses(
            scheduler=scheduler,
            job_ids=normalized_job_ids,
            wait_seconds=wait_seconds,
        )
        summary = {
            "total": len(statuses),
            "queued": 0,
            "running": 0,
            "succeeded": 0,
            "failed": 0,
        }
        states: list[str] = []
        for status in statuses:
            state = str(status.get("state") or "").strip().lower()
            states.append(state)
            if state in {"queued", "running", "succeeded", "failed"}:
                summary[state] += 1
        return _ok(
            {
                "ready": all(state in SELLER_SPRITE_TERMINAL_STATES for state in states),
                "summary": summary,
                "jobs": [_sanitize_status(status) for status in statuses],
            }
        )
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_jobs_status(...)",
            call_params={"job_ids": job_ids, "wait_seconds": wait_seconds},
        )


async def seller_sprite_export(job_id: str) -> dict:
    """读取当前 MCP 用户所属卖家精灵任务的导出文件信息。"""
    try:
        _ensure_seller_sprite_job_owner(job_id)
        status = _get_task_scheduler().job_status(job_id)
        export = status.get("export")
        if not export:
            raise ValueError(f"任务无导出文件：{job_id}")
        return _ok(_sanitize_export(dict(export)))
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_export(...)", call_params={"job_id": job_id})


_ALL_TOOLS = [
    seller_sprite_spec_must_read,
    seller_sprite_scenarios,
    seller_sprite_quota_status,
    seller_sprite_run,
    seller_sprite_listing_analysis_submit,
    seller_sprite_listing_analysis_status,
    seller_sprite_listing_analysis_result,
    seller_sprite_job_status,
    seller_sprite_jobs_status,
    seller_sprite_export,
]


def register(mcp) -> None:
    """向 FastMCP 实例注册卖家精灵工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
