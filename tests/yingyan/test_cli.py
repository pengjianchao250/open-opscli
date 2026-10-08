"""鹰眼 PND 正式 CLI 测试。"""

from pathlib import Path

from typer.testing import CliRunner

from opscli.yingyan import cli as yingyan_cli


runner = CliRunner()


def test_datasets_uses_remote_adapter(monkeypatch):
    captured = []

    class FakeAdapter:
        def list_available_datasets(self):
            captured.append("datasets")
            return {"success": True, "data": []}

    monkeypatch.setattr(yingyan_cli, "YingyanRemoteAdapter", FakeAdapter)
    result = runner.invoke(yingyan_cli.app, ["datasets"])

    assert result.exit_code == 0
    assert captured == ["datasets"]
    assert '"success": true' in result.stdout


def test_execute_sql_accepts_utf8_file(tmp_path: Path, monkeypatch):
    captured = []
    sql_file = tmp_path / "query.sql"
    sql_file.write_text("  SELECT 类目 FROM t LIMIT 1\n", encoding="utf-8")

    class FakeAdapter:
        def execute_readonly_sql(self, sql):
            captured.append(sql)
            return {"success": True, "data": {"rows": []}}

    monkeypatch.setattr(yingyan_cli, "YingyanRemoteAdapter", FakeAdapter)
    result = runner.invoke(yingyan_cli.app, ["execute-sql", "--sql-file", str(sql_file)])

    assert result.exit_code == 0
    assert captured == ["SELECT 类目 FROM t LIMIT 1"]


def test_execute_sql_requires_exactly_one_source():
    result = runner.invoke(yingyan_cli.app, ["execute-sql"])
    assert result.exit_code != 0
    assert "必须且只能提供 --sql 或 --sql-file" in result.output


def test_search_and_report_commands_map_arguments(monkeypatch):
    calls = []

    class FakeAdapter:
        def search_similar_terms(self, **kwargs):
            calls.append(("search", kwargs))
            return {"success": True, "data": {}}

        def report_task_status(self, task_id):
            calls.append(("status", task_id))
            return {"success": True, "data": {}}

    monkeypatch.setattr(yingyan_cli, "YingyanRemoteAdapter", FakeAdapter)
    search = runner.invoke(
        yingyan_cli.app,
        ["search-similar-terms", "stereo amplifier", "--site", "US", "--top", "8"],
    )
    status = runner.invoke(yingyan_cli.app, ["report-task-status", "task-1"])

    assert search.exit_code == 0
    assert status.exit_code == 0
    assert calls == [
        (
            "search",
            {"search_term": "stereo amplifier", "site": "US", "top": 8},
        ),
        ("status", "task-1"),
    ]
