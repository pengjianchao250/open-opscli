"""卖家精灵接口直连任务编排。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.seller_sprite.accounts import SellerSpriteAccountProvider
from opscli.seller_sprite.api.client import SellerSpriteApiClient
from opscli.seller_sprite.api.market_research import parse_market_research_html
from opscli.seller_sprite.api.scenarios import get_scenario, list_scenarios
from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError, SellerSpriteConfigError
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest, SellerSpriteScenarioResult
from opscli.seller_sprite.export.xlsx import export_rows_to_xlsx
from opscli.shared.file_uploads import FileUploadClient, FileUploadError


class SellerSpriteApiManager:
    """执行卖家精灵接口场景并落盘任务结果。"""

    def __init__(
        self,
        *,
        settings: SellerSpriteSettings | None = None,
        account_provider: SellerSpriteAccountProvider | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.account_provider = account_provider or SellerSpriteAccountProvider(self.settings)

    def scenarios(self) -> list[dict[str, Any]]:
        """列出支持的接口场景。"""
        return list_scenarios()

    async def run(self, request: SellerSpriteScenarioRequest) -> SellerSpriteScenarioResult:
        """执行一个接口场景。"""
        scenario = get_scenario(request.scenario)
        job_id = request.job_id or _build_job_id(request.scenario)
        root_dir = self._build_root_dir(request, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)

        site = (request.site or self.settings.default_site).upper()
        period = request.period or self.settings.default_period
        page_size = request.page_size or self.settings.page_size
        payload = scenario.build_payload(params=request.params, site=site, period=period, page_size=page_size)

        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"
        _write_json(
            params_path,
            {
                "request": request.to_dict(),
                "payload": payload,
            },
        )

        account = self.account_provider.get_default()
        warnings: list[dict[str, Any]] = []
        async with SellerSpriteApiClient(account=account) as client:
            login = {"mode": "cached", "cookie_names": client.cookie_names()}
            if not client.has_login_cookies():
                login = await _login_with_account_refresh(
                    client=client,
                    account_provider=self.account_provider,
                    warnings=warnings,
                )
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
            "login": login,
            "payload": payload,
            "response": main_response,
            "high_frequency_response": high_frequency_response,
            "warnings": warnings,
        }
        _write_json(raw_path, raw)

        rows = _extract_items(main_response)
        high_frequency_rows = _extract_high_frequency_rows(high_frequency_response)
        export_format = _normalize_export_format(request.export_format)
        if export_format == "xlsx":
            export = export_rows_to_xlsx(
                rows=rows,
                output_path=root_dir / f"{job_id}.xlsx",
                scenario=request.scenario,
                site=site,
                period=period,
                params=request.params,
                high_frequency_rows=high_frequency_rows,
            )
        else:
            export = _export_rows_to_json(
                output_path=root_dir / f"{job_id}.json",
                job_id=job_id,
                scenario=request.scenario,
                site=site,
                period=period,
                rows=rows,
                high_frequency_rows=high_frequency_rows,
                warnings=warnings,
            )
        _upload_export_if_enabled(
            export=export,
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            period=period,
            warnings=warnings,
        )
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
            raise SellerSpriteConfigError(f"任务不存在：{job_id}")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def _build_root_dir(self, request: SellerSpriteScenarioRequest, job_id: str) -> Path:
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
    if method == "GET":
        return await client.get_json(endpoint, payload, referer=referer)
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
        return _without(payload, {"market", "includeHighFrequency", "groupNum", "page"})
    return payload


def _high_frequency_payload(scenario: str, payload: dict[str, Any]) -> dict[str, Any]:
    """构造高频词接口 payload。"""
    if scenario == "keyword-reverse":
        body = _without(payload, {"market", "includeHighFrequency", "groupNum", "page", "limit", "skip"})
        body["groupNum"] = int(payload.get("groupNum") or 1)
        return body
    return payload


def _without(payload: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in keys}


def _extract_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [item for item in data["items"] if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("pager"), dict):
        pager = data["pager"]
        if isinstance(pager.get("items"), list):
            return [item for item in pager["items"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _looks_like_guest_limited_response(response: dict[str, Any], *, page_size: int) -> bool:
    if page_size <= 20:
        return False
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False
    items = data.get("items")
    if not isinstance(items, list) or len(items) != 20:
        return False
    total = _int(data.get("total"), 0)
    pages = _int(data.get("pages"), 0)
    size = _int(data.get("size"), 0)
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


def _build_job_id(scenario: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    return f"seller-sprite-{scenario}-{timestamp}-{suffix}"


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
) -> None:
    client = FileUploadClient()
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
