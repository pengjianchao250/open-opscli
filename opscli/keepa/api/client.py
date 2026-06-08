"""Keepa REST API 轻量客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from opscli.keepa.domain.exceptions import KeepaApiError


DEFAULT_BASE_URL = "https://api.keepa.com"
DEFAULT_USER_AGENT = "opscli-keepa/1.0"


class KeepaApiClient:
    """使用 API Key 调用 Keepa REST API。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    async def __aenter__(self) -> "KeepaApiClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层 HTTP client。"""
        await self._client.aclose()

    async def token_status(self) -> dict[str, Any]:
        """读取 Keepa API token 状态。"""
        return await self.get_json("token", {})

    async def get_json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET JSON 并返回 Keepa 原始响应。"""
        clean_params = _clean_params({"key": self.api_key, **params})
        response = await self._client.get(f"{self.base_url}/{endpoint.lstrip('/')}", params=clean_params)
        return _parse_json_response(response)


def _clean_params(params: dict[str, Any]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            clean[key] = "1" if value else "0"
        else:
            text = str(value)
            if text != "":
                clean[key] = text
    return clean


def _parse_json_response(response: httpx.Response) -> dict[str, Any]:
    text = response.text
    try:
        payload = response.json()
    except Exception as exc:
        raise KeepaApiError(
            "Keepa API 返回非 JSON",
            status_code=response.status_code,
            response_excerpt=text[:1000],
        ) from exc

    if not isinstance(payload, dict):
        raise KeepaApiError(
            "Keepa API 返回结构不是 JSON 对象",
            status_code=response.status_code,
            response_excerpt=text[:1000],
        )

    if response.status_code >= 400:
        message = _extract_error_message(payload) or f"Keepa API 请求失败，HTTP {response.status_code}"
        raise KeepaApiError(
            message,
            status_code=response.status_code,
            response_excerpt=text[:1000],
            response_payload=payload,
        )

    if payload.get("error"):
        raise KeepaApiError(
            str(payload.get("error")),
            status_code=response.status_code,
            response_excerpt=text[:1000],
            response_payload=payload,
        )

    return payload


def _extract_error_message(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("message", "msg", "error"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(error, str) and error.strip():
        return error.strip()
    for key in ("message", "msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
