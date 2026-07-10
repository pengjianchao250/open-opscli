import json

from typer.testing import CliRunner

from opscli.cli import app
from opscli.seller_sprite import cli as seller_sprite_cli
from opscli.seller_sprite_debug import cli as seller_sprite_debug_cli

runner = CliRunner()


def test_public_seller_sprite_help_shows_remote_commands_only():
    result = runner.invoke(app, ["seller-sprite", "--help"])
    assert result.exit_code == 0
    assert "job-status" in result.stdout
    assert "export" in result.stdout
    assert "--mode" not in result.stdout


def test_debug_seller_sprite_help_keeps_local_debug_options():
    result = runner.invoke(app, ["seller-sprite-debug", "--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout

    run_help = runner.invoke(app, ["seller-sprite-debug", "run", "--help"])
    assert run_help.exit_code == 0
    assert "--mode" in run_help.stdout


def test_public_seller_sprite_run_help_hides_local_only_options():
    result = runner.invoke(app, ["seller-sprite", "run", "--help"])
    assert result.exit_code == 0
    assert "--mode" not in result.stdout
    assert "--page-prepare" not in result.stdout
    assert "--task-interval-seconds" not in result.stdout
    assert "--cooldown-seconds" not in result.stdout


def test_public_seller_sprite_run_rejects_local_only_options():
    result = runner.invoke(
        app,
        [
            "seller-sprite",
            "run",
            "keyword-reverse",
            "--mode",
            "api-direct",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output


def test_debug_seller_sprite_run_keeps_local_execution_path(monkeypatch):
    captured = {}

    class FakeResult:
        def to_dict(self):
            return {"job_id": "debug-job", "mode": "api-direct"}

    class FakeManager:
        def scenarios(self):
            return []

        async def run(self, request):
            captured["request"] = request
            return FakeResult()

    monkeypatch.setattr(seller_sprite_debug_cli, "SellerSpriteApiManager", lambda: FakeManager())

    result = runner.invoke(
        app,
        [
            "seller-sprite-debug",
            "run",
            "keyword-reverse",
            "--params",
            json.dumps({"asin": "B07YRMT36L"}),
            "--mode",
            "api-direct",
        ],
    )

    assert result.exit_code == 0
    assert captured["request"].scenario == "keyword-reverse"
    assert captured["request"].params == {"asin": "B07YRMT36L"}
    assert captured["request"].mode == "api-direct"
    assert '"job_id": "debug-job"' in result.stdout


def test_public_seller_sprite_run_uses_public_contract_without_local_flags(monkeypatch):
    captured = {}

    class FakeAdapter:
        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "success": True,
                "data": {"job_id": "public-job"},
                "error": None,
            }

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        app,
        [
            "seller-sprite",
            "run",
            "keyword-reverse",
            "--site",
            "JP",
            "--period",
            "nearly",
            "--params",
            json.dumps({"asin": "B07YRMT36L"}),
            "--export-format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"]["scenario"] == "keyword-reverse"
    assert captured["kwargs"]["site"] == "JP"
    assert captured["kwargs"]["period"] == "nearly"
    assert captured["kwargs"]["params"] == {"asin": "B07YRMT36L"}
    assert captured["kwargs"]["page_size"] == 100
    assert captured["kwargs"]["export_format"] == "json"
    assert captured["kwargs"]["job_id"] is None
    assert '"job_id": "public-job"' in result.stdout


def test_public_seller_sprite_listing_analysis_commands_use_remote_adapter(monkeypatch):
    captured = {}

    class FakeAdapter:
        def listing_analysis_submit(self, **kwargs):
            captured["submit"] = kwargs
            return {"success": True, "data": {"job_id": "listing-job-1"}}

        def listing_analysis_status(self, job_id):
            captured["status"] = job_id
            return {"success": True, "data": {"job_id": job_id, "ready": False}}

        def listing_analysis_result(self, job_id, *, export_format):
            captured["result"] = {"job_id": job_id, "export_format": export_format}
            return {"success": True, "data": {"job_id": job_id, "ready": True}}

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    submit = runner.invoke(
        app,
        [
            "seller-sprite",
            "listing-analysis-submit",
            "--asin",
            "B0TEST123",
            "--station",
            "GLOBAL",
            "--site",
            "US",
        ],
    )
    status = runner.invoke(app, ["seller-sprite", "listing-analysis-status", "listing-job-1"])
    result = runner.invoke(
        app,
        [
            "seller-sprite",
            "listing-analysis-result",
            "listing-job-1",
            "--export-format",
            "json",
        ],
    )

    assert submit.exit_code == 0
    assert status.exit_code == 0
    assert result.exit_code == 0
    assert captured["submit"]["asin"] == "B0TEST123"
    assert captured["status"] == "listing-job-1"
    assert captured["result"] == {"job_id": "listing-job-1", "export_format": "json"}



def test_public_seller_sprite_job_status_and_export_use_remote_adapter(monkeypatch):
    class FakeAdapter:
        def job_status(self, job_id):
            return {"success": True, "data": {"job_id": job_id, "state": "succeeded"}}

        def export(self, job_id):
            return {
                "success": True,
                "data": {
                    "path": "D:/tmp/export.json",
                    "filename": "export.json",
                    "format": "json",
                },
            }

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    status_result = runner.invoke(app, ["seller-sprite", "job-status", "job-1"])
    export_result = runner.invoke(app, ["seller-sprite", "export", "job-1"])

    assert status_result.exit_code == 0
    assert '"job_id": "job-1"' in status_result.stdout
    assert export_result.exit_code == 0
    assert '"filename": "export.json"' in export_result.stdout
