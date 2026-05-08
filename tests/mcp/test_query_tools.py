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

