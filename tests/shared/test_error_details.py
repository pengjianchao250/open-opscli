"""服务端字段级错误详情必须透传给调用方的回归测试。

事故形态：服务端（Laravel）在 `error_details` 里返回
`{"filters.0.operator": ["..."]}` 这种字段级原因，但 `msg` 只有笼统的
「参数验证失败」。此前 parse_remote_response 只取 msg，详情被整段丢弃，
Agent 拿不到「是哪个字段哪条规则不合法」，只能改写请求盲试——
线上 3987 条取数反馈中有 347 条（8.7%）卡在这一步。
"""

from __future__ import annotations

import httpx
import pytest

from opscli.shared.http import extract_error_details, parse_remote_response


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


def _parse(payload: dict, status_code: int = 200):
    response = httpx.Response(status_code, json=payload)
    return parse_remote_response(
        response,
        http_error_cls=_HttpError,
        business_error_cls=_BusinessError,
        bad_json_error_cls=_BadJsonError,
    )


def test_business_error_carries_field_level_reasons():
    """业务错误必须把 error_details 里的字段级原因拼进消息。"""
    payload = {
        "code": 422,
        "msg": "参数验证失败",
        "data": [],
        "error_details": {
            "filters.0.operator": ["The filters.0.operator field is required."],
            "tableId": ["The table id must be an integer."],
        },
    }
    with pytest.raises(_BusinessError) as excinfo:
        _parse(payload)
    message = str(excinfo.value)
    assert "参数验证失败" in message
    assert "filters.0.operator" in message, f"字段级原因被丢弃：{message}"
    assert "tableId" in message


def test_http_error_also_carries_details():
    """HTTP 4xx/5xx 分支同样要透传详情。"""
    payload = {"msg": "请求非法", "error_details": {"limit": ["must be <= 10000"]}}
    with pytest.raises(_HttpError) as excinfo:
        _parse(payload, status_code=422)
    assert "limit" in str(excinfo.value)


def test_no_details_keeps_message_unchanged():
    """没有 error_details 时消息保持原样，不加空括号。"""
    with pytest.raises(_BusinessError) as excinfo:
        _parse({"code": 400, "msg": "远端拒绝"})
    assert str(excinfo.value) == "远端拒绝"


def test_details_are_not_duplicated_into_message():
    """详情已包含在 msg 里时不重复拼接。"""
    with pytest.raises(_BusinessError) as excinfo:
        _parse({"code": 400, "msg": "字段 asin 不存在", "error_details": "字段 asin 不存在"})
    assert str(excinfo.value).count("字段 asin 不存在") == 1


@pytest.mark.parametrize(
    "details,expected_fragment",
    [
        ({"asin": ["不存在"]}, "asin: 不存在"),
        ({"a": ["x", "y"]}, "a: x；y"),
        (["裸字符串原因"], "裸字符串原因"),
        ("整段字符串", "整段字符串"),
    ],
)
def test_detail_shapes(details, expected_fragment):
    """服务端可能给 dict / list / str 三种形态，都要能展开。"""
    assert expected_fragment in (extract_error_details({"error_details": details}) or "")


def test_too_many_fields_are_truncated_with_marker():
    """字段过多时截断并标注省略，避免把整个校验器输出灌进终端。"""
    text = extract_error_details({"error_details": {f"f{i}": ["bad"] for i in range(20)}})
    assert text.endswith("…")
    assert text.count("；") <= 6


def test_success_payload_is_untouched():
    """成功返回不受影响。"""
    assert _parse({"code": 200, "msg": "ok", "data": {"x": 1}})["data"] == {"x": 1}
