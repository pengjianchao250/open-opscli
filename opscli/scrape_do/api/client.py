"""Scrape.do HTTP 客户端。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, quote, quote_plus, urlsplit, urlunsplit

import httpx

from opscli.scrape_do.config import SCRAPE_DO_BASE_URL, DEFAULT_TIMEOUT_SECONDS
from opscli.scrape_do.domain.exceptions import ScrapeDoApiError

_TOKEN_LOCKS: dict[str, asyncio.Lock] = {}
_TOKEN_LOCKS_GUARD = asyncio.Lock()


@dataclass(frozen=True)
class ScrapeDoApiResponse:
    """Scrape.do API 响应和计费头。"""

    payload: dict[str, Any]
    billing: dict[str, Any]
    safe_url: str


class ScrapeDoApiClient:
    """Scrape.do JSON API 客户端，按 token 串行化请求。"""

    def __init__(self, *, base_url: str = SCRAPE_DO_BASE_URL, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ScrapeDoApiClient":
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def get_json(self, endpoint: str, params: dict[str, Any]) -> ScrapeDoApiResponse:
        token = str(params.get("token") or "")
        lock = await _lock_for_token(token)
        async with lock:
            return await self._get_json(endpoint, params)

    async def _get_json(self, endpoint: str, params: dict[str, Any]) -> ScrapeDoApiResponse:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        close_after = self._client is None
        url = f"{self.base_url}{endpoint}"
        try:
            response = await client.get(url, params=params)
            safe_url = _redact_token(str(response.request.url))
            payload = _parse_json_response(response, safe_url=safe_url, params=params)
            if response.status_code >= 400:
                raise _api_error_from_payload(response.status_code, payload, safe_url=safe_url, params=params)
            if not isinstance(payload, dict):
                raise ScrapeDoApiError("Scrape.do API 响应不是 JSON 对象", status_code=response.status_code)
            _raise_business_error(payload, status_code=response.status_code, safe_url=safe_url, params=params)
            return ScrapeDoApiResponse(payload=payload, billing=_billing_from_headers(response.headers), safe_url=safe_url)
        except ScrapeDoApiError:
            raise
        except httpx.HTTPError as exc:
            request_url = getattr(getattr(exc, "request", None), "url", "")
            safe_excerpt = _sanitize_text(str(request_url), params)
            safe_detail = _sanitize_text(str(exc), params)
            raise ScrapeDoApiError(f"Scrape.do API 请求失败：{safe_detail}", response_excerpt=safe_excerpt) from None
        finally:
            if close_after:
                await client.aclose()


def _parse_json_response(response: httpx.Response, *, safe_url: str, params: dict[str, Any]) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ScrapeDoApiError(
            "Scrape.do API 响应不是合法 JSON",
            status_code=response.status_code,
            response_excerpt=_sanitize_text(response.text[:1000], params) or safe_url,
        ) from None


def _api_error_from_payload(
    status_code: int,
    payload: Any,
    *,
    safe_url: str,
    params: dict[str, Any],
) -> ScrapeDoApiError:
    if isinstance(payload, dict):
        error_code = str(payload.get("error") or payload.get("code") or "").strip() or None
        message = _sanitize_text(
            str(payload.get("message") or payload.get("errorMessage") or f"Scrape.do API 返回 HTTP {status_code}"),
            params,
        )
        excerpt = _sanitize_text(json.dumps(_strip_token_fields(payload), ensure_ascii=False), params)[:1000]
        return ScrapeDoApiError(message, status_code=status_code, error_code=error_code, response_excerpt=excerpt)
    return ScrapeDoApiError(f"Scrape.do API 返回 HTTP {status_code}", status_code=status_code, response_excerpt=safe_url)


def _raise_business_error(
    payload: dict[str, Any],
    *,
    status_code: int,
    safe_url: str,
    params: dict[str, Any],
) -> None:
    status = str(payload.get("status") or "").lower()
    if status == "error" or payload.get("error"):
        error_code = str(payload.get("error") or "").strip() or None
        message = _sanitize_text(
            str(payload.get("errorMessage") or payload.get("message") or "Scrape.do API 返回业务错误"),
            params,
        )
        excerpt = _sanitize_text(json.dumps(_strip_token_fields(payload), ensure_ascii=False), params)[:1000]
        raise ScrapeDoApiError(message, status_code=status_code, error_code=error_code, response_excerpt=excerpt or safe_url)


def _billing_from_headers(headers: httpx.Headers) -> dict[str, Any]:
    return {
        "request_cost": _optional_int(headers.get("Scrape.do-Request-Cost")),
        "remaining_credits": _optional_int(headers.get("Scrape.do-Remaining-Credits")),
    }


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def _lock_for_token(token: str) -> asyncio.Lock:
    key = token or "__missing__"
    async with _TOKEN_LOCKS_GUARD:
        lock = _TOKEN_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _TOKEN_LOCKS[key] = lock
        return lock


def _redact_token(url: str) -> str:
    if not url:
        return url
    parts = urlsplit(url)
    query_parts = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        encoded_key = quote_plus(key)
        encoded_value = "***" if key.lower() == "token" else quote_plus(value)
        query_parts.append(f"{encoded_key}={encoded_value}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query_parts), parts.fragment))


def _sanitize_text(text: str, params: dict[str, Any]) -> str:
    return _redact_secret_values(_redact_token(text), params)


def _redact_secret_values(text: str, params: dict[str, Any]) -> str:
    redacted = text
    for key, value in params.items():
        if str(key).replace("-", "_").lower() not in {"token", "api_key", "authorization"}:
            continue
        for secret in _secret_replacements(value):
            redacted = redacted.replace(secret, "***")
    return redacted


def _secret_replacements(value: Any) -> list[str]:
    secret = str(value or "")
    if not secret:
        return []
    return [secret, quote_plus(secret), quote(secret, safe="")]


def _strip_token_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_token_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if str(key).replace("-", "_").lower() in {"token", "api_key", "authorization"}:
            result[key] = "***"
        else:
            result[key] = _strip_token_fields(item)
    return result
