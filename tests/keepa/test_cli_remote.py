"""Keepa 正式 CLI 远端调用测试。"""

import json

from typer.testing import CliRunner

from opscli.keepa import cli as keepa_cli


runner = CliRunner()


def test_public_keepa_run_uses_remote_adapter(monkeypatch):
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

    monkeypatch.setattr(keepa_cli, "KeepaRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        keepa_cli.app,
        [
            "run",
            "product",
            "--site",
            "JP",
            "--params",
            json.dumps({"asin": "B07YRMT36L"}),
            "--export-format",
            "xlsx",
            "--reserve-tokens",
            "12",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"] == {
        "scenario": "product",
        "site": "JP",
        "params": {"asin": "B07YRMT36L"},
        "job_id": None,
        "export_format": "xlsx",
        "reserve_tokens": 12,
        "force": True,
        "wait": False,
    }
    assert '"job_id": "public-job"' in result.stdout


def test_public_keepa_scenarios_job_status_and_export_use_remote_adapter(monkeypatch):
    class FakeAdapter:
        """模拟正式 CLI 的查询接口。"""

        def scenarios(self):
            return {"success": True, "data": [{"id": "product"}]}

        def job_status(self, job_id):
            return {"success": True, "data": {"job_id": job_id, "state": "succeeded"}}

        def export(self, job_id):
            return {
                "success": True,
                "data": {
                    "job_id": job_id,
                    "filename": "keepa-job-1.xlsx",
                    "path": "D:/exports/keepa-job-1.xlsx",
                },
            }

    monkeypatch.setattr(keepa_cli, "KeepaRemoteAdapter", lambda: FakeAdapter())

    scenarios_result = runner.invoke(keepa_cli.app, ["scenarios"])
    status_result = runner.invoke(keepa_cli.app, ["job-status", "job-1"])
    export_result = runner.invoke(keepa_cli.app, ["export", "job-1"])

    assert scenarios_result.exit_code == 0
    assert '"id": "product"' in scenarios_result.stdout
    assert status_result.exit_code == 0
    assert '"job_id": "job-1"' in status_result.stdout
    assert export_result.exit_code == 0
    assert '"filename": "keepa-job-1.xlsx"' in export_result.stdout
