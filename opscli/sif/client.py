"""Sif API 客户端。"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import httpx

from opscli.sif.config import SifSettings, load_settings
from opscli.sif.domain.exceptions import SifApiRequestError, SifDownloadError, SifLoginError, SifLoginRequiredError
from opscli.sif.domain.models import SifSalesApiResult


LISTING_HISTORY_PATH = "/api/search/bought/listingHistory"
GROUP_VARIANTS_PATH = "/api/search/bought/asin"
LISTING_HISTORY_DOWNLOAD_PATH = "/api/updown/boughtListingHistory/download"
BOUGHT_BY_ASIN_DOWNLOAD_PATH = "/api/updown/boughtByAsin/download"
LOGIN_PATH = "/api/user/login"


class SifApiClient:
    """封装 Sif 查销量相关接口。"""

    def __init__(self, *, settings: SifSettings | None = None, timeout: float = 60.0) -> None:
        self.settings = settings or load_settings()
        self.timeout = timeout
        self._token = self.settings.token
        self._request_marker = _build_request_marker()
        self._last_login_diagnostics: dict[str, Any] = {}

    def fetch_sales(
        self,
        *,
        asin: str,
        site: str,
        range_value: str | None = None,
        time_piece_type: str = "latelyDay",
        time_piece_value: str = "30",
        page_num: int = 1,
        page_size: int = 100,
        download_listing_history: bool = True,
        download_bought_by_asin: bool = True,
    ) -> SifSalesApiResult:
        """获取查销量接口数据与下载文件。"""
        params = self._build_params(asin=asin, site=site, range_value=range_value)
        search_payload = self._build_search_payload(asin=asin, range_value=range_value)
        listing_history_download_payload = {"asins": [asin.strip().upper()]}
        bought_by_asin_download_payload = self._build_bought_by_asin_payload(
            asin=asin,
            time_piece_type=time_piece_type,
            time_piece_value=time_piece_value,
            page_num=page_num,
            page_size=page_size,
        )
        with httpx.Client(timeout=self.timeout, headers=self._headers(), follow_redirects=True) as client:
            self._ensure_authenticated(client)
            listing_history = self._post_json(client, LISTING_HISTORY_PATH, payload=search_payload, country=params["country"])
            group_variants = self._post_json(client, GROUP_VARIANTS_PATH, payload=search_payload, country=params["country"])
            listing_history_xlsx = (
                self._download(
                    client,
                    LISTING_HISTORY_DOWNLOAD_PATH,
                    payload=listing_history_download_payload,
                    country=params["country"],
                )
                if download_listing_history
                else None
            )
            bought_by_asin_xlsx = (
                self._download(
                    client,
                    BOUGHT_BY_ASIN_DOWNLOAD_PATH,
                    payload=bought_by_asin_download_payload,
                    country=params["country"],
                )
                if download_bought_by_asin
                else None
            )
        return SifSalesApiResult(
            listing_history=listing_history,
            group_variants=group_variants,
            listing_history_xlsx=listing_history_xlsx,
            bought_by_asin_xlsx=bought_by_asin_xlsx,
        )

    def _headers(self) -> dict[str, str]:
        if not (self.settings.cookie or self._token):
            if not self._has_credentials():
                raise SifLoginRequiredError(
                    "未获取到 Sif 登录态。请设置 OPSCLI_SIF_USERNAME/OPSCLI_SIF_PASSWORD，"
                    "或传入 --sif-username/--sif-password 后重试。"
                )
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome Safari/537.36",
            **({"Cookie": self.settings.cookie} if self.settings.cookie else {}),
            **({"authorization": self._token} if self._token else {}),
        }

    def _ensure_authenticated(self, client: httpx.Client) -> None:
        if self._has_credentials():
            self._login(client)
            return
        if self.settings.cookie or self._token:
            return
        raise SifLoginRequiredError(
            "未获取到 Sif 登录态。请设置 OPSCLI_SIF_USERNAME/OPSCLI_SIF_PASSWORD，"
            "或传入 --sif-username/--sif-password 后重试。"
        )

    def _login(self, client: httpx.Client) -> None:
        if not self._has_credentials():
            raise SifLoginRequiredError(
                "未获取到 Sif 登录态。请设置 OPSCLI_SIF_USERNAME/OPSCLI_SIF_PASSWORD，"
                "或传入 --sif-username/--sif-password 后重试。"
            )
        response = client.post(
            self._absolute_url(LOGIN_PATH),
            json={"phone": self.settings.username, "password": self.settings.password},
        )
        self._last_login_diagnostics = self._build_login_diagnostics(response, client)
        if response.status_code >= 400:
            raise SifLoginError(
                "Sif 账号密码登录请求失败",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SifLoginError("Sif 登录接口返回非 JSON") from exc
        if not isinstance(payload, dict):
            raise SifLoginError("Sif 登录接口返回结构异常")
        code = payload.get("code")
        if code not in {0, "0", 1, "1", 200, "200", None}:
            message = payload.get("message") or payload.get("msg") or "Sif 登录失败"
            raise SifLoginError(str(message))
        if not client.cookies:
            raise SifLoginError("Sif 登录成功但未返回 Cookie")
        token = response.headers.get("authorization") or response.headers.get("Authorization")
        if token:
            self._token = token
            client.headers["authorization"] = token

    def _has_credentials(self) -> bool:
        return bool(self.settings.username and self.settings.password)

    def _build_login_diagnostics(self, response: httpx.Response, client: httpx.Client) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
                payload = {
                    "login_status": response.status_code,
                    "login_code": parsed.get("code"),
                    "login_message": parsed.get("message") or parsed.get("msg"),
                    "login_is_success": data.get("isSuccess") if isinstance(data, dict) else None,
                    "login_data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
                }
        except ValueError:
            payload = {"login_status": response.status_code, "login_non_json": True}
        payload.update(
            {
                "login_header_names": sorted(response.headers.keys()),
                "login_has_authorization": bool(response.headers.get("authorization") or response.headers.get("Authorization")),
                "login_cookie_names": self._cookie_names(client),
                "login_cookie_count": len(self._cookie_names(client)),
            }
        )
        return payload

    def _cookie_names(self, client: httpx.Client) -> list[str]:
        cookies = getattr(client, "cookies", None)
        jar = getattr(cookies, "jar", None)
        if jar is not None:
            return sorted([cookie.name for cookie in jar])
        if isinstance(cookies, dict):
            return sorted(cookies.keys())
        return []

    def _build_params(self, *, asin: str, site: str, range_value: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"asin": asin.strip().upper(), "site": site.strip().upper(), "country": site.strip().upper()}
        if range_value:
            params["range"] = range_value
        return params

    def _build_search_payload(self, *, asin: str, range_value: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pageSize": 5,
            "pageNum": 1,
            "asins": [asin.strip().upper()],
            "dimension": range_value or "asin",
        }
        return payload

    def _build_bought_by_asin_payload(
        self,
        *,
        asin: str,
        time_piece_type: str,
        time_piece_value: str,
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        return {
            "pageNum": page_num,
            "pageSize": page_size,
            "sortBy": "",
            "desc": True,
            "asins": [asin.strip().upper()],
            "timePieceType": time_piece_type,
            "timePieceValue": str(time_piece_value),
        }

    def _absolute_url(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}{path}"

    def _post_json(self, client: httpx.Client, path: str, *, payload: dict[str, Any], country: str | None = None) -> dict[str, Any]:
        request_payload = payload
        query = self._request_params({"country": country or request_payload.get("country") or "US"})
        response = client.post(self._absolute_url(path), json=request_payload, params=query)
        if response.status_code >= 400:
            raise SifApiRequestError(
                f"Sif API 请求失败：{path}",
                status_code=response.status_code,
                response_excerpt=response.text[:1000],
                request_payload=_public_request_payload(request_payload),
                request_query=_public_request_payload(query),
            )
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise SifApiRequestError(
                f"Sif API 返回非 JSON：{path}",
                status_code=response.status_code,
                response_excerpt=response.text[:1000],
                request_payload=_public_request_payload(request_payload),
                request_query=_public_request_payload(query),
            ) from exc
        normalized = response_payload if isinstance(response_payload, dict) else {"data": response_payload}
        self._raise_for_business_error(normalized, path=path, request_payload=request_payload, request_query=query)
        return normalized

    def _download(self, client: httpx.Client, path: str, *, payload: dict[str, Any], country: str | None = None) -> bytes:
        query = self._request_params({"country": country or payload.get("country") or "US"})
        response = client.post(self._absolute_url(path), json=payload, params=query)
        if response.status_code >= 400:
            raise SifApiRequestError(
                f"Sif 下载接口请求失败：{path}",
                status_code=response.status_code,
                response_excerpt=response.text[:1000],
                request_payload=_public_request_payload(payload),
                request_query=_public_request_payload(query),
            )
        content = response.content
        self._validate_xlsx_response(content, path=path)
        return content

    def download_post(self, path: str, *, payload: dict[str, Any], country: str | None = None) -> bytes:
        """Download an XLSX file through a POST Sif endpoint."""
        with httpx.Client(timeout=self.timeout, headers=self._headers(), follow_redirects=True) as client:
            self._ensure_authenticated(client)
            return self._download(client, path, payload=payload, country=country)

    def download_get(
        self,
        path: str,
        *,
        query: dict[str, Any],
        country: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        """Download an XLSX file through a GET Sif endpoint."""
        with httpx.Client(timeout=self.timeout, headers=self._headers(), follow_redirects=True) as client:
            self._ensure_authenticated(client)
            request_query = self._request_params({"country": country or query.get("country") or "US"})
            request_query.update(query)
            response = client.get(self._absolute_url(path), params=request_query, headers=headers or None)
            if response.status_code >= 400:
                raise SifApiRequestError(
                    f"Sif 下载接口请求失败：{path}",
                    status_code=response.status_code,
                    response_excerpt=response.text[:1000],
                    request_payload={},
                    request_query=_public_request_payload(request_query),
                )
            content = response.content
            self._validate_xlsx_response(content, path=path)
            return content

    def _raise_for_business_error(
        self,
        payload: dict[str, Any],
        *,
        path: str,
        request_payload: dict[str, Any] | None = None,
        request_query: dict[str, Any] | None = None,
    ) -> None:
        code = payload.get("code")
        if code in {-10, "-10"}:
            raise SifLoginRequiredError(f"Sif 登录态无效或已过期：{path}")
        if code not in {None, 0, "0", 1, "1", 200, "200"}:
            raise SifApiRequestError(
                f"Sif API 返回业务错误：{path}",
                response_excerpt=str(payload)[:1000],
                request_payload=_public_request_payload(request_payload or {}),
                request_query=_public_request_payload(request_query or {}),
            )

    def _validate_xlsx_response(self, content: bytes, *, path: str) -> None:
        if content.startswith(b"PK"):
            return
        text = content[:1000].decode("utf-8", errors="ignore").strip()
        if '"code"' in text or text.startswith("{"):
            if "UNAUTHORIZED" in text or '"code": -10' in text or '"code":-10' in text:
                raise SifLoginRequiredError(f"Sif 下载接口登录态无效或已过期：{path}")
            raise SifDownloadError(f"Sif 下载接口返回非 XLSX 内容：{text[:200]}")
        raise SifDownloadError(f"Sif 下载接口返回内容不是 XLSX：{path}")

    def _request_params(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = {"_t": int(time.time() * 1000), "_m": self._request_marker, "country": payload.get("country") or payload.get("site") or "US"}
        return params

    def login_diagnostics(self) -> dict[str, Any]:
        """返回不含敏感值的登录诊断信息。"""
        with httpx.Client(timeout=self.timeout, headers=self._headers(), follow_redirects=True) as client:
            self._ensure_authenticated(client)
            basic = client.get(self._absolute_url("/api/user/basic/info"), params=self._request_params({"site": "US"}))
            return {
                "client_module_file": __file__,
                "auth_input_mode": self._auth_input_mode(),
                "will_attempt_password_login": self._has_credentials(),
                "configured_has_cookie": bool(self.settings.cookie),
                "configured_has_token": bool(self.settings.token),
                "configured_has_username": bool(self.settings.username),
                "configured_has_password": bool(self.settings.password),
                **self._last_login_diagnostics,
                "has_cookie": bool(client.cookies),
                "cookie_names": self._cookie_names(client),
                "has_authorization": bool(self._token),
                "authorization_length": len(self._token or ""),
                "basic_info_status": basic.status_code,
                "basic_info_excerpt": basic.text[:300],
            }

    def _auth_input_mode(self) -> str:
        if self._has_credentials():
            return "credentials"
        if self.settings.token:
            return "token"
        if self.settings.cookie:
            return "cookie"
        return "missing"


def _public_request_payload(payload: dict[str, Any]) -> dict[str, object]:
    return {
        str(key): value
        for key, value in payload.items()
        if str(key).lower() not in {"password", "cookie", "authorization", "token"}
    }


def _build_request_marker() -> str:
    return f"Sif_{uuid4()}-{int(time.time() * 1000)}"
