"""Keepa API 场景执行和落盘。"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.keepa.accounts import KeepaApiKeyProvider
from opscli.keepa.api.client import KeepaApiClient
from opscli.keepa.api.scenarios import get_scenario, list_scenarios
from opscli.keepa.best_sellers_formatter import FormattedBestSellersExport, format_best_sellers_export
from opscli.keepa.config import KeepaSettings, load_settings
from opscli.keepa.domain.exceptions import KeepaApiError, KeepaConfigError
from opscli.keepa.domain.models import KeepaExportResult, KeepaScenarioRequest, KeepaScenarioResult
from opscli.keepa.export.xlsx import export_rows_to_xlsx
from opscli.keepa.product_formatter import FormattedProductExport, format_product_export
from opscli.keepa.search_insights_formatter import FormattedSearchInsightsExport, format_search_insights_export
from opscli.keepa.time import add_keepa_time_conversions
from opscli.shared.file_uploads import FileUploadClient, FileUploadError
from opscli.shared.integration_accounts import IntegrationAccountClient


MAX_XLSX_EXPORT_ROWS = 5_000


class KeepaApiManager:
    """执行 Keepa API 场景并保存请求和响应数据。"""

    def __init__(
        self,
        *,
        settings: KeepaSettings | None = None,
        api_key_provider: KeepaApiKeyProvider | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.jwt = jwt
        self.session_id = session_id
        self.api_key_provider = api_key_provider or KeepaApiKeyProvider(
            self.settings,
            integration_client=IntegrationAccountClient(jwt=jwt, session_id=session_id),
        )

    def scenarios(self) -> list[dict[str, Any]]:
        """列出支持的接口场景。"""
        return list_scenarios()

    async def token_status(self) -> dict[str, Any]:
        """读取 Keepa API token 状态。"""
        credential = self.api_key_provider.get_default()
        async with KeepaApiClient(api_key=credential.api_key) as client:
            payload = await client.token_status()
        return {
            "account": credential.to_public_dict(),
            "quota": extract_quota(payload),
            "raw": payload,
        }

    async def run(self, request: KeepaScenarioRequest) -> KeepaScenarioResult:
        """执行一个 Keepa API 场景。"""
        scenario = get_scenario(request.scenario)
        site = (request.site or "US").upper()
        job_id = request.job_id or _build_job_id(request, site)
        root_dir = self._build_root_dir(request, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)
        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"

        credential = self.api_key_provider.get_default()
        normalized_params = scenario.build_params(params=request.params, site=site)
        estimated_tokens = scenario.estimate_tokens(request.params)
        reserve_tokens = self.settings.reserve_tokens if request.reserve_tokens is None else request.reserve_tokens
        warnings: list[dict[str, Any]] = []

        async with KeepaApiClient(api_key=credential.api_key) as client:
            before_status = await _safe_token_status(client, warnings)
            before_quota = extract_quota(before_status)
            quota_warning = _build_quota_warning(
                before_quota=before_quota,
                estimated_tokens=estimated_tokens,
                reserve_tokens=reserve_tokens,
            )
            if quota_warning:
                warnings.append(quota_warning)
                if not request.force and not request.wait:
                    _write_json(
                        params_path,
                        _params_payload(
                            request=request,
                            scenario=scenario.to_public_dict(),
                            normalized_params=normalized_params,
                            account=credential.to_public_dict(),
                            estimated_tokens=estimated_tokens,
                            reserve_tokens=reserve_tokens,
                        ),
                    )
                    raise KeepaConfigError(
                        "Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。"
                    )
                if request.wait:
                    await _wait_for_refill(client, before_quota, warnings)
                    before_status = await _safe_token_status(client, warnings)
                    before_quota = extract_quota(before_status)

            _write_json(
                params_path,
                _params_payload(
                    request=request,
                    scenario=scenario.to_public_dict(),
                    normalized_params=normalized_params,
                    account=credential.to_public_dict(),
                    estimated_tokens=estimated_tokens,
                    reserve_tokens=reserve_tokens,
                    before_quota=before_quota,
                ),
            )

            raw_response = await client.get_json(scenario.endpoint, normalized_params)
            after_status = await _safe_token_status(client, warnings)

        raw_payload = {
            "job_id": job_id,
            "scenario": request.scenario,
            "site": site,
            "endpoint": scenario.endpoint,
            "request_params": normalized_params,
            "before_status": before_status,
            "response": raw_response,
            "after_status": after_status,
            "warnings": warnings,
        }
        _write_json(raw_path, raw_payload)

        raw_rows = extract_rows(raw_response)
        product_export = _format_product_rows_if_needed(
            scenario=request.scenario,
            rows=raw_rows,
            site=site,
            normalized_params=normalized_params,
        )
        search_insights_export = _format_search_insights_if_needed(
            scenario=request.scenario,
            raw_response=raw_response,
            site=site,
            normalized_params=normalized_params,
            request_params=request.params,
        )
        best_sellers_export = _format_best_sellers_if_needed(
            scenario=request.scenario,
            raw_response=raw_response,
            site=site,
            normalized_params=normalized_params,
        )
        data = _formatted_data_or_default(
            raw_rows=raw_rows,
            product_export=product_export,
            best_sellers_export=best_sellers_export,
        )
        export_format = _resolve_export_format(
            requested_format=_normalize_export_format(request.export_format),
            row_count=len(raw_rows),
            warnings=warnings,
        )
        if export_format == "xlsx":
            export_rows = _export_rows_for_xlsx(
                raw_response=raw_response,
                product_export=product_export,
                best_sellers_export=best_sellers_export,
            )
            export = export_rows_to_xlsx(
                rows=export_rows,
                output_path=root_dir / f"{job_id}.xlsx",
                scenario=request.scenario,
                site=site,
                params=request.params,
                extra_sheets=_merge_extra_sheets(product_export, search_insights_export, best_sellers_export),
            )
        else:
            export = _export_raw_to_json(
                output_path=root_dir / f"{job_id}.json",
                job_id=job_id,
                scenario=request.scenario,
                site=site,
                endpoint=scenario.endpoint,
                request_params=normalized_params,
                raw_response=raw_response,
                rows=data,
                warnings=warnings,
                formatted_tables=_formatted_tables_payload(product_export, search_insights_export, best_sellers_export),
            )
        _upload_export_if_enabled(
            export=export,
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            warnings=warnings,
            jwt=self.jwt,
            session_id=self.session_id,
        )
        quota = {
            "estimated_tokens": estimated_tokens,
            "before": extract_quota(before_status),
            "response": extract_quota(raw_response),
            "after": extract_quota(after_status),
        }
        result = KeepaScenarioResult(
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            row_count=len(data),
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
            export=export,
            data=data,
            quota=quota,
            warnings=warnings,
        )
        _write_json(result_path, result.to_dict())
        return result

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取已落盘任务状态。"""
        root_dir = self.settings.output_dir / job_id
        result_path = root_dir / "result.json"
        if not result_path.exists():
            raise KeepaConfigError(f"任务不存在：{job_id}")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def _build_root_dir(self, request: KeepaScenarioRequest, job_id: str) -> Path:
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / job_id


def extract_quota(payload: dict[str, Any] | None) -> dict[str, Any]:
    """提取 Keepa 响应中的额度字段。"""
    if not isinstance(payload, dict):
        return {}
    keys = ("tokensLeft", "refillIn", "refillRate", "tokensConsumed", "tokenFlowReduction", "timestamp")
    return {key: payload[key] for key in keys if key in payload}


def extract_rows(payload: dict[str, Any]) -> list[Any]:
    """从 Keepa 原始响应中提取主要结果列表。"""
    if not isinstance(payload, dict):
        return []
    sellers = payload.get("sellers")
    if isinstance(sellers, list):
        return sellers
    if isinstance(sellers, dict):
        return list(sellers.values())
    for key in (
        "products",
        "asinList",
        "sellerIdList",
        "lightningDeals",
        "trackings",
        "notifications",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    categories = payload.get("categories")
    if isinstance(categories, dict):
        return list(categories.values())
    deals = payload.get("deals")
    if isinstance(deals, dict):
        for key in ("dr", "deals"):
            value = deals.get(key)
            if isinstance(value, list):
                return value
        return [deals]
    bestsellers = payload.get("bestSellersList")
    if isinstance(bestsellers, dict):
        asin_list = bestsellers.get("asinList")
        if isinstance(asin_list, list):
            return asin_list
        return [bestsellers]
    total = payload.get("totalResults")
    if total is not None:
        return [{"totalResults": total}]
    return []


def raw_response_to_export_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """将 Keepa 原始响应转换成 XLSX 行，尽量保留 API 返回的全部顶层 JSON 字段。"""
    if not isinstance(payload, dict):
        return [{"value": payload}]
    row_source_key, row_items = _primary_row_items(payload)
    base_row = {
        key: value
        for key, value in payload.items()
        if key != row_source_key and key != "searchInsights"
    }
    if not row_items:
        return [dict(payload)]
    rows: list[dict[str, Any]] = []
    for item in row_items:
        row = dict(base_row)
        if row_source_key:
            row["rowSource"] = row_source_key
        if isinstance(item, dict):
            row.update(item)
        else:
            row[_scalar_item_field(row_source_key)] = item
        rows.append(row)
    return rows


def _primary_row_items(payload: dict[str, Any]) -> tuple[str | None, list[Any]]:
    for key in (
        "products",
        "sellers",
        "categories",
        "deals",
        "bestSellersList",
        "asinList",
        "sellerIdList",
        "lightningDeals",
        "trackings",
        "notifications",
    ):
        value = payload.get(key)
        rows = _rows_from_response_value(key, value)
        if rows:
            return key, rows
    return None, []


def _rows_from_response_value(key: str, value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if key == "deals":
            for child_key in ("dr", "deals"):
                child_value = value.get(child_key)
                if isinstance(child_value, list):
                    return child_value
        if key == "bestSellersList":
            asin_list = value.get("asinList")
            if isinstance(asin_list, list):
                return asin_list
        return list(value.values())
    return []


def _scalar_item_field(row_source_key: str | None) -> str:
    if row_source_key == "sellerIdList":
        return "sellerId"
    if row_source_key in {"asinList", "bestSellersList"}:
        return "asin"
    return "value"


def _format_product_rows_if_needed(
    *,
    scenario: str,
    rows: list[Any],
    site: str,
    normalized_params: dict[str, Any],
) -> FormattedProductExport | None:
    if scenario != "product":
        return None
    return format_product_export(rows, site=site, domain_id=normalized_params.get("domain"))


def _format_search_insights_if_needed(
    *,
    scenario: str,
    raw_response: dict[str, Any],
    site: str,
    normalized_params: dict[str, Any],
    request_params: dict[str, Any],
) -> FormattedSearchInsightsExport | None:
    if scenario != "product-finder":
        return None
    return format_search_insights_export(
        raw_response.get("searchInsights"),
        site=site,
        domain_id=normalized_params.get("domain"),
        query_name=_search_insights_query_name(request_params),
    )


def _format_best_sellers_if_needed(
    *,
    scenario: str,
    raw_response: dict[str, Any],
    site: str,
    normalized_params: dict[str, Any],
) -> FormattedBestSellersExport | None:
    if scenario != "bestsellers":
        return None
    return format_best_sellers_export(
        raw_response.get("bestSellersList"),
        site=site,
        domain_id=normalized_params.get("domain"),
        category_id=normalized_params.get("category"),
    )


def _formatted_data_or_default(
    *,
    raw_rows: list[Any],
    product_export: FormattedProductExport | None,
    best_sellers_export: FormattedBestSellersExport | None,
) -> list[Any]:
    if product_export:
        return product_export.products
    if best_sellers_export:
        return best_sellers_export.asin_rows
    return add_keepa_time_conversions(raw_rows)


def _export_rows_for_xlsx(
    *,
    raw_response: dict[str, Any],
    product_export: FormattedProductExport | None,
    best_sellers_export: FormattedBestSellersExport | None,
) -> list[dict[str, Any]]:
    if product_export:
        return product_export.products
    if best_sellers_export:
        return best_sellers_export.asin_rows
    return raw_response_to_export_rows(raw_response)


def _merge_extra_sheets(
    product_export: FormattedProductExport | None,
    search_insights_export: FormattedSearchInsightsExport | None,
    best_sellers_export: FormattedBestSellersExport | None,
) -> dict[str, list[dict[str, Any]]] | None:
    sheets: dict[str, list[dict[str, Any]]] = {}
    if product_export:
        sheets.update(product_export.extra_sheets())
    if search_insights_export:
        sheets.update(search_insights_export.extra_sheets())
    if best_sellers_export:
        sheets.update(best_sellers_export.extra_sheets())
    return sheets or None


def _formatted_tables_payload(
    product_export: FormattedProductExport | None,
    search_insights_export: FormattedSearchInsightsExport | None,
    best_sellers_export: FormattedBestSellersExport | None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if product_export:
        payload.update(product_export.to_dict())
    if search_insights_export:
        payload.update(search_insights_export.to_dict())
    if best_sellers_export:
        payload.update(best_sellers_export.to_dict())
    return payload or None


def _search_insights_query_name(params: dict[str, Any]) -> str:
    for key in ("queryName", "query_name", "name", "keyword", "term"):
        value = params.get(key)
        if value:
            return str(value)
    return "product-finder"


async def _safe_token_status(client: KeepaApiClient, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await client.token_status()
    except KeepaApiError as exc:
        warnings.append(
            {
                "stage": "token_status",
                "message": "读取 Keepa 可用额度状态失败，继续执行主请求",
                "error": exc.to_dict(),
            }
        )
        return {}


def _build_quota_warning(
    *,
    before_quota: dict[str, Any],
    estimated_tokens: int | None,
    reserve_tokens: int,
) -> dict[str, Any] | None:
    tokens_left = before_quota.get("tokensLeft")
    if tokens_left is None or estimated_tokens is None:
        return None
    try:
        tokens_left_int = int(tokens_left)
    except (TypeError, ValueError):
        return None
    required = max(0, estimated_tokens) + max(0, reserve_tokens)
    if tokens_left_int >= required:
        return None
    return {
        "stage": "quota_precheck",
        "message": "Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。",
        "tokens_left": tokens_left_int,
        "estimated_tokens": estimated_tokens,
        "reserve_tokens": reserve_tokens,
        "refill_in_ms": before_quota.get("refillIn"),
        "refill_rate": before_quota.get("refillRate"),
    }


async def _wait_for_refill(
    client: KeepaApiClient,
    before_quota: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    refill_in = before_quota.get("refillIn")
    try:
        wait_seconds = max(0.0, float(refill_in) / 1000.0 + 1.0)
    except (TypeError, ValueError):
        wait_seconds = 0.0
    if wait_seconds <= 0:
        return
    warnings.append(
        {
            "stage": "quota_wait",
            "message": "等待 Keepa 可用额度恢复后继续请求",
            "wait_seconds": wait_seconds,
        }
    )
    await asyncio.sleep(wait_seconds)
    await client.token_status()


def _params_payload(
    *,
    request: KeepaScenarioRequest,
    scenario: dict[str, Any],
    normalized_params: dict[str, Any],
    account: dict[str, Any],
    estimated_tokens: int | None,
    reserve_tokens: int,
    before_quota: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "request": request.to_dict(),
        "scenario": scenario,
        "account": account,
        "normalized_params": normalized_params,
        "estimated_tokens": estimated_tokens,
        "reserve_tokens": reserve_tokens,
        "before_quota": before_quota or {},
    }


def _build_job_id(request: KeepaScenarioRequest, site: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    parts = ["Keepa", _scenario_label(request.scenario), site]
    target = _build_target_label(request.scenario, request.params)
    if target:
        parts.append(target)
    parts.append(timestamp)
    parts.append(suffix)
    return "-".join(parts)


def _scenario_label(scenario: str) -> str:
    labels = {
        "product": "Product",
        "product-search": "ProductSearch",
        "product-finder": "ProductFinder",
        "category-search": "CategorySearch",
        "category-lookup": "CategoryLookup",
        "seller": "Seller",
        "top-seller": "TopSeller",
        "bestsellers": "BestSellers",
        "deals": "Deals",
        "lightning-deals": "LightningDeals",
    }
    return labels.get(scenario, _camel_case(scenario))


def _build_target_label(scenario: str, params: dict[str, Any] | None) -> str:
    if not isinstance(params, dict):
        return ""
    if scenario == "product":
        return _sanitize_filename_part(params.get("asin") or _first(params.get("asins")) or params.get("code") or _first(params.get("codes")))
    if scenario in {"product-search", "category-search"}:
        return _sanitize_filename_part(params.get("term") or params.get("keyword"))
    if scenario in {"category-lookup", "bestsellers"}:
        return _sanitize_filename_part(params.get("category") or params.get("productGroup") or params.get("product_group"))
    if scenario == "seller":
        return _sanitize_filename_part(params.get("seller") or _first(params.get("sellers")))
    if scenario == "lightning-deals":
        return _sanitize_filename_part(params.get("asin"))
    return ""


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value


def _camel_case(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    return "".join(part.capitalize() for part in parts if part)


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


def _normalize_export_format(value: str) -> str:
    text = (value or "").strip().lower()
    if text in {"", "xls", "xlsx"}:
        return "xlsx"
    if text == "json":
        return "json"
    raise KeepaConfigError(f"不支持的导出格式：{value}")


def _resolve_export_format(
    *,
    requested_format: str,
    row_count: int,
    warnings: list[dict[str, Any]],
) -> str:
    if requested_format != "xlsx" or row_count <= MAX_XLSX_EXPORT_ROWS:
        return requested_format
    warnings.append(
        {
            "stage": "export_format_auto_json",
            "message": f"Keepa 返回 {row_count} 行，数据量较大，已自动改为 JSON 导出，避免 XLSX 文件过大或导出超时。",
            "row_count": row_count,
            "max_xlsx_rows": MAX_XLSX_EXPORT_ROWS,
        }
    )
    return "json"


def _export_raw_to_json(
    *,
    output_path: Path,
    job_id: str,
    scenario: str,
    site: str,
    endpoint: str,
    request_params: dict[str, Any],
    raw_response: dict[str, Any],
    rows: list[Any],
    warnings: list[dict[str, Any]],
    formatted_tables: dict[str, Any] | None = None,
) -> KeepaExportResult:
    payload = {
        "job_id": job_id,
        "scenario": scenario,
        "site": site,
        "endpoint": endpoint,
        "request_params": request_params,
        "row_count": len(rows),
        "rows": rows,
        "raw_response": raw_response,
        "quota": extract_quota(raw_response),
        "warnings": warnings,
    }
    if formatted_tables:
        payload["formatted_tables"] = formatted_tables
    _write_json(output_path, payload)
    resolved = output_path.resolve()
    return KeepaExportResult(
        path=str(resolved),
        filename=resolved.name,
        url=resolved.as_uri(),
        format="json",
        mime_type="application/json",
    )


def _upload_export_if_enabled(
    *,
    export: KeepaExportResult,
    job_id: str,
    scenario: str,
    site: str,
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
            purpose="keepa_export",
            folder="keepa/exports",
            public="1",
            metadata={
                "job_id": job_id,
                "scenario": scenario,
                "site": site,
                "filename": export.filename,
                "format": export.format,
                "mime_type": export.mime_type,
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
