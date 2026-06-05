"""西柚洞察接口直连客户端。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx

from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential
from opscli.xiyou.domain.exceptions import XiyouApiError


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

BASE_URL = "https://api.xydc.com"
WEB_ORIGIN = "https://www.xydc.com"


class XiyouApiClient:
    """使用本地配置 token 调用西柚洞察 Web API。"""

    def __init__(
        self,
        *,
        credential: XiyouCredential,
        settings: XiyouSettings,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 60.0,
    ) -> None:
        self.credential = credential
        self.settings = settings
        self.user_agent = user_agent
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers=self._browser_headers(),
        )

    async def __aenter__(self) -> "XiyouApiClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层 HTTP client。"""
        await self._client.aclose()

    async def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON 并返回接口 JSON。"""
        response = await self._client.post(
            _absolute_url(url),
            json=payload,
            headers=self._browser_headers(),
        )
        return self._parse_json_response(response)

    def _parse_json_response(self, response: httpx.Response) -> dict[str, Any]:
        """解析并校验接口响应。"""
        text = response.text
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise XiyouApiError(
                "西柚洞察接口返回非 JSON",
                status_code=response.status_code,
                response_excerpt=text[:1000],
            ) from exc
        if response.status_code >= 400:
            raise XiyouApiError(
                "西柚洞察接口请求失败",
                status_code=response.status_code,
                response_excerpt=text[:1000],
            )
        code = payload.get("code") if isinstance(payload, dict) else None
        if code not in (None, 0, 200, "0", "200", "OK", "ok", "success"):
            raise XiyouApiError(
                f"西柚洞察接口返回错误：{code}",
                status_code=response.status_code,
                response_excerpt=text[:1000],
            )
        return payload

    def _browser_headers(self) -> dict[str, str]:
        """构造接近 Web 浏览器的请求头。"""
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "authorization": self.credential.authorization,
            "content-type": "application/json",
            "krs-ver": self.settings.krs_ver or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "origin": WEB_ORIGIN,
            "referer": f"{WEB_ORIGIN}/",
            "request-url": "/detail/ranking_list",
            "select-lang": "zh-cn",
            "user-agent": self.user_agent,
            "web-version": "4.0",
        }
        if self.credential.cookie:
            headers["cookie"] = self.credential.cookie
        return headers


def _absolute_url(url: str) -> str:
    """支持传入完整 URL 或站内路径。"""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{BASE_URL}{url if url.startswith('/') else '/' + url}"

