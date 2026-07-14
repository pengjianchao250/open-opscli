"""Client for ASIN BI report data endpoints."""

from __future__ import annotations

import json
import os
import time
import configparser
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from typing import Any, Callable, Mapping, Sequence

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.auth.config import load_config
from opscli.asin_data.services.report_files import _report_files_base_url
from opscli.config import CONFIG_DIR, __version__
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.exceptions import RemoteError
from opscli.shared.http import parse_remote_response


DEFAULT_TIMEOUT = 30
DEFAULT_BI_LOGIN_ENDPOINT = "https://bi.api.xenkee.com/auth/login"
DEFAULT_POLARIS_BJX_TOKEN_ENDPOINT = "/dataMetrics/v1/asin-report-files/polaris-bjx-token"
DEFAULT_BI_LOGIN_USERNAME = "wanglintao@aukeys.com"
DEFAULT_BI_LOGIN_PASSWORD = "wlt123456"
BI_LOGIN_CONFIG_SECTION = "bi_login"
LISTING_AUTH_MODE_ENV = "OPSCLI_ASIN_DATA_LISTING_AUTH_MODE"
LISTING_AUTH_MODE_ALIASES = {
    "": "user",
    "current_user": "user",
    "personal": "user",
    "remote": "managed",
    "remote_token": "managed",
    "bjx": "managed",
    "login": "bi_login",
}
LISTING_AUTH_MODES = {"user", "managed", "bi_login"}
LISTING_AUTH_EXPIRED_MARKERS = ("未登陆", "未登录")

BI_REPORT_DATA_SOURCES: dict[str, dict[str, str]] = {
    "listing_basic": {
        "label": "刊登基础数据",
        "endpoint": "https://bi.api.xenkee.com/listing/amazonlisdet",
        "list_endpoint": "https://bi.api.xenkee.com/listing/getAmazonListing",
        "template_endpoint": "https://bi.api.xenkee.com/amazon/feed/getTemplate",
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
LISTING_REPORT_SOURCE_KEYS = ("listing_basic",)
BASIC_REPORT_SOURCE_KEYS = ("listing_basic", "crawler_details")
BI_ONLY_REPORT_SOURCE_KEYS = tuple(
    key for key in BI_REPORT_DATA_SOURCES if key not in BASIC_REPORT_SOURCE_KEYS
)
SITE_CODE_ALIASES: dict[str, str] = {
    "US": "US",
    "USA": "US",
    "美国": "US",
    "美国站": "US",
    "美区": "US",
    "UK": "UK",
    "GB": "UK",
    "英国": "UK",
    "英国站": "UK",
    "CA": "CA",
    "加拿大": "CA",
    "加拿大站": "CA",
    "DE": "DE",
    "德国": "DE",
    "德国站": "DE",
    "FR": "FR",
    "法国": "FR",
    "法国站": "FR",
    "IT": "IT",
    "意大利": "IT",
    "意大利站": "IT",
    "ES": "ES",
    "西班牙": "ES",
    "西班牙站": "ES",
    "JP": "JP",
    "日本": "JP",
    "日本站": "JP",
    "AU": "AU",
    "澳大利亚": "AU",
    "澳大利亚站": "AU",
    "澳洲": "AU",
    "MX": "MX",
    "墨西哥": "MX",
    "墨西哥站": "MX",
    "BR": "BR",
    "巴西": "BR",
    "巴西站": "BR",
    "AE": "AE",
    "阿联酋": "AE",
    "阿联酋站": "AE",
    "SA": "SA",
    "沙特": "SA",
    "沙特站": "SA",
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
        http_post: Callable[..., httpx.Response] | None = None,
        ops_url: str | None = None,
    ) -> None:
        self.auth_client = auth_client or AuthClient()
        self.sources = _source_configs(endpoints)
        self.http_get = http_get or httpx.get
        self.http_post = http_post or httpx.post
        self.ops_url = _report_files_base_url(ops_url or OPS_URL)
        self._listing_auth_cache: tuple[dict[str, str], dict[str, str]] | None = None

    def fetch(
        self,
        *,
        asins: Sequence[str],
        start_date: str | None = None,
        end_date: str | None = None,
        source_keys: Sequence[str] | None = None,
        site_by_asin: Mapping[str, str] | None = None,
        listing_account_type_by_asin: Mapping[str, int] | None = None,
        default_site: str = "US",
    ) -> dict[str, Any]:
        normalized_asins = normalize_asins(asins)
        if not normalized_asins:
            raise ValueError("asins must not be empty")
        source_configs = _filter_source_configs(self.sources, source_keys)
        normalized_site_by_asin = _normalize_site_by_asin(site_by_asin)
        normalized_listing_account_type_by_asin = _normalize_listing_account_type_by_asin(
            listing_account_type_by_asin
        )
        normalized_default_site = _normalize_site_code(default_site)

        headers: dict[str, str] = {}
        cookies: dict[str, str] = {}
        ops_auth_error: Exception | None = None
        needs_ops_auth = any(key not in LISTING_REPORT_SOURCE_KEYS for key in source_configs)
        if needs_ops_auth:
            try:
                headers, cookies = self.auth_client.build_request_auth("ops")
                headers.update(get_mcp_request_headers())
            except Exception as exc:
                ops_auth_error = exc

        source_items = list(source_configs.items())

        def fetch_one(key: str, config: dict[str, str]) -> dict[str, Any]:
            return (
                _failed_source(key, config, ops_auth_error)
                if ops_auth_error is not None and key not in LISTING_REPORT_SOURCE_KEYS
                else self._fetch_source(
                    key=key,
                    config=config,
                    asins=normalized_asins,
                    start_date=start_date,
                    end_date=end_date,
                    headers=headers,
                    cookies=cookies,
                    site_by_asin=normalized_site_by_asin,
                    listing_account_type_by_asin=normalized_listing_account_type_by_asin,
                    default_site=normalized_default_site,
                )
            )

        if _can_parallel_fetch_sources(source_configs):
            with ThreadPoolExecutor(max_workers=min(4, len(source_items))) as executor:
                futures = {
                    key: executor.submit(fetch_one, key, config)
                    for key, config in source_items
                }
                sources = {key: futures[key].result() for key, _config in source_items}
        else:
            sources = {key: fetch_one(key, config) for key, config in source_items}
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
        start_date: str | None,
        end_date: str | None,
        headers: dict[str, str],
        cookies: dict[str, str],
        site_by_asin: Mapping[str, str],
        listing_account_type_by_asin: Mapping[str, int],
        default_site: str,
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
                        site_by_asin=site_by_asin,
                        listing_account_type_by_asin=listing_account_type_by_asin,
                        default_site=default_site,
                    )
                except Exception as exc:
                    if not _is_listing_auth_expired(exc):
                        raise
                    self._listing_auth_cache = None
                    listing_headers, listing_cookies = self._build_listing_request_auth(
                        fallback_headers=headers,
                        fallback_cookies=cookies,
                        refresh_auth=True,
                    )
                    return self._fetch_listing_basic_source(
                        key=key,
                        config=config,
                        asins=asins,
                        headers=listing_headers,
                        cookies=listing_cookies,
                        site_by_asin=site_by_asin,
                        listing_account_type_by_asin=listing_account_type_by_asin,
                        default_site=default_site,
                    )
            if key == "sp_search_term":
                return self._fetch_sp_search_term_source(
                    key=key,
                    config=config,
                    asins=asins,
                    start_date=start_date,
                    end_date=end_date,
                    headers=headers,
                    cookies=cookies,
                )
            params = {"asins": ",".join(asins)}
            params.update(_date_range_params(start_date=start_date, end_date=end_date))
            response = self.http_get(
                self._resolve_endpoint(endpoint),
                params=params,
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
        refresh_auth: bool = False,
    ) -> tuple[dict[str, str], dict[str, str]]:
        if self._listing_auth_cache is not None and not refresh_auth:
            headers, cookies = self._listing_auth_cache
            return dict(headers), dict(cookies)
        mode = _listing_auth_mode()
        if mode == "bi_login":
            auth = self._build_bi_login_request_auth(use_default_account=True)
            if auth is None:
                raise AsinBiReportDataBusinessError("BI_LOGIN_AUTH_MISSING", "BI login credentials are missing")
            headers, cookies = auth
            return self._cache_listing_auth(_listing_browser_headers(headers), cookies)

        if mode == "managed":
            auth = self._build_remote_polaris_bjx_request_auth()
            if auth is not None:
                headers, cookies = auth
                return self._cache_listing_auth(_listing_browser_headers(headers), cookies)

        try:
            headers, cookies = self._build_user_polaris_request_auth(refresh=refresh_auth)
            return self._cache_listing_auth(_listing_browser_headers(headers), cookies)
        except Exception as exc:
            try:
                headers, cookies = self._build_direct_polaris_request_auth()
                return self._cache_listing_auth(_listing_browser_headers(headers), cookies)
            except Exception as direct_exc:
                raise AsinBiReportDataBusinessError(
                    "POLARIS_USER_AUTH_MISSING",
                    f"Polaris user auth is missing or invalid: {exc}; direct token exchange failed: {direct_exc}",
                ) from direct_exc

    def _build_user_polaris_request_auth(self, *, refresh: bool = False) -> tuple[dict[str, str], dict[str, str]]:
        """使用当前 opscli 登录用户的北极星 token 构造刊登接口鉴权。"""
        if refresh:
            self.auth_client.refresh_token("polaris")
        headers, cookies = self.auth_client.build_request_auth("polaris")
        headers.update(get_mcp_request_headers())
        return headers, cookies

    def _build_remote_polaris_bjx_request_auth(self) -> tuple[dict[str, str], dict[str, str]] | None:
        """从 ops 取数服务获取托管的北极星 token，并转换为刊登接口鉴权。"""
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = self.http_get(
            self._resolve_endpoint(DEFAULT_POLARIS_BJX_TOKEN_ENDPOINT),
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
        token = _extract_polaris_bjx_token(payload)
        if not token:
            raise AsinBiReportDataBusinessError(
                "POLARIS_BJX_TOKEN_MISSING",
                "polaris-bjx-token response missing polaris_bjx_token",
            )
        return {"Authorization": _authorization_value(token), "X-Opscli-Version": __version__}, {}

    def _build_bi_login_request_auth(
        self,
        *,
        use_default_account: bool = False,
    ) -> tuple[dict[str, str], dict[str, str]] | None:
        """通过本地配置中的 BI 账号密码登录，并返回刊登接口鉴权信息。"""
        login_config = _load_bi_login_config()
        username = _bi_login_setting("BI_LOGIN_USERNAME", "username", login_config)
        password = _bi_login_setting("BI_LOGIN_PASSWORD", "password", login_config)
        if use_default_account:
            username = username or DEFAULT_BI_LOGIN_USERNAME
            password = password or DEFAULT_BI_LOGIN_PASSWORD
        if not username or not password:
            return None

        endpoint = _bi_login_setting("BI_LOGIN_ENDPOINT", "endpoint", login_config) or DEFAULT_BI_LOGIN_ENDPOINT
        cookies = _parse_cookie_header(_bi_login_setting("BI_LOGIN_COOKIE", "cookie", login_config))
        headers = _listing_browser_headers(
            {
                "Content-Type": "application/json;charset=UTF-8",
                "X-Opscli-Version": __version__,
            }
        )
        response = self.http_post(
            endpoint,
            json={"username": username, "password": password, "_t": int(time.time())},
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
        token = _extract_auth_token(payload)
        response_cookies = _response_cookies(response)
        merged_cookies = {**cookies, **response_cookies}
        auth_headers = {"X-Opscli-Version": __version__}
        if token:
            auth_headers["Authorization"] = _authorization_value(token)
        if not token and not merged_cookies:
            raise AsinBiReportDataBusinessError("BI_LOGIN_AUTH_MISSING", "BI login response missing token or cookies")
        return auth_headers, merged_cookies

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
        response = self.http_post(
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
        start_date: str | None,
        end_date: str | None,
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> dict[str, Any]:
        """Fetch SP search term data via POST /api/v1/sp-search-term/query."""
        all_rows: list[dict[str, Any]] = []
        raw_items: list[Any] = []
        errors: list[str] = []

        def fetch_one(asin: str) -> tuple[Any | None, list[dict[str, Any]], str | None]:
            try:
                body = {"asin": asin}
                body.update(_date_range_params(start_date=start_date, end_date=end_date))
                response = self.http_post(
                    self._resolve_endpoint(config["endpoint"]),
                    json=body,
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
                return payload, rows, None
            except Exception as exc:
                return None, [], f"{asin}: {exc}"

        if len(asins) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(asins))) as executor:
                futures = [executor.submit(fetch_one, asin) for asin in asins]
                results = [future.result() for future in futures]
        else:
            results = [fetch_one(asin) for asin in asins]

        for payload, rows, error in results:
            if payload is not None:
                raw_items.append(payload)
            all_rows.extend(rows)
            if error:
                errors.append(error)
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
        site_by_asin: Mapping[str, str],
        listing_account_type_by_asin: Mapping[str, int],
        default_site: str,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        raw_items: list[dict[str, Any]] = []

        def fetch_one(asin: str) -> dict[str, Any]:
            try:
                return self._fetch_listing_basic_for_asin(
                    asin=asin,
                    site_code=_site_code_for_asin(asin, site_by_asin=site_by_asin, default_site=default_site),
                    account_type=_listing_account_type_for_asin(asin, listing_account_type_by_asin),
                    config=config,
                    headers=headers,
                    cookies=cookies,
                )
            except Exception as exc:
                if _is_listing_auth_expired(exc):
                    raise
                return {
                    "asin": asin,
                    "status": "not_found" if _is_listing_not_found(exc) else "failed",
                    "row": None,
                    "error": _error_dict(exc),
                    "error_message": str(exc),
                }

        if len(asins) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(asins))) as executor:
                futures = [executor.submit(fetch_one, asin) for asin in asins]
                payloads = [future.result() for future in futures]
        else:
            payloads = [fetch_one(asin) for asin in asins]

        for payload in payloads:
            raw_items.append(payload)
            row = payload.get("row")
            if isinstance(row, dict):
                rows.append(row)
        errors = [
            f"{payload.get('asin')}: {payload.get('error_message')}"
            for payload in payloads
            if payload.get("error_message")
        ]
        return {
            "key": key,
            "label": config["label"],
            "endpoint": config["endpoint"],
            "list_endpoint": config.get("list_endpoint"),
            "status": "success" if not errors else "partial",
            "row_count": len(rows),
            "rows": rows,
            "raw": raw_items,
            **({"errors": errors} if errors else {}),
        }

    def _fetch_listing_basic_for_asin(
        self,
        *,
        asin: str,
        site_code: str,
        account_type: int,
        config: dict[str, str],
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> dict[str, Any]:
        list_endpoint = config.get("list_endpoint") or "https://bi.api.xenkee.com/listing/getAmazonListing"
        list_params = {
            "abnormal_state": 1,
            "asin": asin,
            "page": 1,
            "limit": 20,
            "view_type": "child",
            "account_type": account_type,
            "_t": int(time.time()),
        }
        if _has_value(site_code):
            list_params["site_code"] = site_code
        list_response = self.http_get(
            self._resolve_endpoint(list_endpoint),
            params=list_params,
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
            template_payload: dict[str, Any] = {}
            template_error = ""
            if _listing_template_params(list_row=selected, detail=detail, listid=listid):
                try:
                    template_payload = self._fetch_listing_template_payload(
                        config=config,
                        list_row=selected,
                        detail=detail,
                        listid=listid,
                        headers=headers,
                        cookies=cookies,
                    )
                except Exception as exc:
                    template_error = str(exc)
            payload = {
                "asin": asin,
                "listid": listid,
                "row": normalize_listing_basic(
                    asin=asin,
                    list_row=selected,
                    detail=detail,
                    template=template_payload,
                ),
                "list_response": list_payload,
                "detail_response": detail_payload,
            }
            if template_payload:
                payload["template_response"] = template_payload
            if template_error:
                payload["template_error"] = template_error
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

    def _fetch_listing_template_payload(
        self,
        *,
        config: dict[str, str],
        list_row: dict[str, Any],
        detail: dict[str, Any],
        listid: Any,
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> dict[str, Any]:
        params = _listing_template_params(list_row=list_row, detail=detail, listid=listid)
        if not params:
            return {}
        template_endpoint = config.get("template_endpoint") or "https://bi.api.xenkee.com/amazon/feed/getTemplate"
        response = self.http_get(
            self._resolve_endpoint(template_endpoint),
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        return parse_remote_response(
            response,
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
    source_keys: Sequence[str] | None = None,
) -> dict[str, Any]:
    normalized_asins = normalize_asins(asins)
    source_configs = _filter_source_configs(BI_REPORT_DATA_SOURCES, source_keys)
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
            for key, config in source_configs.items()
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


def normalize_listing_basic(
    *,
    asin: str,
    list_row: dict[str, Any],
    detail: dict[str, Any],
    template: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "商品亮点": _first_present(
            merged,
            "title_differentiation.value",
            "title_differentiation",
        ),
        "品牌": _first_present(merged, "brand.value", "brand_name"),
        "站点": _first_present(merged, "country_iso_code", "country_site_code"),
        "店铺/部门": _first_present(merged, "site_name"),
        "负责人": _first_present(merged, "sales_team_user_name"),
        "listid": _first_present(merged, "listid", "id"),
    }
    for key, value in listing_template_alias_values(merged, template or {}).items():
        if key not in row or not _has_value(row.get(key)):
            row[key] = value
    return {key: value for key, value in row.items() if _has_value(value)}


def listing_template_alias_values(values: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """按刊登模板里的中文 alias，把 amazonlisdet 字段值转换成中文字段。"""
    result: dict[str, Any] = {}
    for item in iter_template_fields(template):
        field = str(item.get("field") or "").strip()
        alias = str(item.get("alias") or "").strip()
        if not field or not alias:
            continue
        value = values.get(field)
        if _has_value(value) and alias not in result:
            result[alias] = value
    return result


def iter_template_fields(value: Any) -> list[dict[str, Any]]:
    """递归提取 getTemplate 响应中的 field/alias 字段定义。"""
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("field"), str) and isinstance(value.get("alias"), str):
            rows.append(value)
        for child in value.values():
            rows.extend(iter_template_fields(child))
    elif isinstance(value, list):
        for item in value:
            rows.extend(iter_template_fields(item))
    return rows


def _listing_template_params(*, list_row: dict[str, Any], detail: dict[str, Any], listid: Any) -> dict[str, Any]:
    """从 amazonlisdet 和列表行中构造 getTemplate 查询参数。"""
    merged = {**list_row, **detail}
    feed_info = _json_object(_first_present(merged, "feed_type_info"))
    params = {
        "feed_product_type": _first_present(merged, "feed_product_type") or feed_info.get("feed_product_type"),
        "feed_product_type_id": _first_present(merged, "feed_product_type_id") or feed_info.get("feed_product_type_id"),
        "item_type": _first_present(merged, "item_type") or feed_info.get("item_type"),
        "channel_id": _first_present(merged, "channel_id"),
        "source_type": 1,
        "listid": listid,
        "task_id": "",
        "_t": int(time.time()),
    }
    required_keys = ("feed_product_type", "feed_product_type_id", "item_type", "channel_id", "listid")
    if not all(_has_value(params.get(key)) for key in required_keys):
        return {}
    return params


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _normalize_site_code(value: Any) -> str:
    text = str(value or "US").strip()
    return SITE_CODE_ALIASES.get(text) or SITE_CODE_ALIASES.get(text.upper()) or text.upper()


def _normalize_site_by_asin(site_by_asin: Mapping[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for asin, site in (site_by_asin or {}).items():
        normalized_asin = normalize_asin(asin)
        normalized_site = _normalize_site_code(site)
        if normalized_asin and normalized_site:
            result[normalized_asin] = normalized_site
    return result


def _normalize_listing_account_type_by_asin(account_type_by_asin: Mapping[str, int] | None) -> dict[str, int]:
    result: dict[str, int] = {}
    for asin, account_type in (account_type_by_asin or {}).items():
        normalized_asin = normalize_asin(asin)
        try:
            normalized_account_type = int(account_type)
        except (TypeError, ValueError):
            continue
        if normalized_asin and normalized_account_type > 0:
            result[normalized_asin] = normalized_account_type
    return result


def _site_code_for_asin(asin: str, *, site_by_asin: Mapping[str, str], default_site: str) -> str:
    return site_by_asin.get(normalize_asin(asin)) or _normalize_site_code(default_site)


def _listing_account_type_for_asin(asin: str, account_type_by_asin: Mapping[str, int]) -> int:
    return account_type_by_asin.get(normalize_asin(asin), 1)


def _date_range_params(*, start_date: str | None, end_date: str | None) -> dict[str, str]:
    """构造后端 ASIN BI 接口支持的日期范围参数。"""
    if not start_date or not end_date:
        return {}
    return {"start_date": start_date, "end_date": end_date}


def _source_configs(endpoints: Mapping[str, str] | None) -> dict[str, dict[str, str]]:
    configs = {key: dict(value) for key, value in BI_REPORT_DATA_SOURCES.items()}
    if endpoints:
        for key, endpoint in endpoints.items():
            if key in configs:
                configs[key]["endpoint"] = endpoint
    return configs


def _load_bi_login_config() -> dict[str, str]:
    """读取本机 BI 登录配置，避免把服务账号写进代码仓库。"""
    config_path = CONFIG_DIR / "config.ini"
    if not config_path.exists():
        return {}
    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    if not parser.has_section(BI_LOGIN_CONFIG_SECTION):
        return {}
    return {
        key: str(value).strip()
        for key, value in parser.items(BI_LOGIN_CONFIG_SECTION)
        if str(value).strip()
    }


def _bi_login_setting(env_name: str, config_name: str, login_config: Mapping[str, str]) -> str:
    """按环境变量优先、本地配置兜底的顺序读取 BI 登录参数。"""
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        return env_value
    return str(login_config.get(config_name) or "").strip()


def _listing_auth_mode() -> str:
    """读取刊登接口鉴权模式，默认使用当前登录用户的北极星权限。"""
    raw_mode = os.environ.get(LISTING_AUTH_MODE_ENV, "user").strip().lower()
    mode = LISTING_AUTH_MODE_ALIASES.get(raw_mode, raw_mode)
    if mode not in LISTING_AUTH_MODES:
        raise AsinBiReportDataBusinessError(
            "LISTING_AUTH_MODE_INVALID",
            f"{LISTING_AUTH_MODE_ENV} must be one of: {', '.join(sorted(LISTING_AUTH_MODES))}",
        )
    return mode


def _filter_source_configs(
    configs: Mapping[str, dict[str, str]],
    source_keys: Sequence[str] | None,
) -> dict[str, dict[str, str]]:
    """按调用方指定的数据源 key 过滤配置。"""
    if source_keys is None:
        return {key: dict(value) for key, value in configs.items()}
    normalized = [str(key).strip() for key in source_keys if str(key).strip()]
    unknown = [key for key in normalized if key not in configs]
    if unknown:
        raise ValueError(f"Unknown BI report data source keys: {', '.join(unknown)}")
    return {key: dict(configs[key]) for key in normalized}


def _can_parallel_fetch_sources(source_configs: Mapping[str, dict[str, str]]) -> bool:
    """判断当前 source 组合是否适合并发请求。"""
    return len(source_configs) > 1 and not any(key in LISTING_REPORT_SOURCE_KEYS for key in source_configs)


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


def _extract_auth_token(payload: Any) -> str:
    """从 BI 登录响应中递归提取常见 token 字段。"""
    token_keys = {
        "token",
        "access_token",
        "accessToken",
        "jwt",
        "id_token",
        "idToken",
        "authorization",
        "Authorization",
        "bearer_token",
        "bearerToken",
    }
    if isinstance(payload, dict):
        for key in token_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            token = _extract_auth_token(value)
            if token:
                return token
    if isinstance(payload, list):
        for item in payload:
            token = _extract_auth_token(item)
            if token:
                return token
    return ""


def _extract_polaris_bjx_token(payload: Any) -> str:
    """从取数服务响应中提取托管的北极星刊登 token。"""
    if isinstance(payload, dict):
        value = payload.get("polaris_bjx_token")
        if isinstance(value, str) and value.strip():
            return value.strip()
        for child in payload.values():
            token = _extract_polaris_bjx_token(child)
            if token:
                return token
    if isinstance(payload, list):
        for item in payload:
            token = _extract_polaris_bjx_token(item)
            if token:
                return token
    return ""


def _authorization_value(token: str) -> str:
    """统一补齐 Authorization 头，兼容后端直接返回 Bearer 字符串。"""
    text = token.strip()
    if text.lower().startswith(("bearer ", "basic ")):
        return text
    return f"Bearer {text}"


def _is_listing_auth_expired(exc: Exception) -> bool:
    """判断刊登接口错误是否属于登录态失效，需要改用账号密码重新登录。"""
    message = str(exc)
    return any(marker in message for marker in LISTING_AUTH_EXPIRED_MARKERS)


def _is_listing_not_found(exc: Exception) -> bool:
    """判断单个 ASIN 是否仅是未命中刊登记录，这类错误不应中断整个批量。"""
    code = str(getattr(exc, "business_code", "") or "").upper()
    return code in {"LISTING_NOT_FOUND", "LISTING_ID_NOT_FOUND"}


def _error_dict(exc: Exception) -> dict[str, Any]:
    """把异常转换成可序列化的错误字典。"""
    if hasattr(exc, "to_dict"):
        return exc.to_dict()  # type: ignore[no-any-return, call-arg]
    return {"code": type(exc).__name__, "message": str(exc)}


def _failed_source(key: str, config: dict[str, str], exc: Exception) -> dict[str, Any]:
    error = _error_dict(exc)
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


def _response_cookies(response: httpx.Response) -> dict[str, str]:
    """从 HTTP 响应中提取 cookie，兼容测试中未绑定 request 的 Response。"""
    try:
        return {key: value for key, value in response.cookies.items()}
    except RuntimeError:
        parsed = SimpleCookie()
        for value in response.headers.get_list("set-cookie"):
            parsed.load(value)
        return {key: morsel.value for key, morsel in parsed.items()}


def _aggregate_status(sources: Any) -> str:
    statuses = [source.get("status") for source in sources if isinstance(source, dict)]
    if not statuses:
        return "skipped"
    if all(status == "success" for status in statuses):
        return "success"
    if any(status in {"success", "partial"} for status in statuses):
        return "partial"
    if all(status == "planned" for status in statuses):
        return "planned"
    if all(status == "skipped" for status in statuses):
        return "skipped"
    return "failed"
