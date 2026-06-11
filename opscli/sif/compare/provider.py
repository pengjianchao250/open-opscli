"""Sif multi-product compare provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opscli.sif.client import SifApiClient
from opscli.sif.common import build_job_id, parse_asins, parse_sections, resolve_root_dir, timestamp_ms, write_json
from opscli.sif.config import SifSettings, load_settings
from opscli.sif.domain.models import SifExportResult, SifRunRequest, SifRunResult
from opscli.sif.export import save_sif_xlsx
from opscli.sif.sites import normalize_site
from opscli.sif.compare.scenarios import (
    COMPARE_MY_KEYWORDS_PATH,
    COMPARE_SALES_PATH,
    COMPARE_SECTION_ALIASES,
    COMPARE_SUMMARY_PATH,
    DEFAULT_COMPARE_SECTIONS,
    compare_my_keywords_payload,
    compare_sales_payload,
    compare_summary_payload,
)


class SifCompareProvider:
    """Execute Sif multi-product compare exports."""

    def __init__(self, *, client: SifApiClient | None = None) -> None:
        self.client = client or SifApiClient()
        self._client_injected = client is not None

    def run(self, request: SifRunRequest, *, default_output_dir: Path) -> SifRunResult:
        asins = request.asins or parse_asins(request.asin)
        asins = [asin.upper() for asin in asins]
        if len(asins) < 2:
            raise ValueError("多产品对比至少需要 2 个 ASIN，请用英文逗号分隔。")
        site = normalize_site(request.site)
        sections = parse_sections(request.sections, DEFAULT_COMPARE_SECTIONS, COMPARE_SECTION_ALIASES)
        key = f"{len(asins)}asins"
        job_id = request.job_id or build_job_id("sif-compare", key)
        root_dir = resolve_root_dir(request.output_dir, default_output_dir, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)

        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"
        query = {
            "time_piece_type": request.time_piece_type,
            "time_piece_value": str(request.time_piece_value),
            "sections": sections,
            "my_asin": (request.my_asin or asins[0]).upper(),
            "page_num": request.page_num,
            "page_size": request.page_size,
        }
        write_json(
            params_path,
            {
                "job_id": job_id,
                "feature": request.feature,
                "provider": "sif",
                "asins": asins,
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

        def save_section(key_name: str, path: str, payload: dict[str, Any], filename: str) -> None:
            content = client.download_post(path, payload=payload, country=site)
            exports[key_name] = save_sif_xlsx(content=content, output_path=root_dir / filename)
            requests.append({"section": key_name, "method": "POST", "path": path, "payload": payload})

        if "sales" in sections:
            payload = compare_sales_payload(
                asins=asins,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
                page_num=request.page_num,
                page_size=request.page_size or 100,
            )
            save_section("compare_sales_xlsx", COMPARE_SALES_PATH, payload, f"对比销量_{len(asins)}个ASIN_{now}.xlsx")

        if "traffic_words" in sections:
            payload = compare_summary_payload(
                asins=asins,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
                show_type=1,
            )
            save_section(
                "compare_traffic_words_xlsx",
                COMPARE_SUMMARY_PATH,
                payload,
                f"对比流量词_{len(asins)}个ASIN_{now}.xlsx",
            )

        if "traffic_score" in sections:
            payload = compare_summary_payload(
                asins=asins,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
                show_type=2,
            )
            save_section(
                "compare_traffic_score_xlsx",
                COMPARE_SUMMARY_PATH,
                payload,
                f"对比流量分_{len(asins)}个ASIN_{now}.xlsx",
            )

        if "my_traffic_keywords" in sections:
            payload = compare_my_keywords_payload(
                asins=asins,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
                list_type=1,
                page_num=request.page_num,
                page_size=request.page_size or 10,
            )
            save_section(
                "compare_my_traffic_keywords_xlsx",
                COMPARE_MY_KEYWORDS_PATH,
                payload,
                f"重点流量词_{len(asins)}个ASIN_{now}.xlsx",
            )

        if "my_ad_keywords" in sections:
            payload = compare_my_keywords_payload(
                asins=asins,
                time_piece_type=request.time_piece_type,
                time_piece_value=str(request.time_piece_value),
                list_type=2,
                page_num=request.page_num,
                page_size=request.page_size or 10,
            )
            save_section(
                "compare_my_ad_keywords_xlsx",
                COMPARE_MY_KEYWORDS_PATH,
                payload,
                f"重点广告词_{len(asins)}个ASIN_{now}.xlsx",
            )

        raw_payload = {"requests": requests, "exports": {key: value.to_dict() for key, value in exports.items()}}
        write_json(raw_path, raw_payload)
        result_payload = {
            "schema_version": "sif_compare.v1",
            "feature": request.feature,
            "provider": "sif",
            "asins": asins,
            "site": site,
            "query": query,
            "summary": {"asin_count": len(asins), "export_count": len(exports), "warning_count": 0},
            "exports": {key: value.to_dict() for key, value in exports.items()},
            "requests": requests,
            "warnings": [],
        }
        write_json(result_path, result_payload)
        return SifRunResult(
            job_id=job_id,
            feature=request.feature,
            provider="sif",
            asins=asins,
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
