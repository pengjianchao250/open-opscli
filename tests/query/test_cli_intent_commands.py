"""catalog/intent 接口恢复回归：命令注册即视为对外承诺，防止再次静默消失。"""
from typer.testing import CliRunner

from opscli.query.commands.cli import app


def _registered_commands() -> set:
    return {command.name for command in app.registered_commands}


def test_catalog_and_intent_commands_registered():
    assert {"catalog", "intent"} <= _registered_commands()


def test_intent_command_outputs_match_result(monkeypatch):
    """intent 命令输出 JSON 信封，data 为匹配结果。"""
    from opscli.query.services.manager import QueryManager

    def fake_intent_match(self, **kwargs):
        return {"matched": False, "fallback_required": True, "candidates": []}

    monkeypatch.setattr(QueryManager, "intent_match", fake_intent_match)
    result = CliRunner().invoke(app, ["intent", "--query", "看下广告费"])
    assert result.exit_code == 0
    assert '"command": "query intent"' in result.stdout or '"command":"query intent"' in result.stdout


def test_mcp_tools_registered():
    from opscli.mcp.tools import query as query_tools

    tool_names = {tool.__name__ for tool in query_tools._ALL_TOOLS}
    assert {"query_catalog", "query_intent_match"} <= tool_names
