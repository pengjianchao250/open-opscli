"""共享模块测试：exceptions + http 解析器。"""

import httpx
import pytest

from opscli.amazon.domain.exceptions import (
    AmazonError,
    BadRemoteJsonError as AmazonBadRemoteJsonError,
    RemoteBusinessError as AmazonRemoteBusinessError,
    RemoteHttpError as AmazonRemoteHttpError,
)
from opscli.query.domain.exceptions import (
    BadRemoteJsonError,
    QueryError,
    RemoteBusinessError,
    RemoteHttpError,
)
from opscli.shared.exceptions import RemoteError
from opscli.shared.http import extract_error_message, parse_remote_response


class TestRemoteError:
    """统一异常基类测试。"""

    def test_remote_error_base_has_code_and_message(self):
        exc = RemoteError("测试错误")
        assert exc.message == "测试错误"
        assert exc.code == "REMOTE_ERROR"
        assert str(exc) == "测试错误"

    def test_remote_error_to_dict(self):
        exc = RemoteError("网络超时")
        result = exc.to_dict()
        assert result == {"code": "REMOTE_ERROR", "message": "网络超时"}

    def test_query_error_inherits_remote_error(self):
        assert issubclass(QueryError, RemoteError)
        exc = QueryError("查询失败")
        assert exc.message == "查询失败"
        assert exc.code == "QUERY_ERROR"
        assert exc.to_dict() == {"code": "QUERY_ERROR", "message": "查询失败"}

    def test_amazon_error_inherits_remote_error(self):
        assert issubclass(AmazonError, RemoteError)
        exc = AmazonError("抓取失败")
        assert exc.message == "抓取失败"
        assert exc.code == "AMAZON_ERROR"
        assert exc.to_dict() == {"code": "AMAZON_ERROR", "message": "抓取失败"}

    def test_remote_http_error_to_dict_includes_status_code(self):
        exc = RemoteHttpError(403, "禁止访问")
        result = exc.to_dict()
        assert result["code"] == "REMOTE_HTTP_ERROR"
        assert result["message"] == "禁止访问"
        assert result["status_code"] == 403

    def test_remote_business_error_to_dict_includes_business_code(self):
        exc = RemoteBusinessError(403, "无权限")
        result = exc.to_dict()
        assert result["code"] == "REMOTE_BUSINESS_ERROR"
        assert result["message"] == "无权限"
        assert result["business_code"] == 403

    def test_amazon_remote_http_error_same_structure(self):
        exc = AmazonRemoteHttpError(500, "服务错误")
        result = exc.to_dict()
        assert result["status_code"] == 500
        assert result["message"] == "服务错误"

    def test_amazon_remote_business_error_same_structure(self):
        exc = AmazonRemoteBusinessError("ERR_001", "业务失败")
        result = exc.to_dict()
        assert result["business_code"] == "ERR_001"


class TestExtractErrorMessage:
    """错误消息提取测试。"""

    def test_extracts_msg_field(self):
        assert extract_error_message({"msg": "  操作失败  "}) == "操作失败"

    def test_extracts_message_field(self):
        assert extract_error_message({"message": "权限不足"}) == "权限不足"

    def test_extracts_error_field(self):
        assert extract_error_message({"error": "连接超时"}) == "连接超时"

    def test_priority_order_msg_over_message(self):
        assert extract_error_message({"msg": "msg值", "message": "message值"}) == "msg值"

    def test_returns_none_when_no_message(self):
        assert extract_error_message({"code": 403}) is None

    def test_returns_none_for_empty_string(self):
        assert extract_error_message({"msg": "   "}) is None

    def test_returns_none_for_non_string(self):
        assert extract_error_message({"msg": 123}) is None


class TestParseRemoteResponse:
    """统一 HTTP 响应解析测试。"""

    def test_success_response(self):
        response = httpx.Response(200, json={"code": 200, "data": [1, 2, 3]})
        result = parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )
        assert result["data"] == [1, 2, 3]

    def test_http_error_raised(self):
        response = httpx.Response(404, json={"msg": "不存在"})
        with pytest.raises(RemoteHttpError) as exc_info:
            parse_remote_response(
                response,
                http_error_cls=RemoteHttpError,
                business_error_cls=RemoteBusinessError,
                bad_json_error_cls=BadRemoteJsonError,
            )
        assert exc_info.value.status_code == 404
        assert "不存在" in str(exc_info.value)

    def test_business_error_raised(self):
        response = httpx.Response(200, json={"code": 403, "msg": "无权"})
        with pytest.raises(RemoteBusinessError) as exc_info:
            parse_remote_response(
                response,
                http_error_cls=RemoteHttpError,
                business_error_cls=RemoteBusinessError,
                bad_json_error_cls=BadRemoteJsonError,
            )
        assert exc_info.value.business_code == 403

    def test_bad_json_error_raised_for_invalid_json(self):
        class BadResponse:
            status_code = 200
            def json(self):
                raise ValueError("bad json")

        with pytest.raises(BadRemoteJsonError):
            parse_remote_response(
                BadResponse(),
                http_error_cls=RemoteHttpError,
                business_error_cls=RemoteBusinessError,
                bad_json_error_cls=BadRemoteJsonError,
            )

    def test_bad_json_error_raised_for_non_dict(self):
        response = httpx.Response(200, json=[1, 2, 3])
        with pytest.raises(BadRemoteJsonError):
            parse_remote_response(
                response,
                http_error_cls=RemoteHttpError,
                business_error_cls=RemoteBusinessError,
                bad_json_error_cls=BadRemoteJsonError,
            )

    def test_amazon_exceptions_work_with_shared_parser(self):
        """验证 amazon 模块异常类同样与共享解析器兼容。"""
        response = httpx.Response(200, json={"code": 500, "msg": "服务错误"})
        with pytest.raises(AmazonRemoteBusinessError) as exc_info:
            parse_remote_response(
                response,
                http_error_cls=AmazonRemoteHttpError,
                business_error_cls=AmazonRemoteBusinessError,
                bad_json_error_cls=AmazonBadRemoteJsonError,
            )
        assert exc_info.value.business_code == 500

    def test_http_error_with_no_message_in_payload(self):
        """HTTP 错误但 payload 中无 msg 字段时，使用默认消息。"""
        response = httpx.Response(500, json={"random": "data"})
        with pytest.raises(RemoteHttpError) as exc_info:
            parse_remote_response(
                response,
                http_error_cls=RemoteHttpError,
                business_error_cls=RemoteBusinessError,
                bad_json_error_cls=BadRemoteJsonError,
            )
        assert "HTTP 500" in str(exc_info.value)