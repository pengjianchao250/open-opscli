"""Sif product time machine provider."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from opscli.sif.client import SifApiClient
from opscli.sif.common import build_job_id, parse_sections, resolve_root_dir, timestamp_ms, write_json
from opscli.sif.config import SifSettings, load_settings
from opscli.sif.domain.models import SifExportResult, SifRunRequest, SifRunResult
from opscli.sif.export import save_sif_xlsx
from opscli.sif.product_time_machine.scenarios import (
    DEFAULT_PRODUCT_TIME_MACHINE_SECTIONS,
    PRODUCT_TIME_MACHINE_DOWNLOAD_PATH,
    PRODUCT_TIME_MACHINE_LIST_PATH,
    PRODUCT_TIME_MACHINE_SECTION_ALIASES,
    product_time_machine_download_payload,
    product_time_machine_list_payload,
)
from opscli.sif.sites import normalize_site


class SifProductTimeMachineProvider:
    """Execute Sif product time machine exports."""

    def __init__(self, *, client: SifApiClient | None = None) -> None:
        self.client = client or SifApiClient()
        self._client_injected = client is not None

    def run(self, request: SifRunRequest, *, default_output_dir: Path) -> SifRunResult:
        keyword = (request.keyword or request.params.get("keyword") or "").strip()
        if not keyword:
            raise ValueError("产品时光机需要关键词，请通过 --keyword 传入。")
        site = normalize_site(request.site)
        sections = parse_sections(request.sections, DEFAULT_PRODUCT_TIME_MACHINE_SECTIONS, PRODUCT_TIME_MACHINE_SECTION_ALIASES)
        safe_keyword = _safe_filename_part(keyword)
        job_id = request.job_id or build_job_id("sif-product-time-machine", safe_keyword)
        root_dir = resolve_root_dir(request.output_dir, default_output_dir, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)

        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"
        query = {
            "keyword": keyword,
            "time_piece_type": request.time_piece_type,
            "time_piece_value": str(request.time_piece_value),
            "sections": sections,
            "page_num": request.page_num,
            "page_size": request.page_size or 100,
        }
        write_json(
            params_path,
            {
                "job_id": job_id,
                "feature": request.feature,
                "provider": "sif",
                "keyword": keyword,
                "site": site,
                "query": query,
                "params": request.params,
                "auth_mode": "credentials" if request.sif_username or request.sif_password else "configured",
            },
        )

        client = self._client_for_request(request)
        exports: dict[str, SifExportResult] = {}
        requests: list[dict[str, Any]] = []
        list_payload = product_time_machine_list_payload(
            keyword=keyword,
            time_piece_type=request.time_piece_type,
            time_piece_value=str(request.time_piece_value),
            page_num=request.page_num,
            page_size=request.page_size or 100,
        )
        list_response = client.post_json(PRODUCT_TIME_MACHINE_LIST_PATH, payload=list_payload, country=site)
        requests.append({"section": "product_time_machine", "purpose": "list", "method": "POST", "path": PRODUCT_TIME_MACHINE_LIST_PATH, "payload": list_payload})

        if "product_time_machine" in sections:
            download_payload = product_time_machine_download_payload(
                keyword=keyword,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
            )
            content = client.download_post(PRODUCT_TIME_MACHINE_DOWNLOAD_PATH, payload=download_payload, country=site)
            exports["product_time_machine_xlsx"] = save_sif_xlsx(
                content=content,
                output_path=root_dir / f"产品时光机_{safe_keyword}_{timestamp_ms()}.xlsx",
            )
            requests.append(
                {
                    "section": "product_time_machine",
                    "purpose": "download",
                    "method": "POST",
                    "path": PRODUCT_TIME_MACHINE_DOWNLOAD_PATH,
                    "payload": download_payload,
                }
            )

        raw_payload = {
            "list_response": list_response,
            "requests": requests,
            "exports": {key: value.to_dict() for key, value in exports.items()},
        }
        write_json(raw_path, raw_payload)
        result_payload = {
            "schema_version": "sif_product_time_machine.v1",
            "feature": request.feature,
            "provider": "sif",
            "keyword": keyword,
            "site": site,
            "query": query,
            "summary": {"export_count": len(exports), "list_item_count": _list_item_count(list_response), "warning_count": 0},
            "exports": {key: value.to_dict() for key, value in exports.items()},
            "requests": requests,
            "list_response": list_response,
            "warnings": [],
        }
        write_json(result_path, result_payload)
        return SifRunResult(
            job_id=job_id,
            feature=request.feature,
            provider="sif",
            keyword=keyword,
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


def _safe_filename_part(value: str) -> str:
    text = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.UNICODE).strip("_")
    return text or "keyword"


def _list_item_count(response: dict[str, Any]) -> int:
    data = response.get("data")
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("list", "items", "records", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
    return 0
