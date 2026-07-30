"""卖家精灵接口直连任务编排。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from opscli.seller_sprite.accounts import SellerSpriteAccount, SellerSpriteAccountProvider
from opscli.seller_sprite.api.categories import SellerSpriteCategoryResolver
from opscli.seller_sprite.api.client import BASE_URL, SellerSpriteApiClient
from opscli.seller_sprite.api.keyword_research import parse_keyword_research_html
from opscli.seller_sprite.api.market_research import parse_market_research_html
from opscli.seller_sprite.api.scenarios import get_scenario, list_scenarios
from opscli.seller_sprite.browser_route import (
    BrowserRouteRequest,
    BrowserRouteResult,
    BrowserRouteWorkerClosedError,
    build_default_session_state_listener,
    get_browser_route_worker,
    get_existing_browser_route_worker,
)
from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError, SellerSpriteConfigError
from opscli.seller_sprite.domain.models import (
    SellerSpriteExportResult,
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)
from opscli.seller_sprite.export.keyword_comparison_xlsx import (
    export_keyword_comparison_to_xlsx,
)
from opscli.seller_sprite.export.xlsx import export_rows_to_xlsx
from opscli.seller_sprite.services.task_status import (
    base_status,
    error_to_dict,
    now_iso,
    read_status,
    write_status,
)
from opscli.shared.file_uploads import FileUploadClient, FileUploadError
from opscli.shared.integration_accounts import IntegrationAccountClient


AI_TASK_DONE_STATUSES = {"COMPLETED", "COMPLETE", "SUCCESS", "SUCCEEDED", "FINISHED", "DONE"}
AI_TASK_FAILED_STATUSES = {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "EXPIRED"}
DEFAULT_AI_TASK_POLL_ATTEMPTS = 180
DEFAULT_AI_TASK_POLL_INTERVAL_SECONDS = 2.0
WINDOWS_COMPAT_EXPORT_PATH_LIMIT = 240
_BACKGROUND_TASKS: set[asyncio.Task] = set()


class SellerSpriteApiManager:
    """执行卖家精灵接口场景并落盘任务结果。"""

    def __init__(
        self,
        *,
        settings: SellerSpriteSettings | None = None,
        account_provider: SellerSpriteAccountProvider | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
        session_state_listener: Callable[
            [SellerSpriteAccount, dict[str, Any]], None
        ]
        | None = None,
        session_owner_id: str = "default",
        listing_remote_task_id: str | None = None,
        listing_task_id_listener: Callable[[str], None] | None = None,
        progress_listener: Callable[[str, dict[str, Any] | None], None] | None = None,
    ) -> None:
        """创建卖家精灵场景执行器。

        参数：
            settings: 卖家精灵运行配置。
            account_provider: 账号来源。
            jwt: 当前调用者 JWT，仅用于账号接口。
            session_id: 当前调用会话标识。
            session_state_listener: browser 会话状态监听器。
            session_owner_id: browser worker 所有权标识。
            listing_remote_task_id: Listing Analysis 已持久化远端任务标识。
            listing_task_id_listener: 远端任务标识持久化监听器。
            progress_listener: 仅接收阶段与脱敏白名单元数据的进度监听器。

        返回：
            无。
        """
        self.settings = settings or load_settings()
        self.jwt = jwt
        self.session_id = session_id
        self.session_state_listener = session_state_listener or build_default_session_state_listener(
            self.settings
        )
        self.session_owner_id = session_owner_id
        self.listing_remote_task_id = listing_remote_task_id
        self.listing_task_id_listener = listing_task_id_listener
        self.progress_listener = progress_listener
        self.account_provider = account_provider or SellerSpriteAccountProvider(
            self.settings,
            integration_client=IntegrationAccountClient(jwt=jwt, session_id=session_id),
        )

    def scenarios(self) -> list[dict[str, Any]]:
        """列出支持的接口场景。"""
        return list_scenarios()

    def browser_route_busy(self, request: SellerSpriteScenarioRequest) -> bool:
        """判断当前请求对应账号的 browser-route worker 是否正忙。"""
        mode = _resolve_request_mode(request.mode or self.settings.default_mode)
        if mode != "browser-route":
            return False
        account = self.account_provider.get_default()
        worker = get_existing_browser_route_worker(
            settings=self.settings,
            account=account,
            owner_id=self.session_owner_id,
        )
        return bool(worker and worker.is_busy)

    async def start(self, request: SellerSpriteScenarioRequest) -> dict[str, Any]:
        """创建异步任务并立即返回任务状态。"""
        get_scenario(request.scenario)
        site = (request.site or self.settings.default_site).upper()
        period = request.period or self.settings.default_period
        job_id = request.job_id or _build_job_id(request, site, period)
        request = replace(request, site=site, period=period, job_id=job_id)
        root_dir = self._build_root_dir(request, job_id)
        status = base_status(
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            period=period,
            state="queued",
            stage="created",
            root_dir=root_dir,
        )
        write_status(root_dir, status)

        # 保留 task 引用，避免后台任务在事件循环中被提前回收。
        task = asyncio.create_task(self._run_background_task(request, root_dir))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return status

    async def _run_background_task(self, request: SellerSpriteScenarioRequest, root_dir: Path) -> None:
        """执行后台任务并持续更新状态文件。"""
        status = read_status(root_dir) or base_status(
            job_id=request.job_id or "",
            scenario=request.scenario,
            site=request.site,
            period=request.period,
            state="queued",
            stage="created",
            root_dir=root_dir,
        )
        status["state"] = "running"
        status["stage"] = "running"
        status["started_at"] = now_iso()
        write_status(root_dir, status)
        try:
            result = await self.run(request)
        except Exception as exc:
            status["state"] = "failed"
            status["stage"] = "failed"
            status["finished_at"] = now_iso()
            status["error"] = error_to_dict(exc)
            write_status(root_dir, status)
            return

        status["state"] = "succeeded"
        status["stage"] = "finished"
        status["finished_at"] = now_iso()
        status["error"] = None
        status["export"] = result.export.to_dict() if result.export else None
        status["row_count"] = result.row_count
        status["result_path"] = result.result_path
        write_status(root_dir, status)

    async def run(self, request: SellerSpriteScenarioRequest) -> SellerSpriteScenarioResult:
        """执行一个接口场景。"""
        self._emit_progress("resolving")
        scenario = get_scenario(request.scenario)
        site = (request.site or self.settings.default_site).upper()
        period = request.period or self.settings.default_period
        job_id = request.job_id or _build_job_id(request, site, period)
        root_dir = self._build_root_dir(request, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)
        page_size = request.page_size or self.settings.page_size
        export_format = _normalize_export_format(request.export_format)
        if scenario.method in {"GET_XLSX", "POST_XLSX"} and export_format != "xlsx":
            raise SellerSpriteConfigError(
                f"{request.scenario} 仅支持 xls 或 xlsx 官方文件导出"
            )
        account = self.account_provider.get_default()
        warnings: list[dict[str, Any]] = []
        effective_asin_list: list[str] | None = None
        mode = _resolve_request_mode(request.mode or self.settings.default_mode)
        if scenario.browser_context_only and mode != "browser-route":
            raise SellerSpriteConfigError(f"{request.scenario} 仅支持 browser-route 模式")
        async with SellerSpriteApiClient(account=account) as client:
            login = {"mode": "cached", "cookie_names": client.cookie_names()}
            if mode == "api-direct" and not client.has_login_cookies():
                login = await _login_with_account_refresh(
                    client=client,
                    account_provider=self.account_provider,
                    warnings=warnings,
                )
            category_resolver = SellerSpriteCategoryResolver(client)
            params = await _request_with_session_retry(
                client=client,
                warnings=warnings,
                stage="category",
                action=lambda: category_resolver.resolve_params(
                    params=request.params,
                    scenario=request.scenario,
                    site=site,
                    period=period,
                ),
            )
            payload = scenario.build_payload(params=params, site=site, period=period, page_size=page_size)

            params_path = root_dir / "params.json"
            raw_path = root_dir / "raw.json"
            result_path = root_dir / "result.json"
            _write_json(
                params_path,
                {
                    "request": request.to_dict(),
                    "resolved_params": params,
                    "payload": payload,
                },
            )
            if mode == "browser-route":
                if request.scenario == "listing-analysis" and self.listing_remote_task_id:
                    self._emit_progress("remote_poll")
                    from opscli.seller_sprite.browser_route import (
                        fetch_listing_analysis_report_with_browser_route,
                    )

                    browser_result = await fetch_listing_analysis_report_with_browser_route(
                        settings=self.settings,
                        account=account,
                        task_id=self.listing_remote_task_id,
                        root_dir=root_dir,
                        page_prepare=(
                            self.settings.browser_page_prepare
                            if request.page_prepare is None
                            else request.page_prepare
                        ),
                        task_interval_seconds=(
                            self.settings.browser_task_interval_seconds
                            if request.task_interval_seconds is None
                            else request.task_interval_seconds
                        ),
                        cooldown_seconds=(
                            self.settings.browser_cooldown_seconds
                            if request.cooldown_seconds is None
                            else request.cooldown_seconds
                        ),
                        state_listener=self.session_state_listener,
                        owner_id=self.session_owner_id,
                    )
                else:
                    self._emit_progress("browser_wait")
                    browser_result = await _run_browser_route_request(
                        settings=self.settings,
                        account=account,
                        request=request,
                        scenario_method=scenario.method,
                        endpoint=scenario.endpoint_for(payload),
                        payload=_main_payload(request.scenario, payload),
                        referer=scenario.build_referer(payload),
                        root_dir=root_dir,
                        high_frequency_endpoint=(
                            scenario.high_frequency_endpoint_for(payload)
                            if payload.get("includeHighFrequency")
                            else None
                        ),
                        high_frequency_payload=(
                            _high_frequency_payload(request.scenario, payload)
                            if payload.get("includeHighFrequency") and scenario.high_frequency_endpoint_for(payload)
                            else None
                        ),
                        session_state_listener=self.session_state_listener,
                        session_owner_id=self.session_owner_id,
                        replay_safe=scenario.replay_safe,
                    )
                    if request.scenario == "listing-analysis":
                        task_id = _extract_task_id(browser_result.response)
                        if task_id and self.listing_task_id_listener:
                            self.listing_task_id_listener(task_id)
                login = browser_result.login
                main_response = browser_result.response
                high_frequency_response = browser_result.high_frequency_response
                effective_asin_list = browser_result.effective_asin_list
                warnings.extend(browser_result.warnings)
            else:
                self._emit_progress("requesting")
                main_response = await _request_with_session_retry(
                    client=client,
                    warnings=warnings,
                    stage="main",
                    action=lambda: _run_main_request(
                        client=client,
                        method=scenario.method,
                        endpoint=scenario.endpoint_for(payload),
                        payload=_main_payload(request.scenario, payload),
                        referer=scenario.build_referer(payload),
                        root_dir=root_dir,
                    ),
                )
                if scenario.task_result_endpoint:
                    main_response = await _request_with_session_retry(
                        client=client,
                        warnings=warnings,
                        stage="ai_task",
                        action=lambda: _poll_ai_task_result(
                            client=client,
                            submit_response=main_response,
                            result_endpoint_template=scenario.task_result_endpoint or "",
                            referer=scenario.build_referer(payload),
                            params=request.params,
                            progress_listener=self.progress_listener,
                        ),
                    )
                if _looks_like_guest_limited_response(main_response, page_size=page_size):
                    login = await _login_with_account_refresh(
                        client=client,
                        account_provider=self.account_provider,
                        warnings=warnings,
                    )
                    warnings.append(
                        {
                            "stage": "main",
                            "message": "卖家精灵疑似返回游客限制数据，已登录并重试一次",
                            "login": login,
                        }
                    )
                    main_response = await _run_main_request(
                        client=client,
                        method=scenario.method,
                        endpoint=scenario.endpoint_for(payload),
                        payload=_main_payload(request.scenario, payload),
                        referer=scenario.build_referer(payload),
                        root_dir=root_dir,
                    )
                high_frequency_response = None
                if payload.get("includeHighFrequency") and scenario.high_frequency_endpoint_for(payload):
                    try:
                        high_frequency_response = await _request_with_session_retry(
                            client=client,
                            warnings=warnings,
                            stage="high_frequency",
                            action=lambda: client.post_json(
                                scenario.high_frequency_endpoint_for(payload) or "",
                                _high_frequency_payload(request.scenario, payload),
                                referer=scenario.build_referer(payload),
                            ),
                        )
                    except SellerSpriteApiError as exc:
                        warnings.append(
                            {
                                "stage": "high_frequency",
                                "message": "高频词接口请求失败，主表继续导出",
                                "error": exc.to_dict(),
                            }
                        )
        raw = {
            "job_id": job_id,
            "scenario": request.scenario,
            "mode": mode,
            "login": login,
            "payload": payload,
            "response": main_response,
            "high_frequency_response": high_frequency_response,
            "warnings": warnings,
        }
        _write_json(raw_path, raw)

        self._emit_progress("processing")
        rows = _extract_items(main_response, scenario=request.scenario)
        if request.scenario == "keyword-comparison":
            # 即使上游异常返回超过分页大小，也只导出首期约定的第一页 100 条。
            rows = rows[:100]
        high_frequency_rows = _extract_high_frequency_rows(high_frequency_response)
        self._emit_progress("exporting")
        if scenario.method in {"GET_XLSX", "POST_XLSX"}:
            export = _official_xlsx_export(main_response, root_dir=root_dir)
        elif export_format == "xlsx":
            if request.scenario == "keyword-comparison":
                if not effective_asin_list:
                    raise SellerSpriteApiError(
                        "卖家精灵流量词对比缺少最终畅销变体顺序",
                        api_code="ERR_KEYWORD_COMPARISON_ASIN_LIST_MISSING",
                    )
                export = export_keyword_comparison_to_xlsx(
                    rows=rows,
                    output_path=_keyword_comparison_output_path(
                        root_dir,
                        site=site,
                        own_asin=str(payload.get("asin") or ""),
                    ),
                    site=site,
                    own_asin=str(payload.get("asin") or ""),
                    asin_list=effective_asin_list,
                )
            else:
                export = export_rows_to_xlsx(
                    rows=rows,
                    output_path=(
                        _aba_research_output_path(root_dir, site=site, payload=payload)
                        if request.scenario == "aba-research"
                        else _export_output_path(root_dir, job_id, "xlsx")
                    ),
                    scenario=request.scenario,
                    site=site,
                    period=period,
                    params=request.params,
                    high_frequency_rows=high_frequency_rows,
                )
        else:
            export = _export_rows_to_json(
                output_path=_export_output_path(root_dir, job_id, "json"),
                job_id=job_id,
                scenario=request.scenario,
                site=site,
                period=period,
                rows=rows,
                high_frequency_rows=high_frequency_rows,
                warnings=warnings,
            )
        self._emit_progress("uploading")
        _upload_export_if_enabled(
            export=export,
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            period=period,
            warnings=warnings,
            jwt=self.jwt,
            session_id=self.session_id,
        )
        self._emit_progress("finalizing")
        result = SellerSpriteScenarioResult(
            job_id=job_id,
            scenario=request.scenario,
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
        _write_json(result_path, result.to_dict())
        return result

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取已落盘任务状态。"""
        root_dir = self.settings.output_dir / job_id
        result_path = root_dir / "result.json"
        if not result_path.exists():
            status = read_status(root_dir)
            if status:
                return status
            raise SellerSpriteConfigError(f"任务不存在：{job_id}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        status = read_status(root_dir)
        if not status:
            return result
        # 异步任务完成后保留 state/stage，同时用 result.json 补充最终业务结果。
        merged = dict(status)
        merged.update(result)
        merged.setdefault("state", status.get("state") or "succeeded")
        merged.setdefault("stage", status.get("stage") or "finished")
        return merged

    def _emit_progress(
        self,
        stage: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """向可选监听器报告粗粒度阶段及脱敏白名单元数据。"""
        if self.progress_listener is not None:
            self.progress_listener(stage, metadata)

    def _build_root_dir(self, request: SellerSpriteScenarioRequest, job_id: str) -> Path:
        if request.attempt_output_dir:
            attempt_dir = Path(request.attempt_output_dir).expanduser()
            if not attempt_dir.is_absolute():
                attempt_dir = Path.cwd() / attempt_dir
            return attempt_dir.resolve()
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / job_id


async def _run_main_request(
    *,
    client: SellerSpriteApiClient,
    method: str,
    endpoint: str,
    payload: dict[str, Any],
    referer: str,
    root_dir: Path,
) -> dict[str, Any]:
    if method in {"GET", "PAGE_CAPTURE"}:
        return await client.get_json(endpoint, payload, referer=referer)
    if method == "GET_XLSX":
        content, filename = await client.get_bytes(endpoint, payload, referer=referer)
        safe_filename = _safe_official_filename(filename)
        if len(str(root_dir / safe_filename)) >= WINDOWS_COMPAT_EXPORT_PATH_LIMIT:
            safe_filename = "export.xlsx"
        response_path = root_dir / safe_filename
        response_path.write_bytes(content)
        return {
            "code": "OK",
            "data": {
                "official_xlsx_path": str(response_path),
                "official_filename": filename,
                "content_length": len(content),
            },
        }
    if method == "GET_PAGE":
        response_html = await client.get_html(endpoint, payload, referer=referer)
        response_html_path = root_dir / "response.html"
        response_html_path.write_text(response_html, encoding="utf-8")
        rows = parse_keyword_research_html(response_html)
        return {
            "code": "OK",
            "data": {"items": rows},
            "response_html_path": str(response_html_path),
            "response_html_length": len(response_html),
        }
    if method == "POST_QUERY":
        return await client.request_json(
            "POST",
            endpoint,
            params=payload,
            json={},
            headers={
                **client._browser_headers(referer=referer),
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": BASE_URL,
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            },
        )
    if method == "FORM":
        response_html = await client.post_form(endpoint, payload, referer=referer)
        response_html_path = root_dir / "response.html"
        response_html_path.write_text(response_html, encoding="utf-8")
        rows = parse_market_research_html(response_html)
        return {
            "code": "OK",
            "data": {
                "items": rows,
            },
            "response_html_path": str(response_html_path),
            "response_html_length": len(response_html),
        }
    return await client.post_json(endpoint, payload, referer=referer)


async def _run_browser_route_request(
    *,
    settings: SellerSpriteSettings,
    account: SellerSpriteAccount,
    request: SellerSpriteScenarioRequest,
    scenario_method: str,
    endpoint: str,
    payload: dict[str, Any],
    referer: str,
    root_dir: Path,
    high_frequency_endpoint: str | None,
    high_frequency_payload: dict[str, Any] | None,
    session_state_listener: Callable[[SellerSpriteAccount, dict[str, Any]], None] | None,
    session_owner_id: str,
    replay_safe: bool = True,
) -> BrowserRouteResult:
    """提交 browser-route 请求，遇到并发回收时仅重建并重试一次。"""
    browser_request = BrowserRouteRequest(
        scenario=request.scenario,
        method=scenario_method,
        endpoint=endpoint,
        payload=payload,
        referer=referer,
        account=account,
        root_dir=root_dir,
        high_frequency_endpoint=high_frequency_endpoint,
        high_frequency_payload=high_frequency_payload,
        page_prepare=(
            settings.browser_page_prepare if request.page_prepare is None else request.page_prepare
        ),
        task_interval_seconds=(
            settings.browser_task_interval_seconds
            if request.task_interval_seconds is None
            else request.task_interval_seconds
        ),
        cooldown_seconds=(
            settings.browser_cooldown_seconds
            if request.cooldown_seconds is None
            else request.cooldown_seconds
        ),
        replay_safe=replay_safe,
    )
    for attempt in range(2):
        worker = get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=session_state_listener,
            owner_id=session_owner_id,
        )
        try:
            return await worker.submit(browser_request)
        except BrowserRouteWorkerClosedError:
            # 回收先取得生命周期锁时，丢弃旧引用并从 registry 获取全新 worker。
            if attempt > 0:
                raise
    raise BrowserRouteWorkerClosedError("browser worker 重建后仍不可用")


def _resolve_request_mode(value: str) -> str:
    mode = (value or "browser-route").strip().lower()
    if mode not in {"api-direct", "browser-route"}:
        raise SellerSpriteConfigError("卖家精灵 mode 仅支持 api-direct 或 browser-route")
    return mode


async def _poll_ai_task_result(
    *,
    client: SellerSpriteApiClient,
    submit_response: dict[str, Any],
    result_endpoint_template: str,
    referer: str,
    params: dict[str, Any],
    progress_listener: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    task_id = _extract_task_id(submit_response)
    if not task_id:
        raise SellerSpriteApiError(
            "SellerSprite AI task response missing taskId",
            response_excerpt=json.dumps(submit_response, ensure_ascii=False)[:1000],
            api_code="ERR_AI_TASK_ID_MISSING",
        )

    attempts = _int(params.get("pollAttempts") or params.get("maxPolls"), DEFAULT_AI_TASK_POLL_ATTEMPTS)
    attempts = max(1, attempts)
    interval = _float(
        params.get("pollIntervalSeconds") or params.get("pollInterval"),
        DEFAULT_AI_TASK_POLL_INTERVAL_SECONDS,
    )
    endpoint = result_endpoint_template.format(task_id=task_id)
    last_response: dict[str, Any] | None = None
    last_reported_status = ""
    for attempt in range(attempts):
        task_response = await client.get_json(endpoint, {}, referer=referer)
        last_response = task_response
        poll_status = _ai_task_status(task_response) or "PENDING"
        report_due = (
            attempt == 0
            or poll_status != last_reported_status
            or (attempt + 1) % 10 == 0
        )
        if progress_listener is not None and report_due:
            progress_listener(
                "remote_poll",
                {
                    "poll_attempt": attempt + 1,
                    "poll_total": attempts,
                    "poll_status": poll_status,
                },
            )
            last_reported_status = poll_status
        if _ai_task_has_content(task_response) or _ai_task_is_done(task_response):
            return _merge_ai_task_response(
                submit_response=submit_response,
                task_response=task_response,
                task_id=task_id,
                attempts=attempt + 1,
            )
        if _ai_task_failed(task_response):
            data = task_response.get("data") if isinstance(task_response, dict) else {}
            message = data.get("taskErrMsg") if isinstance(data, dict) else None
            raise SellerSpriteApiError(
                f"SellerSprite AI task failed: {task_id}",
                response_excerpt=json.dumps(task_response, ensure_ascii=False)[:1000],
                api_code="ERR_AI_TASK_FAILED",
                api_message=str(message) if message else None,
            )
        if attempt < attempts - 1 and interval > 0:
            await asyncio.sleep(interval)

    raise SellerSpriteApiError(
        f"SellerSprite AI task timeout: {task_id}",
        response_excerpt=json.dumps(last_response or submit_response, ensure_ascii=False)[:1000],
        api_code="ERR_AI_TASK_TIMEOUT",
    )


def _extract_task_id(response: dict[str, Any]) -> str:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        return str(data.get("taskId") or data.get("task_id") or "").strip()
    return ""


def _merge_ai_task_response(
    *,
    submit_response: dict[str, Any],
    task_response: dict[str, Any],
    task_id: str,
    attempts: int,
) -> dict[str, Any]:
    payload = dict(task_response)
    data = dict(task_response.get("data") or {})
    data.setdefault("taskId", task_id)
    data["pollAttempts"] = attempts
    data["submitTask"] = submit_response.get("data")
    payload["data"] = data
    return payload


def _ai_task_has_content(response: dict[str, Any]) -> bool:
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False
    content = data.get("content")
    return content is not None and content != ""


def _ai_task_is_done(response: dict[str, Any]) -> bool:
    status = _ai_task_status(response)
    return status in AI_TASK_DONE_STATUSES


def _ai_task_failed(response: dict[str, Any]) -> bool:
    status = _ai_task_status(response)
    return status in AI_TASK_FAILED_STATUSES


def _ai_task_status(response: dict[str, Any]) -> str:
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return ""
    return str(data.get("taskStatus") or data.get("status") or "").strip().upper()


async def _request_with_session_retry(
    *,
    client: SellerSpriteApiClient,
    warnings: list[dict[str, Any]],
    stage: str,
    action,
) -> dict[str, Any]:
    try:
        return await action()
    except SellerSpriteApiError as exc:
        if not exc.is_session_expired():
            raise
        login = await client.login()
        warnings.append(
            {
                "stage": stage,
                "message": "卖家精灵会话过期，已重新登录并重试一次",
                "error": exc.to_dict(),
                "relogin": login,
            }
        )
        return await action()


async def _login_with_account_refresh(
    *,
    client: SellerSpriteApiClient,
    account_provider: SellerSpriteAccountProvider,
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        return await client.login()
    except SellerSpriteApiError as exc:
        refreshed_account = account_provider.get_default(refresh=True)
        if refreshed_account == client.account:
            raise
        warnings.append(
            {
                "stage": "login",
                "message": "卖家精灵登录失败，已刷新集成账号并重试一次",
                "error": exc.to_dict(),
                "account": refreshed_account.to_public_dict(),
            }
        )
        client.switch_account(refreshed_account)
        return await client.login()


def _main_payload(scenario: str, payload: dict[str, Any]) -> dict[str, Any]:
    """去除仅用于本地编排的字段。"""
    if scenario == "keyword-reverse":
        return _without(payload, {"market", "page"})
    return payload


def _high_frequency_payload(scenario: str, payload: dict[str, Any]) -> dict[str, Any]:
    """构造高频词接口 payload。"""
    return payload


def _without(payload: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in keys}


def _extract_items(response: dict[str, Any], *, scenario: str | None = None) -> list[dict[str, Any]]:
    data = response.get("data") if isinstance(response, dict) else None
    if scenario == "listing-analysis":
        listing_rows = _extract_listing_analysis_rows(data)
        if listing_rows:
            return listing_rows
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [item for item in data["items"] if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("pager"), dict):
        pager = data["pager"]
        if isinstance(pager.get("items"), list):
            return [item for item in pager["items"] if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("pagerDto"), dict):
        pager = data["pagerDto"]
        if isinstance(pager.get("items"), list):
            return [item for item in pager["items"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _extract_listing_analysis_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    if "content" in data or "htmlContent" in data:
        return [
            {
                "taskId": data.get("taskId"),
                "taskStatus": data.get("taskStatus"),
                "content": data.get("content"),
                "htmlStatus": data.get("htmlStatus"),
                "htmlContent": data.get("htmlContent"),
                "completedTime": data.get("completedTime"),
                "expiredTime": data.get("expiredTime"),
            }
        ]
    task_id = data.get("taskId") or data.get("task_id")
    if task_id:
        return [
            {
                "taskId": str(task_id),
                "taskStatus": data.get("taskStatus") or data.get("status"),
                "asin": data.get("asin"),
                "station": data.get("station"),
                "contentReady": bool(data.get("content") or data.get("htmlContent")),
            }
        ]
    if data.get("asin"):
        return [
            {
                "asin": data.get("asin"),
                "station": data.get("station"),
                "taskStatus": data.get("taskStatus") or data.get("status"),
                "contentReady": bool(data.get("content") or data.get("htmlContent")),
            }
        ]
    return []


def _int(value: Any, default: int = 0) -> int:
    """安全将值转为 int，转换失败返回默认值。"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _float(value: Any, default: float = 0) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        return default
    return parsed if parsed >= 0 else default


def _looks_like_guest_limited_response(response: dict[str, Any], *, page_size: int) -> bool:
    if page_size <= 20:
        return False
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False
    pager = data.get("pagerDto") if isinstance(data.get("pagerDto"), dict) else data
    items = pager.get("items")
    if not isinstance(items, list) or len(items) != 20:
        return False
    total = _int(pager.get("total"), 0)
    pages = _int(pager.get("pages"), 0)
    size = _int(pager.get("size"), 0)
    return bool(
        data.get("guestId")
        or data.get("guestVisited") is True
        or size == 20
        or total > 20
        or pages > 1
    )


def _extract_high_frequency_rows(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _build_job_id(request: SellerSpriteScenarioRequest, site: str, period: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    service = "SellerSprite"
    scenario_label = _scenario_label(request.scenario)
    target_label = _build_target_label(request.scenario, request.params)
    period_label = _build_period_label(period)

    parts = [service, scenario_label, site]
    if target_label:
        parts.append(target_label)
    if period_label:
        parts.append(period_label)
    parts.append(timestamp)
    parts.append(suffix)
    return "-".join(parts)


def _scenario_label(scenario: str) -> str:
    labels = {
        "competitor-lookup": "CompetitorLookup",
        "product-research": "ProductResearch",
        "keyword-comparison": "CompareKeywords",
        "keyword-miner": "KeywordMiner",
        "keyword-research": "KeywordResearch",
        "aba-research": "ABAResearch",
        "association-traffic": "AssociationTraffic",
        "aba-reverse": "ABAReverse",
        "keyword-reverse": "ReverseASIN",
        "traffic-source": "TrafficSource",
        "market-research": "MarketResearch",
        "listing-analysis": "ListingAnalysis",
    }
    return labels.get(scenario, _camel_case(scenario))


def _build_target_label(scenario: str, params: dict[str, Any] | None) -> str:
    if not isinstance(params, dict):
        return ""

    def first_value(value: Any) -> str:
        if isinstance(value, list) and value:
            return str(value[0])
        return str(value) if value is not None else ""

    if scenario in {"keyword-reverse", "aba-reverse"}:
        return _sanitize_filename_part(
            params.get("asin") or first_value(params.get("asins"))
        )
    if scenario in {"listing-analysis", "keyword-comparison"}:
        return _sanitize_filename_part(
            params.get("ownAsin") or params.get("myAsin") or params.get("asin")
        )
    if scenario == "keyword-miner":
        return _sanitize_filename_part(params.get("keyword"))
    if scenario in {"keyword-research", "aba-research"}:
        return _sanitize_filename_part(
            params.get("q")
            or params.get("keywords")
            or params.get("includeKeywords")
            or params.get("keyword")
            or params.get("asin")
            or first_value(params.get("departments"))
        )
    if scenario == "association-traffic":
        return _sanitize_filename_part(first_value(params.get("asins") or params.get("asin")))
    if scenario == "traffic-source":
        return _sanitize_filename_part(
            params.get("keywordOrAsin")
            or params.get("keyword")
            or params.get("asin")
            or first_value(params.get("asins"))
        )
    if scenario == "competitor-lookup":
        return _sanitize_filename_part(
            params.get("asins")
            or params.get("keyword")
            or params.get("brand")
            or params.get("sellerName")
        )
    if scenario == "product-research":
        return _sanitize_filename_part(
            params.get("recommendationMode")
            or first_value(params.get("keywords"))
            or params.get("keyword")
            or params.get("category")
            or params.get("node")
        )
    if scenario == "market-research":
        return _sanitize_filename_part(
            params.get("departmentKeyword")
            or params.get("category")
            or params.get("node")
            or params.get("keyword")
        )

    return ""


def _camel_case(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    return "".join(part.capitalize() for part in parts if part)


def _build_period_label(period: str) -> str:
    if not period:
        return ""
    normalized = period.strip().lower()
    if normalized == "nearly":
        return "Nearly"
    if normalized.endswith("d") and normalized[:-1].isdigit():
        return f"Last-{int(normalized[:-1])}-days"
    if re.match(r"^\d{4}-\d{2}$", normalized):
        return normalized.upper()
    return _sanitize_filename_part(period)


def _sanitize_filename_part(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = text.replace(" ", "-")
    text = re.sub(r"[^A-Za-z0-9\-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:64]


def _official_xlsx_export(
    response: dict[str, Any],
    *,
    root_dir: Path,
) -> SellerSpriteExportResult:
    data = response.get("data") if isinstance(response, dict) else None
    source_value = data.get("official_xlsx_path") if isinstance(data, dict) else None
    if not source_value:
        raise SellerSpriteApiError(
            "卖家精灵官方 Excel 下载结果缺少文件路径",
            api_code="ERR_SELLER_SPRITE_XLSX_PATH_MISSING",
        )
    source = Path(str(source_value))
    signature = b""
    if source.exists():
        with source.open("rb") as file:
            signature = file.read(2)
    if signature != b"PK":
        raise SellerSpriteApiError(
            "卖家精灵官方 Excel 文件无效",
            api_code="ERR_SELLER_SPRITE_XLSX_INVALID",
        )
    official_filename = data.get("official_filename") if isinstance(data, dict) else None
    filename = _safe_official_filename(official_filename)
    if len(str(root_dir / filename)) >= WINDOWS_COMPAT_EXPORT_PATH_LIMIT:
        filename = "export.xlsx"
    target = root_dir / filename
    if source.resolve() != target.resolve():
        source.replace(target)
    resolved = target.resolve()
    return SellerSpriteExportResult(
        path=str(resolved),
        filename=resolved.name,
        url=resolved.as_uri(),
    )


def _safe_official_filename(value: Any) -> str:
    filename = Path(str(value or "")).name.strip()
    filename = re.sub(r'[<>:"/\\|?*]+', "-", filename).rstrip(". ")
    if not filename:
        return "official-export.xlsx"
    if not filename.lower().endswith(".xlsx"):
        filename = f"{filename}.xlsx"
    return filename


def _keyword_comparison_output_path(
    root_dir: Path,
    *,
    site: str,
    own_asin: str,
) -> Path:
    """生成流量词对比官方语义文件名。"""
    timestamp = datetime.now().strftime("%y%m%d-%H%M%S")
    filename = (
        f"CompareKeywords-{site.upper()}-"
        f"{_sanitize_filename_part(own_asin)}-{timestamp}.xlsx"
    )
    if len(str(root_dir / filename)) >= WINDOWS_COMPAT_EXPORT_PATH_LIMIT:
        filename = "CompareKeywords.xlsx"
    return root_dir / filename


def _aba_research_output_path(
    root_dir: Path,
    *,
    site: str,
    payload: dict[str, Any],
) -> Path:
    """生成 ABA 数据选品官方语义文件名。"""
    table = str(payload.get("table") or "").removeprefix("ara_")
    reverse_type = str(payload.get("reverseType") or "W").upper()
    if reverse_type == "M" and re.fullmatch(r"\d{6}", table):
        period_label = f"{table[:4]}年{int(table[4:])}月"
    elif re.fullmatch(r"\d{8}", table):
        week_end = datetime.strptime(table, "%Y%m%d")
        week_number = int(week_end.strftime("%U")) + 1
        period_label = f"{week_end.year}第{week_number}周"
    else:
        period_label = table or "latest"
    filename = f"ABAKeywordTrend-{site.upper()}-{period_label}.xlsx"
    if len(str(root_dir / filename)) >= WINDOWS_COMPAT_EXPORT_PATH_LIMIT:
        filename = "ABAKeywordTrend.xlsx"
    return root_dir / filename


def _export_output_path(root_dir: Path, job_id: str, extension: str) -> Path:
    suffix = extension.lstrip(".")
    candidate = root_dir / f"{job_id}.{suffix}"
    if len(str(candidate)) >= WINDOWS_COMPAT_EXPORT_PATH_LIMIT:
        return root_dir / f"export.{suffix}"
    return candidate


def _normalize_export_format(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        raise SellerSpriteConfigError("请指定导出格式：xls 或 json；如需表格导出再使用 xls，避免默认生成过大的文件")
    if text in {"xls", "xlsx"}:
        return "xlsx"
    if text == "json":
        return "json"
    raise SellerSpriteConfigError(f"不支持的导出格式：{value}")


def _export_rows_to_json(
    *,
    output_path: Path,
    job_id: str,
    scenario: str,
    site: str,
    period: str,
    rows: list[dict[str, Any]],
    high_frequency_rows: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
):
    from opscli.seller_sprite.domain.models import SellerSpriteExportResult

    payload = {
        "job_id": job_id,
        "scenario": scenario,
        "site": site,
        "period": period,
        "row_count": len(rows),
        "rows": rows,
        "high_frequency_rows": high_frequency_rows,
        "warnings": warnings,
    }
    _write_json(output_path, payload)
    resolved_output = output_path.resolve()
    return SellerSpriteExportResult(
        path=str(resolved_output),
        filename=resolved_output.name,
        url=resolved_output.as_uri(),
        format="json",
        mime_type="application/json",
    )


def _upload_export_if_enabled(
    *,
    export,
    job_id: str,
    scenario: str,
    site: str,
    period: str,
    warnings: list[dict[str, Any]],
    jwt: str | None = None,
    session_id: str | None = None,
) -> None:
    client = FileUploadClient(jwt=jwt, session_id=session_id)
    if not client.enabled:
        return
    try:
        upload = client.upload(
            export.path,
            purpose="seller_sprite_export",
            folder="seller-sprite/exports",
            public="1",
            metadata={
                "job_id": job_id,
                "scenario": scenario,
                "site": site,
                "period": period,
                "filename": export.filename,
            },
        )
        export.url = upload.url
    except FileUploadError as exc:
        warnings.append(
            {
                "stage": "file_upload",
                "message": "导出文件上传失败，已保留服务端本地文件",
                "error": exc.to_dict(),
            }
        )
    except Exception as exc:
        warnings.append(
            {
                "stage": "file_upload",
                "message": "导出文件上传失败，已保留服务端本地文件",
                "error": {
                    "code": type(exc).__name__,
                    "message": str(exc),
                },
            }
        )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
