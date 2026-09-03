import asyncio

from opscli.mcp.tools import helpers
from opscli.mcp.tools import query as query_tools


def _run(coro):
    return asyncio.run(coro)


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

