"""Google Trends 正式 CLI 远端调用测试。"""

import json

from typer.testing import CliRunner

from opscli.google_trends import cli as google_trends_cli


runner = CliRunner()


def test_public_google_trends_run_uses_remote_adapter(monkeypatch):
    """正式 google-trends run 应通过远端适配器执行。"""
    captured = {}

    class FakeAdapter:
        """模拟正式 CLI 远端适配器。"""

        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "success": True,
                "data": {"job_id": "public-job"},
                "error": None,
            }

    monkeypatch.setattr(google_trends_cli, "GoogleTrendsRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        google_trends_cli.app,
        [
            "run",
            "interest-over-time",
            "--geo",
            "JP",
            "--params",
            json.dumps({"keyword": "flashlight"}),
            "--export-format",
            "json",
            "--hl",
            "ja-JP",
            "--tz",
            "540",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"] == {
        "scenario": "interest-over-time",
        "geo": "JP",
        "params": {"keyword": "flashlight"},
        "job_id": None,
        "export_format": "json",
        "hl": "ja-JP",
        "tz": 540,
    }
    assert '"job_id": "public-job"' in result.stdout


def test_public_google_trends_queries_use_remote_adapter(monkeypatch):
    """正式查询命令应全部走远端适配器。"""

    class FakeAdapter:
        """模拟正式 CLI 查询接口。"""

        def scenarios(self):
            return {"success": True, "data": [{"id": "interest-over-time"}]}

        def job_status(self, job_id):
            return {"success": True, "data": {"job_id": job_id, "state": "succeeded"}}

        def export(self, job_id):
            return {
                "success": True,
                "data": {
                    "job_id": job_id,
                    "filename": "google-trends-job-1.xlsx",
                },
            }

    monkeypatch.setattr(google_trends_cli, "GoogleTrendsRemoteAdapter", lambda: FakeAdapter())

    scenarios_result = runner.invoke(google_trends_cli.app, ["scenarios"])
    status_result = runner.invoke(google_trends_cli.app, ["job-status", "job-1"])
    export_result = runner.invoke(google_trends_cli.app, ["export", "job-1"])

    assert scenarios_result.exit_code == 0
    assert '"id": "interest-over-time"' in scenarios_result.stdout
    assert status_result.exit_code == 0
    assert '"job_id": "job-1"' in status_result.stdout
    assert export_result.exit_code == 0
    assert '"filename": "google-trends-job-1.xlsx"' in export_result.stdout
