"""卖家精灵接口直连任务编排。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.seller_sprite.accounts import SellerSpriteAccountProvider
from opscli.seller_sprite.api.client import SellerSpriteApiClient
from opscli.seller_sprite.api.scenarios import get_scenario, list_scenarios
from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError, SellerSpriteConfigError
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest, SellerSpriteScenarioResult
from opscli.seller_sprite.export.xlsx import export_rows_to_xlsx


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
            login = await client.login()
            main_response = await client.post_json(
                scenario.endpoint_for(payload),
                _main_payload(request.scenario, payload),
                referer=scenario.build_referer(payload),
            )
            high_frequency_response = None
            if payload.get("includeHighFrequency") and scenario.high_frequency_endpoint_for(payload):
                try:
                    high_frequency_response = await client.post_json(
                        scenario.high_frequency_endpoint_for(payload) or "",
                        _high_frequency_payload(request.scenario, payload),
                        referer=scenario.build_referer(payload),
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
        export = None
        if request.export_format == "xlsx":
            export = export_rows_to_xlsx(
                rows=rows,
                output_path=root_dir / f"{job_id}.xlsx",
                scenario=request.scenario,
                site=site,
                period=period,
                params=request.params,
                high_frequency_rows=high_frequency_rows,
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
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _extract_high_frequency_rows(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _build_job_id(scenario: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    return f"seller-sprite-{scenario}-{timestamp}-{suffix}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
