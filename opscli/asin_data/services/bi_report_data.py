"""Client for ASIN BI report data endpoints."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Mapping, Sequence

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.auth.config import load_config
from opscli.asin_data.services.report_files import _report_files_base_url
from opscli.config import __version__
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.exceptions import RemoteError
from opscli.shared.http import parse_remote_response


DEFAULT_TIMEOUT = 30

BI_REPORT_DATA_SOURCES: dict[str, dict[str, str]] = {
    "listing_basic": {
        "label": "刊登基础数据",
        "endpoint": "https://bi.api.xenkee.com/listing/amazonlisdet",
        "list_endpoint": "https://bi.api.xenkee.com/listing/getAmazonListing",
    },
    "sales_traffic": {
        "label": "销售/库存/广告/流量数据",
        "endpoint": "/dataMetrics/v1/asin-report-files/sales-traffic-data",
    },
    "sp_search_term": {
        "label": "SP广告搜索词数据",
        "endpoint": "/api/v1/sp-search-term/query",
    },
    "deals": {
        "label": "活动数据",
        "endpoint": "/dataMetrics/v1/asin-report-files/deals-data",
    },
    "turnover_inventory": {
        "label": "物控版库存数据",
        "endpoint": "/dataMetrics/v1/asin-report-files/turnover-inventory-data",
    },
    "crawler_details": {
        "label": "爬虫ASIN详情数据",
        "endpoint": "/dataMetrics/v1/asin-report-files/crawler-details",
    },
}

ROW_CONTAINER_KEYS = ("rows", "items", "records", "list", "data", "result", "results")
ASIN_KEYS = (
    "asin",
    "ASIN",
    "f_asin",
    "F_ASIN",
    "parent_asin",
    "parentAsin",
    "child_asin",
    "childAsin",
    "seller_asin",
    "sellerAsin",
    "amazon_asin",
    "amazonAsin",
    "asins",
    "ASINS",
    "ASINs",
    "asin_group",
    "asinGroup",
    "ASIN Group",
    "asin\u7ec4",
    "ASIN\u7ec4",
)


class AsinBiReportDataError(RemoteError):
    """ASIN BI report data endpoint error."""

    code = "ASIN_BI_REPORT_DATA_ERROR"


class AsinBiReportDataHttpError(AsinBiReportDataError):
    """HTTP error from ASIN BI report data endpoint."""

    code = "ASIN_BI_REPORT_DATA_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class AsinBiReportDataBusinessError(AsinBiReportDataError):
    """Business error from ASIN BI report data endpoint."""

    code = "ASIN_BI_REPORT_DATA_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class AsinBiReportDataBadJsonError(AsinBiReportDataError):
    """Invalid JSON returned by ASIN BI report data endpoint."""

    code = "ASIN_BI_REPORT_DATA_BAD_JSON"


class AsinBiReportDataClient:
    """Fetch BI data used by the ASIN merged report."""

    def __init__(
        self,
        *,
        auth_client: AuthClient | None = None,
        endpoints: Mapping[str, str] | None = None,
        http_get: Callable[..., httpx.Response] | None = None,
        ops_url: str | None = None,
    ) -> None:
        self.auth_client = auth_client or AuthClient()
        self.sources = _source_configs(endpoints)
        self.http_get = http_get or httpx.get
        self.ops_url = _report_files_base_url(ops_url or OPS_URL)
        self._listing_auth_cache: tuple[dict[str, str], dict[str, str]] | None = None

    def fetch(self, *, asins: Sequence[str]) -> dict[str, Any]:
        normalized_asins = normalize_asins(asins)
        if not normalized_asins:
            raise ValueError("asins must not be empty")

        try:
            headers, cookies = self.auth_client.build_request_auth("ops")
            headers.update(get_mcp_request_headers())
        except Exception as exc:
            sources = {
                key: _failed_source(key, config, exc)
                for key, config in self.sources.items()
            }
            return {
                "status": "failed",
                "asins": normalized_asins,
                "count": len(normalized_asins),
                "sources": sources,
            }

        sources = {
            key: self._fetch_source(
                key=key,
                config=config,
                asins=normalized_asins,
                headers=headers,
                cookies=cookies,
            )
            for key, config in self.sources.items()
        }
        return {
            "status": _aggregate_status(sources.values()),
            "asins": normalized_asins,
            "count": len(normalized_asins),
            "sources": sources,
        }

    def _fetch_source(
        self,
        *,
        key: str,
        config: dict[str, str],
        asins: list[str],
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> dict[str, Any]:
        endpoint = config["endpoint"]
        try:
            if key == "listing_basic":
                listing_headers, listing_cookies = self._build_listing_request_auth(
                    fallback_headers=headers,
                    fallback_cookies=cookies,
                )
                try:
                    return self._fetch_listing_basic_source(
                        key=key,
                        config=config,
                        asins=asins,
                        headers=listing_headers,
                        cookies=listing_cookies,
                    )
                except Exception as exc:
                    if "未登陆" not in str(exc):
                        raise
                    self._listing_auth_cache = None
                    listing_headers, listing_cookies = self._build_listing_request_auth(
                        fallback_headers=headers,
                        fallback_cookies=cookies,
                    )
                    return self._fetch_listing_basic_source(
                        key=key,
                        config=config,
                        asins=asins,
                        headers=listing_headers,
                        cookies=listing_cookies,
                    )
            if key == "sp_search_term":
                return self._fetch_sp_search_term_source(
                    key=key,
                    config=config,
                    asins=asins,
                    headers=headers,
                    cookies=cookies,
                )
            response = self.http_get(
                self._resolve_endpoint(endpoint),
                params={"asins": ",".join(asins)},
                headers=headers,
                cookies=cookies,
                timeout=DEFAULT_TIMEOUT,
            )
            payload = parse_remote_response(
                response,
                http_error_cls=AsinBiReportDataHttpError,
                business_error_cls=AsinBiReportDataBusinessError,
                bad_json_error_cls=AsinBiReportDataBadJsonError,
            )
            rows = extract_rows(payload.get("data") if isinstance(payload, dict) and "data" in payload else payload)
            return {
                "key": key,
                "label": config["label"],
                "endpoint": endpoint,
                "status": "success",
                "row_count": len(rows),
                "rows": rows,
                "raw": payload,
            }
        except Exception as exc:
            return _failed_source(key, config, exc)

    def _build_listing_request_auth(
        self,
        *,
        fallback_headers: dict[str, str],
        fallback_cookies: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        env_auth = os.environ.get("BI_AUTH", "").strip()
        env_cookie = os.environ.get("BI_COOKIE", "").strip()
        if env_auth:
            headers = {"Authorization": env_auth, "X-Opscli-Version": __version__}
            cookies = _parse_cookie_header(env_cookie)
            return _listing_browser_headers(headers), cookies
        if self._listing_auth_cache is not None:
            headers, cookies = self._listing_auth_cache
            return dict(headers), dict(cookies)
        try:
            headers, cookies = self.auth_client.build_request_auth("polaris")
            headers.update(get_mcp_request_headers())
            return self._cache_listing_auth(_listing_browser_headers(headers), cookies)
        except Exception:
            try:
                headers, cookies = self._build_direct_polaris_request_auth()
                return self._cache_listing_auth(_listing_browser_headers(headers), cookies)
            except Exception:
                pass
            return _listing_browser_headers(fallback_headers), fallback_cookies

    def _cache_listing_auth(
        self,
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        self._listing_auth_cache = (dict(headers), dict(cookies))
        return dict(headers), dict(cookies)

    def _build_direct_polaris_request_auth(self) -> tuple[dict[str, str], dict[str, str]]:
        session_id = self.auth_client.get_session("polaris")
        cfg = load_config()
        headers = {"X-Opscli-Version": __version__}
        headers.update(get_mcp_request_headers())
        response = httpx.post(
            f"{str(cfg['polaris_system_url']).rstrip('/')}{cfg['polaris_token_endpoint']}",
            json={"session_id": session_id},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        jwt = payload.get("jwt") if isinstance(payload, dict) else None
        if not jwt:
            raise AsinBiReportDataBusinessError("POLARIS_TOKEN_MISSING", "Polaris token response missing jwt")
        cookies = {"polarisUserToken": session_id}
        device_code = self.auth_client.get_device_code()
        if device_code:
            cookies["opscliDeviceCode"] = device_code
        return {"Authorization": f"Bearer {jwt}", "X-Opscli-Version": __version__}, cookies

    def _fetch_sp_search_term_source(
        self,
        *,
        key: str,
        config: dict[str, str],
        asins: list[str],
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> dict[str, Any]:
        """Fetch SP search term data via POST /api/v1/sp-search-term/query."""
        all_rows: list[dict[str, Any]] = []
        raw_items: list[Any] = []
        errors: list[str] = []
        for asin in asins:
            try:
                response = httpx.post(
                    self._resolve_endpoint(config["endpoint"]),
                    json={"asin": asin},
                    headers=headers,
                    cookies=cookies,
                    timeout=DEFAULT_TIMEOUT,
                )
                payload = parse_remote_response(
                    response,
                    http_error_cls=AsinBiReportDataHttpError,
                    business_error_cls=AsinBiReportDataBusinessError,
                    bad_json_error_cls=AsinBiReportDataBadJsonError,
                )
                raw_items.append(payload)
                rows = extract_rows(payload.get("data") if isinstance(payload, dict) and "data" in payload else payload)
                all_rows.extend(rows)
            except Exception as exc:
                errors.append(f"{asin}: {exc}")
        status = "success" if not errors else ("partial" if all_rows else "failed")
        result: dict[str, Any] = {
            "key": key,
            "label": config["label"],
            "endpoint": config["endpoint"],
            "status": status,
            "row_count": len(all_rows),
            "rows": all_rows,
            "raw": raw_items,
        }
        if errors:
            result["errors"] = errors
        return result

    def _fetch_listing_basic_source(
        self,
        *,
        key: str,
        config: dict[str, str],
        asins: list[str],
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        raw_items: list[dict[str, Any]] = []
        for asin in asins:
            payload = self._fetch_listing_basic_for_asin(
                asin=asin,
                config=config,
                headers=headers,
                cookies=cookies,
            )
            raw_items.append(payload)
            row = payload.get("row")
            if isinstance(row, dict):
                rows.append(row)
        return {
            "key": key,
            "label": config["label"],
            "endpoint": config["endpoint"],
            "list_endpoint": config.get("list_endpoint"),
            "status": "success",
            "row_count": len(rows),
            "rows": rows,
            "raw": raw_items,
        }

    def _fetch_listing_basic_for_asin(
        self,
        *,
        asin: str,
        config: dict[str, str],
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> dict[str, Any]:
        list_endpoint = config.get("list_endpoint") or "https://bi.api.xenkee.com/listing/getAmazonListing"
        list_response = self.http_get(
            self._resolve_endpoint(list_endpoint),
            params={
                "abnormal_state": 1,
                "asin": asin,
                "page": 1,
                "limit": 20,
                "view_type": "child",
                "account_type": 1,
                "_t": int(time.time()),
            },
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        list_payload = parse_remote_response(
            list_response,
            http_error_cls=AsinBiReportDataHttpError,
            business_error_cls=AsinBiReportDataBusinessError,
            bad_json_error_cls=AsinBiReportDataBadJsonError,
        )
        list_rows = extract_rows(list_payload.get("data") if isinstance(list_payload, dict) and "data" in list_payload else list_payload)
        selected_rows = select_listing_rows(list_rows, asin)
        if not selected_rows:
            raise AsinBiReportDataBusinessError("LISTING_NOT_FOUND", f"listing row not found for {asin}")
        first_payload: dict[str, Any] | None = None
        for selected in selected_rows:
            listid = _first_present(selected, "id", "listid", "list_id")
            if not listid:
                continue
            detail_payload = self._fetch_listing_detail_payload(
                config=config,
                listid=listid,
                headers=headers,
                cookies=cookies,
            )
            detail = detail_payload.get("data") if isinstance(detail_payload, dict) else None
            if not isinstance(detail, dict):
                continue
            payload = {
                "asin": asin,
                "listid": listid,
                "row": normalize_listing_basic(asin=asin, list_row=selected, detail=detail),
                "list_response": list_payload,
                "detail_response": detail_payload,
            }
            if first_payload is None:
                first_payload = payload
            if _has_value(detail.get("generic_keyword.value")):
                return payload
        if first_payload is not None:
            return first_payload
        raise AsinBiReportDataBusinessError("LISTING_ID_NOT_FOUND", f"listing id not found for {asin}")

    def _fetch_listing_detail_payload(
        self,
        *,
        config: dict[str, str],
        listid: Any,
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> dict[str, Any]:
        detail_response = self.http_get(
            self._resolve_endpoint(config["endpoint"]),
            params={"listid": listid, "_t": int(time.time())},
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        return parse_remote_response(
            detail_response,
            http_error_cls=AsinBiReportDataHttpError,
            business_error_cls=AsinBiReportDataBusinessError,
            bad_json_error_cls=AsinBiReportDataBadJsonError,
        )

    def _resolve_endpoint(self, endpoint: str) -> str:
        text = endpoint.strip()
        if text.startswith(("http://", "https://")):
            return text
        if not text.startswith("/"):
            text = f"/{text}"
        return f"{self.ops_url}{text}"


def build_bi_report_data_placeholder(
    *,
    asins: Sequence[str],
    status: str,
    reason: str,
) -> dict[str, Any]:
    normalized_asins = normalize_asins(asins)
    return {
        "status": status,
        "asins": normalized_asins,
        "count": len(normalized_asins),
        "reason": reason,
        "sources": {
            key: {
                "key": key,
                "label": config["label"],
                "endpoint": config["endpoint"],
                "status": status,
                "row_count": 0,
                "rows": [],
                "raw": None,
                "reason": reason,
            }
            for key, config in BI_REPORT_DATA_SOURCES.items()
        },
    }


def select_bi_report_data_for_asin(bundle: dict[str, Any], *, asin: str) -> dict[str, Any]:
    normalized_asin = normalize_asin(asin)
    per_asin = bundle.get("per_asin") if isinstance(bundle.get("per_asin"), dict) else {}
    asin_bundle = per_asin.get(normalized_asin)
    if isinstance(asin_bundle, dict):
        bundle = asin_bundle
    sources: dict[str, Any] = {}
    raw_sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    for key, source in raw_sources.items():
        if not isinstance(source, dict):
            continue
        rows = source.get("rows") if isinstance(source.get("rows"), list) else []
        selected_rows = rows_for_asin(rows, normalized_asin)
        selected = dict(source)
        selected["rows"] = selected_rows
        selected["row_count"] = len(selected_rows)
        selected["source_row_count"] = source.get("row_count", len(rows))
        sources[str(key)] = selected
    return {
        "status": bundle.get("status"),
        "asin": normalized_asin,
        "sources": sources,
    }


def summarize_bi_report_data(bundle: dict[str, Any]) -> dict[str, Any]:
    raw_sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    sources: dict[str, Any] = {}
    for key, source in raw_sources.items():
        if not isinstance(source, dict):
            continue
        sources[str(key)] = {
            "label": source.get("label"),
            "endpoint": source.get("endpoint"),
            "status": source.get("status"),
            "row_count": source.get("row_count"),
            "error_message": source.get("error_message"),
            "reason": source.get("reason"),
        }
    summary = {
        "status": bundle.get("status"),
        "asins": bundle.get("asins"),
        "count": bundle.get("count"),
        "reason": bundle.get("reason"),
        "sources": sources,
    }
    if bundle.get("request_mode"):
        summary["request_mode"] = bundle.get("request_mode")
    per_asin = bundle.get("per_asin") if isinstance(bundle.get("per_asin"), dict) else {}
    if per_asin:
        summary["per_asin"] = {
            str(asin): summarize_bi_report_data(asin_bundle)
            for asin, asin_bundle in per_asin.items()
            if isinstance(asin_bundle, dict)
        }
    return summary


def extract_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ROW_CONTAINER_KEYS:
        if key not in value:
            continue
        rows = extract_rows(value.get(key))
        if rows or isinstance(value.get(key), list):
            return rows
    return [value] if _looks_like_row(value) else []


def rows_for_asin(rows: Sequence[Any], asin: str) -> list[dict[str, Any]]:
    normalized_asin = normalize_asin(asin)
    matched: list[dict[str, Any]] = []
    saw_asin_field = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_asins = row_asin_values(row)
        if row_asins:
            saw_asin_field = True
            if normalized_asin in row_asins:
                matched.append(row)
    if matched or saw_asin_field:
        return matched
    return [row for row in rows if isinstance(row, dict)]


def select_listing_rows(rows: list[dict[str, Any]], asin: str) -> list[dict[str, Any]]:
    normalized = normalize_asin(asin)
    matched = [row for row in rows if normalize_asin(row.get("asin") or row.get("ASIN")) == normalized]
    candidates = matched or rows
    return sorted(candidates, key=_listing_row_priority)


def _listing_row_priority(row: dict[str, Any]) -> tuple[int, int]:
    status = str(row.get("amazon_status") or "").strip().lower()
    active_rank = 0 if status == "active" else 1
    deleted_rank = 1 if status in {"delete", "deleted", "inactive"} else 0
    return active_rank, deleted_rank


def normalize_listing_basic(*, asin: str, list_row: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    merged = {**list_row, **detail}
    other_images = [
        _first_present(merged, f"other_product_image_locator_{index}.media_location", f"other_image_url{index}")
        for index in range(1, 9)
    ]
    other_images = [str(item).strip() for item in other_images if str(item or "").strip()]
    bullets = [
        _first_present(merged, f"bullet_point.value{index}", f"bullet_point{index}")
        for index in range(1, 10)
    ]
    bullets = [str(item).strip() for item in bullets if str(item or "").strip()]
    row = {
        "asin": asin,
        "ASIN": asin,
        "渠道": _first_present(merged, "channel_name"),
        "平台SKU": _first_present(merged, "item_sku", "sell_sku"),
        "公司SKU": _first_present(merged, "sku"),
        "亚马逊状态": _first_present(merged, "amazon_status"),
        "发货方式": normalize_fulfillment(_first_present(merged, "fulfillment_availability.fulfillment_channel_code", "fulfillment_center_id"), _first_present(merged, "is_fba")),
        "类目": normalize_category(_first_present(merged, "path_name"), _first_present(merged, "feed_type_info")),
        "五点描述": bullets,
        "主图链接": _first_present(merged, "main_product_image_locator.media_location", "main_image_url"),
        "其他附图链接": other_images,
        "关键词搜索": _first_present(merged, "generic_keyword.value"),
        "generic_keyword.value": _first_present(merged, "generic_keyword.value"),
        "商品标题": _first_present(merged, "item_name.value", "item_name"),
        "品牌": _first_present(merged, "brand.value", "brand_name"),
        "站点": _first_present(merged, "country_iso_code", "country_site_code"),
        "店铺/部门": _first_present(merged, "site_name"),
        "负责人": _first_present(merged, "sales_team_user_name"),
        "listid": _first_present(merged, "listid", "id"),
    }
    return {key: value for key, value in row.items() if _has_value(value)}


def normalize_category(path_name: Any, feed_type_info: Any) -> str:
    if isinstance(path_name, list):
        return str(path_name[0]) if path_name else ""
    if isinstance(path_name, str) and path_name.strip():
        text = path_name.strip()
        if text.startswith("["):
            try:
                payload = json.loads(text)
            except Exception:
                return text
            if isinstance(payload, list) and payload:
                return str(payload[0])
        return text
    if isinstance(feed_type_info, str) and feed_type_info.strip():
        try:
            payload = json.loads(feed_type_info)
        except Exception:
            return ""
        value = payload.get("path_name") if isinstance(payload, dict) else None
        if isinstance(value, list) and value:
            return str(value[0])
    return ""


def normalize_fulfillment(value: Any, is_fba: Any) -> str:
    text = str(value or "").strip()
    if text:
        return text
    if str(is_fba) == "1":
        return "FBA"
    if str(is_fba) == "2":
        return "FBM"
    return ""


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if _has_value(value):
            return value
    return ""


def _has_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    return True


def row_asin_values(row: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ASIN_KEYS:
        if key not in row:
            continue
        values.update(_normalize_asin_values(row.get(key)))
    return values


def normalize_asins(asins: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for asin in asins:
        normalized = normalize_asin(asin)
        if not normalized or normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)
    return result


def normalize_asin(value: Any) -> str:
    return str(value or "").strip().upper()


def _source_configs(endpoints: Mapping[str, str] | None) -> dict[str, dict[str, str]]:
    configs = {key: dict(value) for key, value in BI_REPORT_DATA_SOURCES.items()}
    if endpoints:
        for key, endpoint in endpoints.items():
            if key in configs:
                configs[key]["endpoint"] = endpoint
    return configs


def _normalize_asin_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        values: set[str] = set()
        for item in value:
            values.update(_normalize_asin_values(item))
        return values
    text = str(value).strip()
    if not text:
        return set()
    return {part.strip().upper() for part in text.replace(";", ",").replace("|", ",").split(",") if part.strip()}


def _looks_like_row(value: dict[str, Any]) -> bool:
    if any(key in value for key in ASIN_KEYS):
        return True
    meta_keys = {"code", "msg", "message", "data", "total", "success"}
    if set(value).issubset(meta_keys):
        return False
    return any(not isinstance(item, (dict, list)) for item in value.values())


def _failed_source(key: str, config: dict[str, str], exc: Exception) -> dict[str, Any]:
    error = exc.to_dict() if hasattr(exc, "to_dict") else {"code": type(exc).__name__, "message": str(exc)}
    return {
        "key": key,
        "label": config["label"],
        "endpoint": config["endpoint"],
        "status": "failed",
        "row_count": 0,
        "rows": [],
        "raw": None,
        "error": error,
        "error_message": str(exc),
    }


def _listing_browser_headers(headers: dict[str, str]) -> dict[str, str]:
    result = dict(headers)
    result.setdefault("Accept", "application/json")
    result.setdefault("Accept-Language", "zh-CN,zh;q=0.9")
    result.setdefault("Origin", "https://bi.xenkee.com")
    result.setdefault("Referer", "https://bi.xenkee.com/")
    result.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    )
    return result


def _parse_cookie_header(value: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in value.split(";"):
        if "=" not in part:
            continue
        key, cookie_value = part.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = cookie_value.strip()
    return cookies


def _aggregate_status(sources: Any) -> str:
    statuses = [source.get("status") for source in sources if isinstance(source, dict)]
    if not statuses:
        return "skipped"
    if all(status == "success" for status in statuses):
        return "success"
    if any(status == "success" for status in statuses):
        return "partial"
    if all(status == "planned" for status in statuses):
        return "planned"
    if all(status == "skipped" for status in statuses):
        return "skipped"
    return "failed"
