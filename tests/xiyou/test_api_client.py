"""XiyouApiClient.get_bytes 与 OSS 下载链路相关单元测试。"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from opscli.xiyou.api.client import XiyouApiClient, _normalize_oss_url
from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential
from opscli.xiyou.domain.exceptions import XiyouApiError


def _run(coro):
    return asyncio.run(coro)


def _make_client() -> XiyouApiClient:
    """构造一个带完整业务凭证的 XiyouApiClient，便于验证下载时不会泄漏。"""
    return XiyouApiClient(
        credential=XiyouCredential(authorization="Bearer xiyou-jwt", cookie="sid=abc"),
        settings=XiyouSettings(authorization="Bearer xiyou-jwt", cookie="sid=abc"),
    )


def test_normalize_oss_url_restores_path_slash_and_preserves_query():
    """path 中的 %2F 应被还原为 /，query 中的 %2B / %2F / %3D 应严格保留。"""
    raw = (
        "https://excel.xydc.com/search_by_asin%2F20260528~20260603%2FUS_X.xlsx"
        "?OSSAccessKeyId=LTAI&Expires=1780647406&Signature=RTBwfgNj%2BXKCJms34fD7%2B4wWxZg%3D"
    )
    normalized = _normalize_oss_url(raw)
    assert normalized == (
        "https://excel.xydc.com/search_by_asin/20260528~20260603/US_X.xlsx"
        "?OSSAccessKeyId=LTAI&Expires=1780647406&Signature=RTBwfgNj%2BXKCJms34fD7%2B4wWxZg%3D"
    )


def test_normalize_oss_url_keeps_already_decoded_path():
    """已经是解码形态的 path 不应被破坏。"""
    raw = "https://excel.xydc.com/a/b/c.xlsx?Signature=x%3D"
    assert _normalize_oss_url(raw) == raw


def test_get_bytes_does_not_leak_business_headers_to_oss():
    """get_bytes 发给 OSS 的请求必须只带 user-agent，不能携带任何西柚业务头。"""
    client = _make_client()
    target = (
        "https://excel.xydc.com/search_by_asin%2F20260528~20260603%2FUS_X.xlsx"
        "?OSSAccessKeyId=LTAI&Expires=1780647406&Signature=sig%3D"
    )
    captured: dict[str, httpx.Headers] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["url"] = str(request.url)
        return httpx.Response(200, content=b"xlsx-bytes")

    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(
                "https://excel.xydc.com/search_by_asin/20260528~20260603/US_X.xlsx"
            ).mock(side_effect=_record)
            content = _run(client.get_bytes(target))
    finally:
        _run(client.aclose())

    assert content == b"xlsx-bytes"
    headers = captured["headers"]
    # 关键禁带头：authorization/cookie/origin/referer/content-type
    for forbidden in ("authorization", "cookie", "origin", "referer", "content-type"):
        assert forbidden not in headers, f"OSS 请求不应包含 {forbidden}"
    assert "user-agent" in headers
    # path 中的 %2F 被还原，query 中的 %3D 保留
    assert "/search_by_asin/20260528~20260603/US_X.xlsx" in captured["url"]
    assert "Signature=sig%3D" in captured["url"]


def test_get_bytes_raises_with_response_excerpt_on_403():
    """OSS 返回 403 时应抛出 XiyouApiError 并带响应片段，便于上层透传 StringToSign 等信息。"""
    client = _make_client()
    target = "https://excel.xydc.com/foo.xlsx?Signature=x%3D"
    oss_error_body = (
        "<?xml version=\"1.0\"?><Error>"
        "<Code>SignatureDoesNotMatch</Code>"
        "<Message>The request signature we calculated does not match...</Message>"
        "<StringToSign>GET\\n\\n\\n1780647406\\n/excel/foo.xlsx</StringToSign>"
        "<SignatureProvided>x=</SignatureProvided>"
        "</Error>"
    )
    try:
        with respx.mock() as mock:
            mock.get("https://excel.xydc.com/foo.xlsx").mock(
                return_value=httpx.Response(403, text=oss_error_body)
            )
            with pytest.raises(XiyouApiError) as exc_info:
                _run(client.get_bytes(target))
    finally:
        _run(client.aclose())

    err = exc_info.value
    assert err.status_code == 403
    assert err.response_excerpt is not None
    assert "SignatureDoesNotMatch" in err.response_excerpt
    assert "StringToSign" in err.response_excerpt
