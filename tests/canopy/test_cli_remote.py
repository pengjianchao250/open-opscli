"""Canopy 正式 CLI 远端调用测试。"""

import json

from typer.testing import CliRunner

from opscli.canopy import cli as canopy_cli


runner = CliRunner()


def test_public_canopy_run_uses_remote_adapter(monkeypatch):
    captured = {}

    class FakeAdapter:
        """模拟正式 CLI 远端适配器。"""

        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "success": True,
                "data": {
                    "job_id": "public-job",
                    "request": {
                        "url": "https://rest.canopyapi.co/api/amazon/product",
                    },
                },
                "error": None,
            }

    monkeypatch.setattr(canopy_cli, "CanopyRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        canopy_cli.app,
        [
            "run",
            "product",
            "--domain",
            "JP",
            "--params",
            json.dumps({"asin": "B07YRMT36L"}),
            "--timeout-seconds",
            "45",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"] == {
        "scenario": "product",
        "domain": "JP",
        "params": {"asin": "B07YRMT36L"},
        "job_id": None,
        "export_format": "xls",
        "timeout_seconds": 45,
    }
    assert '"job_id": "public-job"' in result.stdout
    assert "api_key_placeholder_used" not in result.stdout


def test_public_canopy_queries_use_remote_adapter(monkeypatch):
    class FakeAdapter:
        """模拟正式 CLI 的查询接口。"""

        def scenarios(self):
            return {"success": True, "data": [{"scenario_id": "product"}]}

        def job_status(self, job_id):
            return {"success": True, "data": {"job_id": job_id, "state": "succeeded"}}

        def export(self, job_id):
            return {
                "success": True,
                "data": {
                    "job_id": job_id,
                    "filename": "canopy-job-1.xlsx",
                },
            }

    monkeypatch.setattr(canopy_cli, "CanopyRemoteAdapter", lambda: FakeAdapter())

    scenarios_result = runner.invoke(canopy_cli.app, ["scenarios"])
    status_result = runner.invoke(canopy_cli.app, ["job-status", "job-1"])
    export_result = runner.invoke(canopy_cli.app, ["export", "job-1"])

    assert scenarios_result.exit_code == 0
    assert '"scenario_id": "product"' in scenarios_result.stdout
    assert status_result.exit_code == 0
    assert '"job_id": "job-1"' in status_result.stdout
    assert export_result.exit_code == 0
    assert '"filename": "canopy-job-1.xlsx"' in export_result.stdout
