"""Scrape.do 正式 CLI 远端调用测试。"""

import json

from typer.testing import CliRunner

from opscli.scrape_do import cli as scrape_do_cli

runner = CliRunner()


def test_public_scrape_do_run_uses_remote_adapter(monkeypatch):
    captured = {}

    class FakeAdapter:
        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"success": True, "data": {"job_id": "public-job"}, "error": None}

    monkeypatch.setattr(scrape_do_cli, "ScrapeDoRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        scrape_do_cli.app,
        [
            "run",
            "amazon-pdp",
            "--site",
            "JP",
            "--params",
            json.dumps({"asin": "B07YRMT36L"}),
            "--export-format",
            "xlsx",
            "--timeout-seconds",
            "45",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"] == {
        "scenario": "amazon-pdp",
        "site": "JP",
        "params": {"asin": "B07YRMT36L"},
        "job_id": None,
        "export_format": "xlsx",
        "timeout_seconds": 45,
    }
    assert '"job_id": "public-job"' in result.stdout


def test_public_scrape_do_queries_use_remote_adapter(monkeypatch):
    class FakeAdapter:
        def scenarios(self):
            return {"success": True, "data": [{"scenario_id": "amazon-pdp"}]}

        def job_status(self, job_id):
            return {"success": True, "data": {"job_id": job_id, "state": "succeeded"}}

        def export(self, job_id):
            return {"success": True, "data": {"job_id": job_id, "filename": "scrape-do-job-1.xlsx"}}

    monkeypatch.setattr(scrape_do_cli, "ScrapeDoRemoteAdapter", lambda: FakeAdapter())

    scenarios_result = runner.invoke(scrape_do_cli.app, ["scenarios"])
    status_result = runner.invoke(scrape_do_cli.app, ["job-status", "job-1"])
    export_result = runner.invoke(scrape_do_cli.app, ["export", "job-1"])

    assert scenarios_result.exit_code == 0
    assert '"scenario_id": "amazon-pdp"' in scenarios_result.stdout
    assert status_result.exit_code == 0
    assert '"job_id": "job-1"' in status_result.stdout
    assert export_result.exit_code == 0
    assert '"filename": "scrape-do-job-1.xlsx"' in export_result.stdout
