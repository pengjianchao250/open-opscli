"""Sif 查销量 provider。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.sif.client import SifApiClient
from opscli.sif.common import parse_sections
from opscli.sif.config import SifSettings, load_settings
from opscli.sif.sales.export import save_xlsx_bytes
from opscli.sif.sales.models import SifSalesRunRequest, SifSalesRunResult
from opscli.sif.sales.normalizer import SifSalesNormalizer
from opscli.sif.sites import normalize_site


DEFAULT_SALES_SECTIONS = ["listing_history", "bought_by_asin"]
SALES_SECTION_ALIASES = {
    "不同变体销量": "listing_history",
    "变体销量": "listing_history",
    "下载图表": "listing_history",
    "listing_history": "listing_history",
    "同组变体销量": "bought_by_asin",
    "同组销量": "bought_by_asin",
    "下载搜索结果": "bought_by_asin",
    "bought_by_asin": "bought_by_asin",
}


class SifSalesProvider:
    """执行 Sif 关键词平台查销量。"""

    def __init__(self, *, client: SifApiClient | None = None, normalizer: SifSalesNormalizer | None = None) -> None:
        self.client = client or SifApiClient()
        self._client_injected = client is not None
        self.normalizer = normalizer or SifSalesNormalizer()

    def run(self, request: SifSalesRunRequest, *, default_output_dir: Path) -> SifSalesRunResult:
        """执行 Sif 查销量并落盘。"""
        asin = request.asin.strip().upper()
        site = normalize_site(request.site)
        sections = parse_sections(request.sections, DEFAULT_SALES_SECTIONS, SALES_SECTION_ALIASES)
        job_id = request.job_id or _build_job_id(asin)
        root_dir = self._root_dir(request.output_dir, default_output_dir, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)

        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"

        _write_json(params_path, self._params_payload(request=request, asin=asin, site=site, job_id=job_id, sections=sections))
        client = self._client_for_request(request)
        api_result = client.fetch_sales(
            asin=asin,
            site=site,
            range_value=request.range_value,
            time_piece_type=request.time_piece_type,
            time_piece_value=request.time_piece_value,
            page_num=request.page_num,
            page_size=request.page_size,
            download_listing_history="listing_history" in sections,
            download_bought_by_asin="bought_by_asin" in sections,
        )

        raw_payload = {
            "listing_history_response": api_result.listing_history,
            "group_variants_response": api_result.group_variants,
        }
        _write_json(raw_path, raw_payload)

        timestamp_ms = int(datetime.now().timestamp() * 1000)
        exports = {}
        if "listing_history" in sections:
            exports["listing_history_xlsx"] = save_xlsx_bytes(
                content=api_result.listing_history_xlsx,
                output_path=root_dir / f"boughtListingHistory_{asin}_{timestamp_ms}.xlsx",
            )
        if "bought_by_asin" in sections:
            exports["bought_by_asin_xlsx"] = save_xlsx_bytes(
                content=api_result.bought_by_asin_xlsx,
                output_path=root_dir / f"boughtByAsin_{asin}_{timestamp_ms}.xlsx",
            )
        result_payload = self.normalizer.normalize(
            asin=asin,
            site=site,
            range_value=request.range_value,
            time_piece_type=request.time_piece_type,
            time_piece_value=request.time_piece_value,
            page_num=request.page_num,
            page_size=request.page_size,
            listing_history=api_result.listing_history,
            group_variants=api_result.group_variants,
            exports={key: value.to_dict() for key, value in exports.items()},
        )
        _write_json(result_path, result_payload)

        return SifSalesRunResult(
            job_id=job_id,
            feature="查销量",
            provider="sif",
            asin=asin,
            site=site,
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
            exports=exports,
            summary=result_payload.get("summary", {}),
        )

    def _root_dir(self, output_dir: str | None, default_output_dir: Path, job_id: str) -> Path:
        base_dir = Path(output_dir).expanduser() if output_dir else default_output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / job_id

    def _params_payload(
        self,
        *,
        request: SifSalesRunRequest,
        asin: str,
        site: str,
        job_id: str,
        sections: list[str],
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "feature": "查销量",
            "provider": "sif",
            "asin": asin,
            "site": site,
            "range": request.range_value,
            "time_piece_type": request.time_piece_type,
            "time_piece_value": request.time_piece_value,
            "page_num": request.page_num,
            "page_size": request.page_size,
            "sections": sections,
            "cdp_url": request.cdp_url,
            "new_chrome": request.new_chrome,
            "params": request.params,
            "auth_mode": "credentials" if request.sif_username or request.sif_password else "configured",
        }

    def _client_for_request(self, request: SifSalesRunRequest) -> SifApiClient:
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


def _build_job_id(asin: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    return f"sif-sales-{asin}-{timestamp}-{suffix}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
