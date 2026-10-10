"""公共解析函数对「非 JSON 远端响应」的回归测试（Bug 12133）。

事故形态：OPS 网关（nginx）在后端超时时返回 504/502 HTML 错误页，
旧版 parse_remote_response 先做 JSON 解码、后看状态码，
把网关错误、PHP fatal 文本、空 body 全部压成同一个 BAD_REMOTE_JSON，
HTTP 状态码、Content-Type、出错接口路径全部丢失，调用方无法判断是否可重试。

样本取自离线复现脚本的 8 种响应形态；平台 Cookie 接口的 2xx body 是
Amazon Cookie 原文，任何错误消息都不得回显 body 内容。
"""

from __future__ import annotations

import json

import httpx
import pytest

from opscli.shared.http import parse_remote_response

# 与 QA 网关实测同模板的 nginx 默认错误页（状态码替换）
NGINX_504 = (
    "<html>\r\n<head><title>504 Gateway Time-out</title></head>\r\n<body>\r\n"
    "<center><h1>504 Gateway Time-out</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n"
)
NGINX_502 = NGINX_504.replace("504 Gateway Time-out", "502 Bad Gateway")
PHP_FATAL_TEXT = (
    "PHP Fatal error:  Maximum execution time of 30 seconds exceeded in "
    "/data/www/ops-pre-release/ops-api/vendor/x.php on line 120"
)
# 平台 Cookie 接口 content 承载的是浏览器 cURL 原文，里面就是 Amazon 会话 Cookie
FAKE_CURL = (
    "curl 'https://www.amazon.com/rufus/cl/streaming?tabId=t1' "
    "-H 'cookie: session-id=1; ubid-main=2; at-main=3' --data-raw '{}'"
)
OK_JSON = {"code": 200, "msg": "ok", "data": {"platform": "amazon", "country": "US", "content": FAKE_CURL}}
PLATFORM_COOKIE_URL = "https://ops.api.qa.aukeyit.com/api/v1/platform-cookies?platform=amazon"
# 任何错误消息中都不允许出现的敏感/正文片段
SECRET_FRAGMENTS = ("session-id", "ubid-main", "at-main", "curl", "rufus/cl/streaming", "platform=amazon", "Warning")


def make_response(status: int, *, text: str | None = None, js: dict | None = None, ctype: str = "text/html") -> httpx.Response:
    """构造带请求对象的 httpx.Response，模拟平台 Cookie 接口返回。"""
    request = httpx.Request("GET", PLATFORM_COOKIE_URL)
    if js is not None:
        return httpx.Response(status, json=js, request=request)
    return httpx.Response(
        status,
        content=(text or "").encode("utf-8"),
        headers={"content-type": ctype},
        request=request,
    )


def remote_samples() -> list[tuple[str, httpx.Response]]:
    """返回离线复现的 8 种远端响应形态（每次调用生成新对象，避免跨用例共享状态）。"""
    return [
        ("200_json", make_response(200, js=OK_JSON)),
        ("504_nginx_html", make_response(504, text=NGINX_504)),
        ("502_nginx_html", make_response(502, text=NGINX_502)),
        ("500_php_text", make_response(500, text=PHP_FATAL_TEXT, ctype="text/plain")),
        ("200_empty", make_response(200, text="", ctype="application/json")),
        (
            "200_warning_prefix",
            make_response(
                200,
                text="<br />\n<b>Warning</b>: x in y\n" + json.dumps(OK_JSON),
                ctype="application/json",
            ),
        ),
        ("503_json", make_response(503, js={"code": 503, "message": "服务繁忙"})),
        ("401_json", make_response(401, js={"code": 401, "message": "未授权访问"})),
    ]


class _HttpError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class _BusinessError(Exception):
    def __init__(self, business_code, message):
        super().__init__(message)
        self.business_code = business_code


class _BadJsonError(Exception):
    pass


def _parse(response):
    return parse_remote_response(
        response,
        http_error_cls=_HttpError,
        business_error_cls=_BusinessError,
        bad_json_error_cls=_BadJsonError,
    )


# 期望：(错误类, HTTP 状态码, 消息中必须包含的诊断片段)
_EXPECTED = {
    "200_json": (None, None, ()),
    "504_nginx_html": (_HttpError, 504, ("HTTP 504", "非 JSON", "text/html", "/api/v1/platform-cookies", "504 Gateway Time-out")),
    "502_nginx_html": (_HttpError, 502, ("HTTP 502", "非 JSON", "text/html", "502 Bad Gateway")),
    "500_php_text": (_HttpError, 500, ("HTTP 500", "非 JSON", "text/plain", "/api/v1/platform-cookies")),
    "200_empty": (_BadJsonError, 200, ("无法解析的 JSON", "HTTP 200", "application/json", "空 body")),
    "200_warning_prefix": (_BadJsonError, 200, ("无法解析的 JSON", "HTTP 200", "/api/v1/platform-cookies")),
    "503_json": (_HttpError, 503, ("服务繁忙",)),
    "401_json": (_HttpError, 401, ("未授权访问",)),
}


@pytest.mark.parametrize("name,response", remote_samples(), ids=[name for name, _ in remote_samples()])
def test_non_json_response_checks_status_before_json(name, response):
    """非 JSON 响应先看状态码：>=400 报 HTTP 错误并带诊断，2xx 才报 bad_json。"""
    expected_cls, expected_status, fragments = _EXPECTED[name]
    if expected_cls is None:
        assert _parse(response)["data"]["country"] == "US"
        return

    with pytest.raises(expected_cls) as exc_info:
        _parse(response)

    message = str(exc_info.value)
    if expected_cls is _HttpError:
        assert exc_info.value.status_code == expected_status
    for fragment in fragments:
        assert fragment in message, (name, message)
    # 反向断言：错误消息不得泄露 Cookie/cURL 原文、query 参数或 body 片段
    for secret in SECRET_FRAGMENTS:
        assert secret not in message, (name, secret, message)
    # body 字节数随响应浮动，写进 message 会让反馈指纹漂移，消息里只允许出现稳定的「空 body」标记
    assert "字节" not in message, (name, message)


def test_non_json_2xx_never_echoes_body_even_if_it_has_title():
    """2xx 非 JSON 响应一律不截取 body（平台 Cookie 的 2xx body 就是 Cookie 原文）。"""
    body = f"<html><head><title>{FAKE_CURL}</title></head><body>{FAKE_CURL}</body></html>"
    response = make_response(200, text=body)

    with pytest.raises(_BadJsonError) as exc_info:
        _parse(response)

    message = str(exc_info.value)
    assert "text/html" in message
    for secret in SECRET_FRAGMENTS:
        assert secret not in message


def test_non_html_error_body_never_extracts_title():
    """Content-Type 不含 html 的 4xx/5xx 正文即使带 <title> 也不摘取（与「非 HTML 正文不回显」一致）。"""
    response = make_response(403, text="<title>internal-host-01 denied</title> raw text", ctype="text/plain")

    with pytest.raises(_HttpError) as exc_info:
        _parse(response)

    message = str(exc_info.value)
    assert "text/plain" in message
    assert "title=" not in message
    assert "internal-host-01" not in message


@pytest.mark.parametrize(
    "title",
    ["session-id=abc expired", "Invalid Cookie header", "token refresh failed", "curl: (52) Empty reply"],
)
def test_html_error_title_with_sensitive_pattern_is_masked(title):
    """错误页标题命中 cookie/session/token/curl/= 等敏感模式时用占位替换，不回显原文。"""
    response = make_response(502, text=f"<html><head><title>{title}</title></head></html>")

    with pytest.raises(_HttpError) as exc_info:
        _parse(response)

    message = str(exc_info.value)
    assert "title=（已隐藏）" in message
    assert title not in message


def test_non_json_error_without_request_or_headers_still_maps_status():
    """测试桩常见的极简响应对象（无 headers/request）也必须按状态码归类，不抛额外异常。"""

    class BareResponse:
        status_code = 504

        def json(self):
            raise ValueError("bad json")

    with pytest.raises(_HttpError) as exc_info:
        _parse(BareResponse())

    assert exc_info.value.status_code == 504
    assert "HTTP 504" in str(exc_info.value)


def _module_error_triples():
    """收集所有调用公共解析函数的模块异常三元组（HTTP、业务、bad_json）。"""
    from opscli.amazon.domain import exceptions as amazon_exc
    from opscli.amazon_rufus.domain import exceptions as rufus_exc
    from opscli.asin_data.services import bi_report_data, category_top, report_files
    from opscli.asin_review.domain import exceptions as review_exc
    from opscli.baiyi.domain import exceptions as baiyi_exc
    from opscli.feedback.domain import exceptions as feedback_exc
    from opscli.mcp_client import config_client
    from opscli.query.domain import exceptions as query_exc
    from opscli.shared import integration_accounts

    return [
        (query_exc.RemoteHttpError, query_exc.RemoteBusinessError, query_exc.BadRemoteJsonError),
        (amazon_exc.RemoteHttpError, amazon_exc.RemoteBusinessError, amazon_exc.BadRemoteJsonError),
        (feedback_exc.RemoteHttpError, feedback_exc.RemoteBusinessError, feedback_exc.BadRemoteJsonError),
        (rufus_exc.RufusRemoteHttpError, rufus_exc.RufusRemoteBusinessError, rufus_exc.RufusBadRemoteJsonError),
        (review_exc.ReviewHttpError, review_exc.ReviewBusinessError, review_exc.ReviewBadJsonError),
        (baiyi_exc.BaiyiProductInfoHttpError, baiyi_exc.BaiyiProductInfoBusinessError, baiyi_exc.BaiyiProductInfoBadJsonError),
        (category_top.AsinCategoryTopHttpError, category_top.AsinCategoryTopBusinessError, category_top.AsinCategoryTopBadJsonError),
        (bi_report_data.AsinBiReportDataHttpError, bi_report_data.AsinBiReportDataBusinessError, bi_report_data.AsinBiReportDataBadJsonError),
        (report_files.AsinReportFileHttpError, report_files.AsinReportFileBusinessError, report_files.AsinReportFileBadJsonError),
        (
            integration_accounts.IntegrationAccountHttpError,
            integration_accounts.IntegrationAccountBusinessError,
            integration_accounts.IntegrationAccountBadJsonError,
        ),
        (config_client.RemoteConfigHttpError, config_client.RemoteConfigBusinessError, config_client.BadRemoteConfigError),
    ]


def test_every_caller_module_maps_gateway_504_html_to_http_error():
    """所有调用方模块的 HTTP 异常类都能承接 504 HTML，错误码不再是 *_BAD_JSON。"""
    for http_cls, business_cls, bad_json_cls in _module_error_triples():
        with pytest.raises(http_cls) as exc_info:
            parse_remote_response(
                make_response(504, text=NGINX_504),
                http_error_cls=http_cls,
                business_error_cls=business_cls,
                bad_json_error_cls=bad_json_cls,
            )
        assert exc_info.value.status_code == 504
        assert "BAD" not in str(getattr(exc_info.value, "code", "")), http_cls
