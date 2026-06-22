"""Sif operation time machine provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opscli.sif.client import SifApiClient
from opscli.sif.common import build_job_id, parse_sections, resolve_root_dir, timestamp_ms, write_json
from opscli.sif.config import SifSettings, load_settings
from opscli.sif.domain.models import SifExportResult, SifRunRequest, SifRunResult
from opscli.sif.export import save_sif_xlsx
from opscli.sif.operation_time_machine.scenarios import (
    DEFAULT_OPERATION_TIME_MACHINE_SECTIONS,
    OPERATION_TIME_MACHINE_DOWNLOAD_PATH,
    OPERATION_TIME_MACHINE_LIST_PATH,
    OPERATION_TIME_MACHINE_SECTION_ALIASES,
    change_type_for_section,
    normalize_last_months,
    normalize_operation_granularity,
    operation_time_machine_payload,
)
from opscli.sif.sites import normalize_site


class SifOperationTimeMachineProvider:
    """Execute Sif operation time machine exports."""

    def __init__(self, *, client: SifApiClient | None = None) -> None:
        self.client = client or SifApiClient()
        self._client_injected = client is not None

    def run(self, request: SifRunRequest, *, default_output_dir: Path) -> SifRunResult:
        asin = request.asin.strip().upper()
        if not asin:
            raise ValueError("运营时光机需要 ASIN，请通过 --asin 传入。")
        site = normalize_site(request.site)
        granularity = normalize_operation_granularity(request.granularity)
        last_months = normalize_last_months(request.last_months)
        sections = parse_sections(request.sections, DEFAULT_OPERATION_TIME_MACHINE_SECTIONS, OPERATION_TIME_MACHINE_SECTION_ALIASES)
        if request.change_type == "all" and not request.sections:
            sections = ["keyword_count_change"]
        job_id = request.job_id or build_job_id("sif-operation-time-machine", asin)
        root_dir = resolve_root_dir(request.output_dir, default_output_dir, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)

        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"
        query = {
            "granularity": granularity,
            "last_months": last_months,
            "change_type": request.change_type,
            "sections": sections,
        }
        write_json(
            params_path,
            {
                "job_id": job_id,
                "feature": request.feature,
                "provider": "sif",
                "asin": asin,
                "site": site,
                "query": query,
                "params": request.params,
                "auth_mode": "credentials" if request.sif_username or request.sif_password else "configured",
            },
        )

        client = self._client_for_request(request)
        exports: dict[str, SifExportResult] = {}
        requests: list[dict[str, Any]] = []
        list_responses: dict[str, Any] = {}

        for section in sections:
            change_type = change_type_for_section(section, request.change_type)
            payload = operation_time_machine_payload(
                asin=asin,
                granularity=granularity,
                last_months=last_months,
                change_type=change_type,
            )
            list_response = client.post_json(OPERATION_TIME_MACHINE_LIST_PATH, payload=payload, country=site)
            list_responses[section] = list_response
            requests.append({"section": section, "purpose": "list", "method": "POST", "path": OPERATION_TIME_MACHINE_LIST_PATH, "payload": payload})

            content = client.download_post(OPERATION_TIME_MACHINE_DOWNLOAD_PATH, payload=payload, country=site)
            label = "流量词数量变化" if section == "keyword_count_change" else "流量变化"
            export_key = "operation_keyword_count_change_xlsx" if section == "keyword_count_change" else "operation_traffic_change_xlsx"
            exports[export_key] = save_sif_xlsx(
                content=content,
                output_path=root_dir / f"运营时光机_{label}_{asin}_{timestamp_ms()}.xlsx",
            )
            requests.append(
                {
                    "section": section,
                    "purpose": "download",
                    "method": "POST",
                    "path": OPERATION_TIME_MACHINE_DOWNLOAD_PATH,
                    "payload": payload,
                }
            )

        raw_payload = {
            "list_responses": list_responses,
            "requests": requests,
            "exports": {key: value.to_dict() for key, value in exports.items()},
        }
        write_json(raw_path, raw_payload)
        result_payload = {
            "schema_version": "sif_operation_time_machine.v1",
            "feature": request.feature,
            "provider": "sif",
            "asin": asin,
            "asins": [asin],
            "site": site,
            "query": query,
            "summary": {"export_count": len(exports), "list_item_count": _list_item_count(list_responses), "warning_count": 0},
            "exports": {key: value.to_dict() for key, value in exports.items()},
            "requests": requests,
            "list_responses": list_responses,
            "warnings": [],
        }
        write_json(result_path, result_payload)
        return SifRunResult(
            job_id=job_id,
            feature=request.feature,
            provider="sif",
            asin=asin,
            asins=[asin],
            site=site,
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
            exports=exports,
            summary=result_payload["summary"],
        )

    def _client_for_request(self, request: SifRunRequest) -> SifApiClient:
        if self._client_injected:
            return self.client
        if not (request.sif_username or request.sif_password):
            return self.client
        settings = load_settings()
        return SifApiClient(
            settings=SifSettings(
                base_url=settings.base_url,
                cookie=settings.cookie,
                token=settings.token,
                username=request.sif_username or settings.username,
                password=request.sif_password or settings.password,
                output_dir=settings.output_dir,
            ),
            timeout=request.timeout,
        )


def _list_item_count(responses: dict[str, Any]) -> int:
    count = 0
    for response in responses.values():
        if isinstance(response, dict):
            data = response.get("data")
            if isinstance(data, list):
                count += len(data)
            elif isinstance(data, dict):
                for key in ("list", "items", "records", "rows", "data"):
                    value = data.get(key)
                    if isinstance(value, list):
                        count += len(value)
                        break
    return count
