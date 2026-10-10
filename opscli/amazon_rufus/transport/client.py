"""Amazon Rufus 远端传输客户端。"""

from __future__ import annotations

import re
import time

import httpx

from opscli.amazon_rufus.domain.exceptions import (
    RufusBadRemoteJsonError,
    RufusPlatformCookieAuthError,
    RufusPlatformCookieUnavailableError,
    RufusRemoteBusinessError,
    RufusRemoteHttpError,
)
from opscli.auth import AuthClient
from opscli.auth.config import get_ops_url
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.http import parse_remote_response


# Rufus 上传接口 path 是后端固定契约，环境切换只覆盖 ops_url。
RUFUS_UPLOAD_ENDPOINT = "/v1/rufus/upload"
PLATFORM_COOKIE_ENDPOINT = "/v1/platform-cookies"
# 读平台 Cookie（亚马逊 Rufus 登录态）的单次超时：body 只有约 4KB cURL 文本，正常秒级返回；
# OPS 网关自身 30~60 秒就会切断请求，原来照搬 Rufus 每题的 180 秒只会拉长失败反馈。
PLATFORM_COOKIE_GET_TIMEOUT_SECONDS = 60
# 读登录态遇网关瞬时错误的重试退避秒数，元素个数即自动重试次数（2 次，最多共 3 次请求）。
# 只读请求幂等，短退避即可越过网关抖动；最坏总等待约 3×60+7 秒，与旧版单次 180 秒相当。
PLATFORM_COOKIE_GET_RETRY_BACKOFF_SECONDS = (2, 5)
# 无论 body 是否为 JSON 都视为网关瞬时故障的 HTTP 状态码
GATEWAY_TRANSIENT_STATUS_CODES = frozenset({502, 503, 504})
# 视为瞬时网络故障、值得重试的 httpx 异常：超时、建连失败、读写中断、对端断连。
# UnsupportedProtocol、InvalidURL、ProxyError、LocalProtocolError 等属于配置/本机问题，重试无益，不在此列。
# 注意 SSL 证书校验失败也表现为 ConnectError，会被重试，但原文会保留在最终错误里供定位。
TRANSIENT_NETWORK_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)
# 网络异常原文保留长度：够区分拒绝连接/证书失败/断连等根因，又不至于刷屏
MAX_NETWORK_ERROR_TEXT_CHARS = 120
# 异常原文可能带完整 URL（含 query 里的业务参数），统一抹掉 URL 与 query
_URL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
_QUERY_PATTERN = re.compile(r"\?\S+")


class RufusTransportClient:
    """封装 Rufus 结果上传能力。"""

    def __init__(self, auth_client: AuthClient | None = None, ops_url: str | None = None) -> None:
        self.auth_client = auth_client or AuthClient()
        self.ops_url = (ops_url or get_ops_url()).rstrip("/")

    def build_disabled_upload_hint(self) -> dict:
        """返回上传禁用说明。"""
        return {"enabled": False, "reason": "默认只构造 upload_payload；显式启用后才发送上传接口"}

    def submit_upload_payload(self, upload_payload: dict) -> dict:
        """提交 Rufus upload_payload 到 ops 后端。"""
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = httpx.post(
            f"{self.ops_url}{RUFUS_UPLOAD_ENDPOINT}",
            json=upload_payload,
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        return parse_remote_response(
            response,
            http_error_cls=RufusRemoteHttpError,
            business_error_cls=RufusRemoteBusinessError,
            bad_json_error_cls=RufusBadRemoteJsonError,
        )

    def save_platform_cookie(self, *, platform: str, country: str, content: str) -> dict:
        """保存或覆盖当前用户指定平台的 Cookie content。"""
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = httpx.post(
            f"{self.ops_url}{PLATFORM_COOKIE_ENDPOINT}",
            json={
                "platform": platform,
                "country": country,
                "content": content,
            },
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        return self._parse_platform_cookie_response(response)

    def get_platform_cookie(self, *, platform: str) -> dict:
        """读取当前用户指定平台保存的 Cookie content。

        读登录态是幂等只读请求：遇网关类瞬时错误（502/503/504、非 JSON 的 5xx）或瞬时网络故障
        （超时、建连失败、读写中断、对端断连）按退避自动重试；URL/协议等配置错误不重试，原异常直接抛出；重试耗尽抛 RufusPlatformCookieUnavailableError（retryable=true），
        明确告诉 Agent 这是 OPS 后端临时不可用，不是 Amazon 登录态失效，避免误触发重新登录。
        其他响应（成功、401、业务码、应用层 500 JSON、2xx 非 JSON 等）不重试，保持原有错误语义。

        Raises:
            RufusPlatformCookieUnavailableError: 网关类瞬时错误重试耗尽
            RufusPlatformCookieAuthError: OPS 平台 Cookie 接口 401
        """
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        attempts = len(PLATFORM_COOKIE_GET_RETRY_BACKOFF_SECONDS) + 1
        for attempt in range(1, attempts + 1):
            try:
                response = httpx.get(
                    f"{self.ops_url}{PLATFORM_COOKIE_ENDPOINT}",
                    params={"platform": platform},
                    headers=headers,
                    cookies=cookies,
                    timeout=PLATFORM_COOKIE_GET_TIMEOUT_SECONDS,
                )
                return self._parse_platform_cookie_response(response)
            except TRANSIENT_NETWORK_ERRORS as exc:
                # 网络层失败没有 HTTP 状态码；保留脱敏截断后的原文，SSL/拒绝连接等根因才能区分
                status_code, last_error = None, self._summarize_network_error(exc)
            except RufusRemoteHttpError as exc:
                if not self._is_gateway_transient(response):
                    raise
                status_code, last_error = exc.status_code, str(exc)
                # JSON 形态的 503 只有「服务繁忙」这类业务文案，补上状态码方便反馈定位
                if f"HTTP {exc.status_code}" not in last_error:
                    last_error = f"HTTP {exc.status_code}：{last_error}"
            if attempt < attempts:
                time.sleep(PLATFORM_COOKIE_GET_RETRY_BACKOFF_SECONDS[attempt - 1])
        raise RufusPlatformCookieUnavailableError(
            attempts=attempts,
            last_error=last_error,
            status_code=status_code,
        )

    @staticmethod
    def _summarize_network_error(exc: Exception) -> str:
        """把网络异常压成「类型: 原文」，原文去掉 URL/query 后截断，避免泄露请求参数。"""
        text = _QUERY_PATTERN.sub("", _URL_PATTERN.sub("<url>", str(exc)))
        text = " ".join(text.split())[:MAX_NETWORK_ERROR_TEXT_CHARS]
        return f"{type(exc).__name__}: {text}" if text else type(exc).__name__

    @staticmethod
    def _is_gateway_transient(response: httpx.Response) -> bool:
        """判断平台 Cookie 响应是否属于可自动重试的网关类瞬时错误。

        502/503/504 一律算；其他 5xx 只有 body 不是 JSON 时才算——非 JSON 说明失败发生在
        nginx/PHP-FPM 进程层面（超时页、fatal 文本），而应用层返回的 500 JSON 多为确定性错误，重试无益。
        """
        if response.status_code in GATEWAY_TRANSIENT_STATUS_CODES:
            return True
        if response.status_code < 500:
            return False
        try:
            response.json()
        except Exception:
            return True
        return False

    def _parse_platform_cookie_response(self, response: httpx.Response) -> dict:
        """解析平台 Cookie 响应，并把 401 固定归类为 OPS 鉴权失败。"""
        try:
            return parse_remote_response(
                response,
                http_error_cls=RufusRemoteHttpError,
                business_error_cls=RufusRemoteBusinessError,
                bad_json_error_cls=RufusBadRemoteJsonError,
            )
        except RufusRemoteHttpError as exc:
            if exc.status_code == 401:
                # 平台 Cookie API 401 代表 OPS/MCP 鉴权失败，不代表亚马逊 Rufus 登录态缺失。
                raise RufusPlatformCookieAuthError(status_code=exc.status_code) from exc
            raise
