import asyncio

from opscli.mcp.tools import helpers
from opscli.mcp.tools import query as query_tools


def _run(coro):
    return asyncio.run(coro)


def test_query_metadata_treats_stringified_null_dataset_as_absent(monkeypatch):
    """dataset 为字符串化空值时应改用同时提供的有效 table_id。"""
    captured = {}

    class DummyResult:
        def to_dict(self):
            return {"dataset": {"table_id": 1}, "fields": [], "source": "remote"}

    class DummyManager:
        def metadata(self, **kwargs):
            captured["kwargs"] = kwargs
            return DummyResult()

    monkeypatch.setattr(
        helpers, "_get_auth_pair", lambda system, session_id, jwt: ("sid-1", "jwt-1")
    )
    monkeypatch.setattr(
        query_tools, "_query_manager", lambda jwt=None, session_id=None: DummyManager()
    )

    result = _run(
        query_tools.query_metadata(
            dataset=" NULL ", table_id=1, session_id="sid-1", jwt="jwt-1"
        )
    )

    assert result["success"] is True
    assert captured["kwargs"] == {
        "dataset_alias": None,
        "table_id": 1,
        "skills_dir": None,
    }


def test_query_catalog_passes_remote_options_to_manager(monkeypatch):
    captured = {}

    class DummyManager:
        def catalog(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"version": "remote", "intent_count": 1, "intents": []}

    monkeypatch.setattr(helpers, "_get_auth_pair", lambda system, session_id, jwt: ("sid-1", "jwt-1"))
    monkeypatch.setattr(query_tools, "_query_manager", lambda jwt=None, session_id=None: DummyManager())

    result = _run(
        query_tools.query_catalog(
            skills_dir="/tmp/skills",
            source="remote",
            fallback_local=False,
            session_id="sid-1",
            jwt="jwt-1",
        )
    )

    assert result["success"] is True
    assert result["data"]["version"] == "remote"
    assert captured["kwargs"] == {
        "skills_dir": "/tmp/skills",
        "source": "remote",
        "fallback_local": False,
    }


def test_query_intent_match_reports_mcp_intent_source(monkeypatch):
    """MCP 路径调用 intent_match 必须显式声明 report_source="mcp_intent"，
    避免服务端归因统计沿用默认值 "cli_intent" 而误判调用来源。"""
    captured = {}

    class DummyManager:
        def intent_match(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"matched": True, "candidates": [], "match_record_id": 1}

    monkeypatch.setattr(helpers, "_get_auth_pair", lambda system, session_id, jwt: ("sid-1", "jwt-1"))
    monkeypatch.setattr(query_tools, "_query_manager", lambda jwt=None, session_id=None: DummyManager())

    result = _run(
        query_tools.query_intent_match(
            query="看下广告费",
            session_id="sid-1",
            jwt="jwt-1",
        )
    )

    assert result["success"] is True
    assert captured["kwargs"]["report_source"] == "mcp_intent"


def test_query_simple_forwards_global_currency(monkeypatch):
    """MCP query_simple 必须把 global_currency 透传给 QueryManager。"""
    captured = {}

    class DummyManager:
        def build_simple_and_run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "payload": {"globalCurrency": kwargs.get("global_currency")},
                "result": {},
            }

    monkeypatch.setattr(
        helpers, "_get_auth_pair", lambda system, session_id, jwt: ("sid-1", "jwt-1")
    )
    monkeypatch.setattr(
        query_tools, "_query_manager", lambda jwt=None, session_id=None: DummyManager()
    )

    result = _run(
        query_tools.query_simple(
            table_id=1,
            metrics=["price:SUM"],
            global_currency="USD",
        )
    )

    assert result["success"] is True
    assert captured["kwargs"]["global_currency"] == "USD"


def test_query_simple_omits_global_currency_by_default(monkeypatch):
    """未指定币种时只透传 None，不注入默认值；最终币种以返回声明为准。"""
    captured = {}

    class DummyManager:
        def build_simple_and_run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"payload": {}, "result": {}}

    monkeypatch.setattr(
        helpers, "_get_auth_pair", lambda system, session_id, jwt: ("sid-1", "jwt-1")
    )
    monkeypatch.setattr(
        query_tools, "_query_manager", lambda jwt=None, session_id=None: DummyManager()
    )

    result = _run(query_tools.query_simple(table_id=1, metrics=["price:SUM"]))

    assert result["success"] is True
    assert captured["kwargs"]["global_currency"] is None


def test_query_build_and_build_and_run_forward_global_currency(monkeypatch):
    """query_build 与 query_build_and_run 同样透传币种参数。"""
    captured = {}

    class DummyManager:
        def build(self, **kwargs):
            captured["build"] = kwargs
            return {"payload": {}}

        def build_and_run(self, **kwargs):
            captured["build_and_run"] = kwargs
            return {"payload": {}, "result": {}}

    monkeypatch.setattr(
        helpers, "_get_auth_pair", lambda system, session_id, jwt: ("sid-1", "jwt-1")
    )
    monkeypatch.setattr(
        query_tools, "_query_manager", lambda jwt=None, session_id=None: DummyManager()
    )

    _run(
        query_tools.query_build(
            table_id=1, metrics=["price:SUM"], global_currency="EUR"
        )
    )
    _run(
        query_tools.query_build_and_run(
            table_id=1, metrics=["price:SUM"], global_currency="EUR"
        )
    )

    assert captured["build"]["global_currency"] == "EUR"
    assert captured["build_and_run"]["global_currency"] == "EUR"
