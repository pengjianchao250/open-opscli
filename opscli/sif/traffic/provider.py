"""Sif traffic provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opscli.sif.client import SifApiClient
from opscli.sif.common import build_job_id, parse_sections, resolve_root_dir, timestamp_ms, write_json
from opscli.sif.config import SifSettings, load_settings
from opscli.sif.domain.models import SifExportResult, SifRunRequest, SifRunResult
from opscli.sif.export import save_sif_xlsx
from opscli.sif.sites import normalize_site
from opscli.sif.traffic.scenarios import (
    DEFAULT_TRAFFIC_SECTIONS,
    TRAFFIC_KEYWORDS_PATH,
    TRAFFIC_MULTI_NF_PATH,
    TRAFFIC_SECTION_ALIASES,
    TRAFFIC_STRUCTURE_PATH,
    asin_keyword_list_payload,
    asin_multi_nf_payload,
    listing_score_chart_query,
    traffic_referer,
)


class SifTrafficProvider:
    """Execute Sif traffic exports for a single ASIN."""

    def __init__(self, *, client: SifApiClient | None = None) -> None:
        self.client = client or SifApiClient()
        self._client_injected = client is not None

    def run(self, request: SifRunRequest, *, default_output_dir: Path) -> SifRunResult:
        asin = request.asin.strip().upper()
        site = normalize_site(request.site)
        sections = parse_sections(request.sections, DEFAULT_TRAFFIC_SECTIONS, TRAFFIC_SECTION_ALIASES)
        job_id = request.job_id or build_job_id("sif-traffic", asin)
        root_dir = resolve_root_dir(request.output_dir, default_output_dir, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)

        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"
        query = {
            "time_piece_type": request.time_piece_type,
            "time_piece_value": str(request.time_piece_value),
            "sections": sections,
            "page_num": request.page_num,
            "page_size": request.page_size,
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
        now = timestamp_ms()

        if "structure" in sections:
            section_query = listing_score_chart_query(
                asin=asin,
                country=site,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
            )
            headers = {
                "Origin": "https://www.sif.com",
                "Referer": traffic_referer(
                    asin=asin,
                    country=site,
                    time_piece_type=request.time_piece_type,
                    time_piece_value=str(request.time_piece_value),
                ),
            }
            content = client.download_get(TRAFFIC_STRUCTURE_PATH, query=section_query, country=site, headers=headers)
            exports["traffic_structure_xlsx"] = save_sif_xlsx(
                content=content,
                output_path=root_dir / f"流量结构_{asin}_{now}.xlsx",
            )
            requests.append({"section": "structure", "method": "GET", "path": TRAFFIC_STRUCTURE_PATH, "query": section_query})

        if "keywords" in sections:
            payload = asin_keyword_list_payload(
                asin=asin,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
                page_num=request.page_num,
                page_size=request.page_size or 50,
            )
            content = client.download_post(TRAFFIC_KEYWORDS_PATH, payload=payload, country=site)
            exports["traffic_keywords_xlsx"] = save_sif_xlsx(
                content=content,
                output_path=root_dir / f"反查流量词_{asin}_{now}.xlsx",
            )
            requests.append({"section": "keywords", "method": "POST", "path": TRAFFIC_KEYWORDS_PATH, "payload": payload})

        if "multi_nf" in sections:
            payload = asin_multi_nf_payload(
                asin=asin,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
                page_num=request.page_num,
                page_size=request.page_size or 100,
            )
            content = client.download_post(TRAFFIC_MULTI_NF_PATH, payload=payload, country=site)
            exports["multi_nf_keywords_xlsx"] = save_sif_xlsx(
                content=content,
                output_path=root_dir / f"多变体自然位_{asin}_{now}.xlsx",
            )
            requests.append({"section": "multi_nf", "method": "POST", "path": TRAFFIC_MULTI_NF_PATH, "payload": payload})

        raw_payload = {"requests": requests, "exports": {key: value.to_dict() for key, value in exports.items()}}
        write_json(raw_path, raw_payload)
        result_payload = {
            "schema_version": "sif_traffic.v1",
            "feature": request.feature,
            "provider": "sif",
            "asin": asin,
            "asins": [asin],
            "site": site,
            "query": query,
            "summary": {"export_count": len(exports), "warning_count": 0},
            "exports": {key: value.to_dict() for key, value in exports.items()},
            "requests": requests,
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
