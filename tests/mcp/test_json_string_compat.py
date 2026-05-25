"""测试 AI 将 list/dict 参数以 JSON 字符串传入时的容错兼容性。

背景：Claude 等 LLM 调用 MCP 工具时，有时会将 list/dict 类型参数
JSON.stringify() 为字符串传入，导致 FastMCP Pydantic 验证失败。
本测试验证 _parse_json_arg 和各工具函数对此场景的容错处理。
"""

import asyncio
import json

import pytest

from opscli.mcp.tools import helpers
from opscli.mcp.tools import query as query_tools
from opscli.mcp.tools import feedback as feedback_tools
from opscli.mcp.tools.helpers import _parse_json_arg


# ── _parse_json_arg 单元测试 ─────────────────────────────────────────────

class TestParseJsonArg:
    def test_none_returns_none(self):
        assert _parse_json_arg(None, list) is None
        assert _parse_json_arg(None, dict) is None

    def test_list_passthrough(self):
        """已是 list 不做转换。"""
        val = ["a", "b"]
        assert _parse_json_arg(val, list) is val

    def test_dict_passthrough(self):
        """已是 dict 不做转换。"""
        val = {"k": "v"}
        assert _parse_json_arg(val, dict) is val

    def test_json_string_to_list(self):
        """JSON 字符串自动解析为 list。"""
        assert _parse_json_arg('["country_name", "asin"]', list) == ["country_name", "asin"]

    def test_json_string_to_dict(self):
        """JSON 字符串自动解析为 dict。"""
        assert _parse_json_arg('{"key": "val"}', dict) == {"key": "val"}

    def test_complex_list_string(self):
        """复杂嵌套 list（如 filters）能正确解析。"""
        raw = '[{"field": "date_id", "operator": ">=", "value": "2026-05-01"}]'
        result = _parse_json_arg(raw, list)
        assert isinstance(result, list)
        assert result[0]["field"] == "date_id"

    def test_invalid_json_raises(self):
        """非法 JSON 字符串抛出 ValueError。"""
        with pytest.raises(ValueError, match="无法解析"):
            _parse_json_arg("not-valid-json", list)

    def test_wrong_type_after_parse_raises(self):
        """JSON 解析后类型不匹配抛出 ValueError。"""
        with pytest.raises(ValueError, match="期望 list"):
            _parse_json_arg('{"k": "v"}', list)  # dict 但期望 list

    def test_wrong_type_dict_expects_list(self):
        with pytest.raises(ValueError, match="期望 dict"):
            _parse_json_arg('["a"]', dict)  # list 但期望 dict


# ── query_build 容错测试 ─────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


class TestQueryBuildJsonStringCompat:
    """模拟 AI 将 list 参数序列化为 JSON 字符串后调用 query_build 的场景。"""

    def setup_method(self):
        self.captured = {}

        class DummyManager:
            def build(inner_self, **kwargs):
                self.captured.update(kwargs)
                return {"payload": "ok"}

        self._dummy_cls = DummyManager

    def test_dimensions_as_json_string(self, monkeypatch):
        """dimensions 以 JSON 字符串传入，应自动解析为 list。"""
        monkeypatch.setattr(
            query_tools, "_query_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        result = _run(
            query_tools.query_build(
                table_id=1,
                dimensions='["country_name", "asin"]',   # 字符串，非 list
                metrics='["ads_spend:SUM"]',
            )
        )
        assert result["success"] is True
        assert self.captured["dimensions"] == ["country_name", "asin"]
        assert self.captured["metrics"] == ["ads_spend:SUM"]

    def test_where_conditions_as_json_string(self, monkeypatch):
        """where_conditions 以 JSON 字符串传入，应自动解析为 list。"""
        monkeypatch.setattr(
            query_tools, "_query_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        conds = json.dumps(['date_id|>=|"2026-05-01"', 'dept_name|=|"宁波"'])
        result = _run(
            query_tools.query_build(
                table_id=1,
                where_conditions=conds,
            )
        )
        assert result["success"] is True
        assert isinstance(self.captured["where_conditions"], list)
        assert len(self.captured["where_conditions"]) == 2

    def test_order_by_as_json_string(self, monkeypatch):
        """order_by 以 JSON 字符串传入，应自动解析为 list。"""
        monkeypatch.setattr(
            query_tools, "_query_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        result = _run(
            query_tools.query_build(
                table_id=1,
                order_by='["f_spend:desc"]',
            )
        )
        assert result["success"] is True
        assert self.captured["order_by"] == ["f_spend:desc"]


# ── query_simple 容错测试 ────────────────────────────────────────────────

class TestQuerySimpleJsonStringCompat:
    """模拟 AI 将 filters/data_comparison 序列化为 JSON 字符串后调用 query_simple 的场景。"""

    def setup_method(self):
        self.captured = {}

        class DummyManager:
            def build_simple_and_run(inner_self, **kwargs):
                self.captured.update(kwargs)
                return {"rows": []}

        self._dummy_cls = DummyManager

    def test_filters_as_json_string(self, monkeypatch):
        """filters 以 JSON 字符串传入，应自动解析为 list[dict]。"""
        monkeypatch.setattr(helpers, "_get_auth_pair", lambda s, sid, jwt: ("sid-1", "jwt-1"))
        monkeypatch.setattr(
            query_tools, "_query_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        filters_str = json.dumps([{"field": "date_id", "operator": ">=", "value": "2026-05-01"}])
        result = _run(
            query_tools.query_simple(
                table_id=100,
                filters=filters_str,
            )
        )
        assert result["success"] is True
        assert isinstance(self.captured["filters"], list)
        assert self.captured["filters"][0]["field"] == "date_id"

    def test_data_comparison_as_json_string(self, monkeypatch):
        """data_comparison 以 JSON 字符串传入，应自动解析为 dict。"""
        monkeypatch.setattr(helpers, "_get_auth_pair", lambda s, sid, jwt: ("sid-1", "jwt-1"))
        monkeypatch.setattr(
            query_tools, "_query_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        dc_str = json.dumps({"field": "date_id", "startDate": "2026-04-01", "endDate": "2026-04-30"})
        result = _run(
            query_tools.query_simple(
                table_id=100,
                data_comparison=dc_str,
            )
        )
        assert result["success"] is True
        assert isinstance(self.captured["data_comparison"], dict)
        assert self.captured["data_comparison"]["field"] == "date_id"

    def test_dimensions_and_metrics_as_json_string(self, monkeypatch):
        """dimensions 和 metrics 以 JSON 字符串传入，应自动解析并归一化。"""
        monkeypatch.setattr(helpers, "_get_auth_pair", lambda s, sid, jwt: ("sid-1", "jwt-1"))
        monkeypatch.setattr(
            query_tools, "_query_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        result = _run(
            query_tools.query_simple(
                table_id=100,
                dimensions='["country_name"]',
                metrics='["ads_spend:SUM"]',
            )
        )
        assert result["success"] is True
        # 归一化后应为 dict 格式
        assert self.captured["dimensions"] == [{"field": "country_name"}]
        assert self.captured["metrics"] == [{"field": "ads_spend", "aggregation": "SUM"}]


# ── query_build_and_run 容错测试 ─────────────────────────────────────────

class TestQueryBuildAndRunJsonStringCompat:
    """模拟 AI 将参数序列化为 JSON 字符串后调用 query_build_and_run 的场景。"""

    def setup_method(self):
        self.captured = {}

        class DummyManager:
            def build_and_run(inner_self, **kwargs):
                self.captured.update(kwargs)
                return {"rows": []}

        self._dummy_cls = DummyManager

    def test_all_list_params_as_json_strings(self, monkeypatch):
        """dimensions/metrics/where_conditions/order_by 全部以字符串传入。"""
        monkeypatch.setattr(helpers, "_get_auth_pair", lambda s, sid, jwt: ("sid-1", "jwt-1"))
        monkeypatch.setattr(
            query_tools, "_query_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        result = _run(
            query_tools.query_build_and_run(
                table_id=100,
                dimensions='["country_name"]',
                metrics='["ads_spend_cny:SUM:f_spend"]',
                where_conditions='["dept_name|=|\\"宁波\\""]',
                order_by='["f_spend:desc"]',
            )
        )
        assert result["success"] is True
        assert self.captured["dimensions"] == ["country_name"]
        assert self.captured["metrics"] == ["ads_spend_cny:SUM:f_spend"]
        # json.loads 会还原转义字符：\\" → "，这是正确的解析行为
        assert self.captured["where_conditions"] == ['dept_name|=|"宁波"']
        assert self.captured["order_by"] == ["f_spend:desc"]


# ── feedback_submit 容错测试 ─────────────────────────────────────────────

class TestFeedbackSubmitJsonStringCompat:
    """模拟 AI 将 execution_summary dict 序列化为 JSON 字符串后调用 feedback_submit 的场景。"""

    def setup_method(self):
        self.captured = {}

        class DummyResult:
            def get(self, key, default=None):
                return default

        class DummyManager:
            def submit(inner_self, **kwargs):
                self.captured.update(kwargs)
                return {}

        self._dummy_cls = DummyManager

    def test_execution_summary_as_json_string(self, monkeypatch):
        """execution_summary 以 JSON 字符串传入，应自动解析为 dict。"""
        monkeypatch.setattr(feedback_tools, "_get_auth_pair", lambda s, sid, jwt: ("sid-1", "jwt-1"))
        monkeypatch.setattr(
            feedback_tools, "_feedback_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        summary = {
            "failed_calls": [{"tool": "query_build", "error_message": "ValidationError"}],
            "summary": "测试",
        }
        result = _run(
            feedback_tools.feedback_submit(
                feedback_type="bug",
                title="测试反馈",
                content="测试内容",
                execution_summary=json.dumps(summary),  # 字符串，非 dict
            )
        )
        assert result["success"] is True
        assert isinstance(self.captured["execution_summary"], dict)
        assert self.captured["execution_summary"]["summary"] == "测试"

    def test_native_dict_still_works(self, monkeypatch):
        """正常传入 dict 时不受影响。"""
        monkeypatch.setattr(feedback_tools, "_get_auth_pair", lambda s, sid, jwt: ("sid-1", "jwt-1"))
        monkeypatch.setattr(
            feedback_tools, "_feedback_manager", lambda jwt=None, session_id=None: self._dummy_cls()
        )
        summary = {"summary": "原生dict"}
        result = _run(
            feedback_tools.feedback_submit(
                feedback_type="bug",
                title="测试",
                content="内容",
                execution_summary=summary,
            )
        )
        assert result["success"] is True
        assert self.captured["execution_summary"] is summary
