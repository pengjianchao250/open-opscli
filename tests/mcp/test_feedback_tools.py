import asyncio

from opscli.mcp.tools import feedback as feedback_tools
from opscli.mcp.tools.helpers import _err


def _run(coro):
    return asyncio.run(coro)


def test_draft_feedback_contains_required_failed_call_fields():
    result = _err(
        ValueError("字段不存在: original_price"),
        tool="MCP -> query_simple",
        call_params={"table_id": 1},
    )

    feedback = result["feedback"]
    failed_call = feedback["execution_summary"]["failed_calls"][0]

    assert failed_call["tool"] == "MCP -> query_simple"
    assert failed_call["call_params"] == {"table_id": 1}
    assert failed_call["error_message"] == "ValueError: 字段不存在: original_price"
    assert "reason" in failed_call
    assert "fix_suggestion" in failed_call


def test_draft_feedback_uses_empty_call_params_when_missing():
    result = _err(ValueError("boom"))

    failed_call = result["feedback"]["execution_summary"]["failed_calls"][0]

    assert failed_call["call_params"] == {}


def test_feedback_submit_auth_failure_does_not_generate_recursive_feedback(monkeypatch):
    monkeypatch.setattr(
        feedback_tools,
        "_get_auth_pair",
        lambda system, session_id, jwt: (None, None),
    )

    result = _run(
        feedback_tools.feedback_submit(
            feedback_type="bug",
            title="提交失败",
            content="无 session",
        )
    )

    assert result["success"] is False
    assert "feedback" not in result


def test_feedback_submit_manager_failure_does_not_generate_recursive_feedback(monkeypatch):
    class DummyManager:
        def submit(self, **kwargs):
            raise RuntimeError("remote unavailable")

    monkeypatch.setattr(
        feedback_tools,
        "_get_auth_pair",
        lambda system, session_id, jwt: ("sid", "jwt"),
    )
    monkeypatch.setattr(
        feedback_tools,
        "_feedback_manager",
        lambda jwt=None, session_id=None: DummyManager(),
    )

    result = _run(
        feedback_tools.feedback_submit(
            feedback_type="bug",
            title="提交失败",
            content="远端不可用",
        )
    )

    assert result["success"] is False
    assert result["error"]["code"] == "RuntimeError"
    assert "feedback" not in result


def test_feedback_detail_failure_does_not_generate_recursive_feedback(monkeypatch):
    class DummyManager:
        def detail(self, feedback_uuid):
            raise RuntimeError("remote unavailable")

    monkeypatch.setattr(
        feedback_tools,
        "_get_auth_pair",
        lambda system, session_id, jwt: ("sid", "jwt"),
    )
    monkeypatch.setattr(
        feedback_tools,
        "_feedback_manager",
        lambda jwt=None, session_id=None: DummyManager(),
    )

    result = _run(feedback_tools.feedback_detail("fb-1"))

    assert result["success"] is False
    assert result["error"]["code"] == "RuntimeError"
    assert "feedback" not in result
