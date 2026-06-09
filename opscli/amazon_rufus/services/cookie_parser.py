"""Rufus Cookie header 解析服务。

该模块只把用户提供的 Amazon Cookie header 转换为最小 Playwright
storage_state，方便复用既有本地状态存储。
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from opscli.amazon_rufus.domain.exceptions import InvalidRufusCookieError


class RufusCookieParser:
    """将 Cookie header 转换为 Playwright storage_state。"""

    def parse_cookie_header(self, cookie_header: str, *, marketplace_origin: str) -> dict:
        """解析 Cookie header 并返回最小 storage_state。

        Args:
            cookie_header: Amazon Cookie header 原文。
            marketplace_origin: 当前国家站点 origin，例如 `https://www.amazon.com`。

        Returns:
            dict: Playwright 兼容的最小 storage_state。

        Raises:
            InvalidRufusCookieError: cookie 为空、格式无效或站点 host 无效。
        """
        raw_cookie = str(cookie_header or "").strip()
        if not raw_cookie:
            raise InvalidRufusCookieError("cookie 不能为空")

        host = (urlsplit(marketplace_origin).hostname or "").strip().lower()
        if not host:
            raise InvalidRufusCookieError("Amazon 站点地址无效，无法生成 cookie domain")
        cookie_domain = host[4:] if host.startswith("www.") else host

        parsed = SimpleCookie()
        try:
            parsed.load(raw_cookie)
        except Exception as exc:
            raise InvalidRufusCookieError("cookie 格式无效") from exc

        cookies = []
        for name, morsel in parsed.items():
            cookie_name = str(name or "").strip()
            cookie_value = str(morsel.value or "")
            if not cookie_name:
                continue
            # 使用国家站点 host 生成 domain，避免把 US cookie 错写到其他站点。
            cookies.append(
                {
                    "name": cookie_name,
                    "value": cookie_value,
                    "domain": f".{cookie_domain}",
                    "path": "/",
                    "secure": True,
                    "httpOnly": False,
                    "sameSite": "Lax",
                }
            )

        if not cookies:
            raise InvalidRufusCookieError("cookie 中未找到有效键值")
        return {"cookies": cookies, "origins": []}
