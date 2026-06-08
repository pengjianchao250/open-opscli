"""西柚洞察接口直连客户端。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

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

    async def get_bytes(self, url: str) -> bytes:
        """下载 OSS 预签名链接对应的二进制内容。

        独立使用 httpx.AsyncClient 发起请求，避免复用 self._client 时
        把西柚业务请求头（authorization / cookie / origin / referer /
        content-type 等）一并发给 OSS：部分 OSS bucket 在检测到请求中
        同时存在 Authorization 头和 Signature query 参数时，会按
        Authorization 头优先解析签名，从而将合法的预签名链接判为
        SignatureDoesNotMatch。
        同时对 URL path 做规范化，还原西柚返回链接中误编码的 %2F，
        避免 httpx / 代理在转发时对 %2F 处理不一致导致签名失败；
        query 部分严格保留原样，防止 Signature 中的 +、/、= 等
        base64 字符被二次解码。
        """
        normalized = _normalize_oss_url(url)
        async with httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers={"user-agent": self.user_agent},
        ) as raw:
            response = await raw.get(normalized)
        if response.status_code >= 400:
            raise XiyouApiError(
                "西柚洞察文件下载失败",
                status_code=response.status_code,
                response_excerpt=response.text[:2000],
            )
        return response.content

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


def _normalize_oss_url(url: str) -> str:
    """规范化 OSS 预签名 URL：仅还原 path 中误编码的 %2F，query 保持原样。

    西柚返回的下载链接会把 path 中的 `/` 编码成 `%2F`，OSS 服务端在验签时
    总是按解码后的 object key 计算 CanonicalizedResource；客户端先 decode
    path 不会破坏签名，反而能避免 httpx 或中间代理对 %2F 处理不一致。
    query 部分必须严格保留——Signature 里的 `+`、`/`、`=` 已经被 URL-encode
    成 %2B / %2F / %3D，再次 decode 会破坏签名。
    """
    parts = urlsplit(url)
    fixed_path = unquote(parts.path)
    return urlunsplit((parts.scheme, parts.netloc, fixed_path, parts.query, parts.fragment))
