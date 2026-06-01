"""卖家精灵接口直连客户端。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

LOGIN_PAGE_URL = "https://www.sellersprite.com/cn/w/user/login"
SIGNIN_URL = "https://www.sellersprite.com/w/user/signin"
BASE_URL = "https://www.sellersprite.com"


class SellerSpriteApiClient:
    """使用服务端账号登录并调用卖家精灵 Web 接口。"""

    def __init__(
        self,
        *,
        account: SellerSpriteAccount,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 60.0,
    ) -> None:
        self.account = account
        self.user_agent = user_agent
        self.login_status: int | None = None
        self.login_redirect = False
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers=self._browser_headers(),
        )

    async def __aenter__(self) -> "SellerSpriteApiClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层 HTTP client。"""
        await self._client.aclose()

    async def login(self) -> dict[str, Any]:
        """登录卖家精灵并保留 cookie。"""
        await self._client.get(LOGIN_PAGE_URL, headers=self._browser_headers())

        password_md5 = _md5(self.account.password)
        form = {
            "callback": "",
            "password": password_md5,
            "email": self.account.username,
            "autoLogin": "Y",
            "salt": _md5(self.account.username + password_md5),
        }
        response = await self._client.post(
            SIGNIN_URL,
            data=form,
            headers={
                **self._browser_headers(referer=LOGIN_PAGE_URL),
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
            },
        )
        self.login_status = response.status_code
        location = response.headers.get("location", "")
        self.login_redirect = bool(location)
        if location:
            await self._client.get(
                str(httpx.URL(BASE_URL).join(location)),
                headers=self._browser_headers(referer=LOGIN_PAGE_URL),
            )
        if response.status_code >= 400:
            raise SellerSpriteApiError(
                "卖家精灵登录失败",
                status_code=response.status_code,
                response_excerpt=response.text[:1000],
            )
        return {
            "login_status": self.login_status,
            "login_redirect": self.login_redirect,
            "cookie_names": self.cookie_names(),
        }

    async def post_json(self, url: str, payload: dict[str, Any], *, referer: str | None = None) -> dict[str, Any]:
        """POST JSON 并返回接口 JSON。"""
        response = await self._client.post(
            _absolute_url(url),
            json=payload,
            headers={
                **self._browser_headers(referer=referer),
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": BASE_URL,
                "Priority": "u=1, i",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            },
        )
        return self._parse_json_response(response)

    async def post_form(self, url: str, payload: dict[str, Any], *, referer: str | None = None) -> str:
        """POST 表单并返回页面文本。"""
        response = await self._client.post(
            _absolute_url(url),
            data=payload,
            headers={
                **self._browser_headers(referer=referer),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
            },
        )
        if response.status_code >= 400:
            raise SellerSpriteApiError(
                "卖家精灵表单请求失败",
                status_code=response.status_code,
                response_excerpt=response.text[:1000],
            )
        return response.text

    async def get_json(self, url: str, params: dict[str, Any], *, referer: str | None = None) -> dict[str, Any]:
        """GET JSON 并返回接口 JSON。"""
        response = await self._client.get(
            _absolute_url(url),
            params=params,
            headers={
                **self._browser_headers(referer=referer),
                "Accept": "application/json, text/plain, */*",
            },
        )
        return self._parse_json_response(response)

    async def request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """发送通用请求并返回接口 JSON。"""
        response = await self._client.request(method, _absolute_url(url), **kwargs)
        return self._parse_json_response(response)

    def cookie_names(self) -> list[str]:
        """返回当前 cookie 名称。"""
        return [cookie.name for cookie in self._client.cookies.jar]

    def _parse_json_response(self, response: httpx.Response) -> dict[str, Any]:
        """解析并校验接口响应。"""
        text = response.text
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise SellerSpriteApiError(
                "卖家精灵接口返回非 JSON",
                status_code=response.status_code,
                response_excerpt=text[:1000],
            ) from exc
        if response.status_code >= 400:
            raise SellerSpriteApiError(
                "卖家精灵接口请求失败",
                status_code=response.status_code,
                response_excerpt=text[:1000],
            )
        code = payload.get("code") if isinstance(payload, dict) else None
        if code and code != "OK":
            raise SellerSpriteApiError(
                f"卖家精灵接口返回错误：{code}",
                status_code=response.status_code,
                response_excerpt=text[:1000],
            )
        return payload

    def _browser_headers(self, *, referer: str | None = None) -> dict[str, str]:
        """构造接近 Web 浏览器的请求头。"""
        headers = {
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": self.user_agent,
            "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        if referer:
            headers["Referer"] = referer
        return headers


def _absolute_url(url: str) -> str:
    """支持传入完整 URL 或站内路径。"""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{BASE_URL}{url if url.startswith('/') else '/' + url}"


def _md5(value: str) -> str:
    """计算 MD5 小写十六进制字符串。"""
    return hashlib.md5(value.encode("utf-8")).hexdigest()
