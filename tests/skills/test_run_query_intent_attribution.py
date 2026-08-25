"""run_query 执行段的意图归因透传回归。"""
import json
import sys
from pathlib import Path

SKILL_SCRIPTS = (
    Path(__file__).parents[2] / "opscli" / "skills" / "templates" / "ops-dataset-query" / "scripts"
)
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

import run_query  # noqa: E402


def test_run_opscli_passes_attribution_flags(monkeypatch):
    """plan 带 intent_code 时，subprocess 命令必须含 --intent-code / --selection-source。"""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0
            stdout = json.dumps({"success": True, "data": {"result": {"success": True, "data": []}}})
            stderr = ""

        return _Result()

    monkeypatch.setattr(run_query.subprocess, "run", fake_run)
    run_query._run_opscli(
        "1", {"dimensions": []},
        intent_code="realtime_sales_monitoring", selection_source="local_fallback",
    )
    cmd = captured["cmd"]
    assert "--intent-code" in cmd and "realtime_sales_monitoring" in cmd
    assert "--selection-source" in cmd and "local_fallback" in cmd


def test_run_opscli_without_attribution_keeps_command_clean(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0
            stdout = json.dumps({"success": True, "data": {"result": {"success": True, "data": []}}})
            stderr = ""

        return _Result()

    monkeypatch.setattr(run_query.subprocess, "run", fake_run)
    run_query._run_opscli("1", {"dimensions": []})
    assert "--intent-code" not in captured["cmd"]
