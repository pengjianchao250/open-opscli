import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

import opscli.xiyou.cli as cli_module
from opscli.xiyou.cli import app
from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential


runner = CliRunner()


@pytest.fixture
def local_tmp_path():
    path = Path("output") / "test-runs" / f"xiyou-cli-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_notify_status_hides_webhook(monkeypatch, local_tmp_path: Path):
    notify_path = local_tmp_path / "notify.yaml"
    notify_path.write_text(
        "\n".join(
            [
                "dedupe_minutes: 5",
                "quick_login_url: https://admin.example.com/xiyou/credential",
                "wechat_work:",
                "  webhook_url: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret",
                "mentions:",
                "  mentioned_mobile_list:",
                "    - '13800138000'",
            ]
        ),
        encoding="utf-8",
    )
    settings = XiyouSettings(
        notify_path=notify_path,
    )
    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)

    result = runner.invoke(app, ["notify", "status"])

    assert result.exit_code == 0
    assert "key=secret" not in result.output
    payload = json.loads(result.output)
    assert payload["enabled"] is True
    assert payload["has_webhook_url"] is True
    assert payload["mentioned_mobile_list"] == ["13800138000"]


def test_notify_test_prints_send_result(monkeypatch):
    monkeypatch.setattr(
        cli_module,
        "notify_token_required",
        lambda **kwargs: {"sent": True, "job_id": kwargs["job_id"], "force": kwargs["force"]},
    )

    result = runner.invoke(app, ["notify", "test", "--job-id", "verify-1"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {"sent": True, "job_id": "verify-1", "force": True}


def test_credential_status_marks_default_latest_url(monkeypatch):
    settings = XiyouSettings(
        authorization="header.payload.signature",
        credential_latest_url="https://ops.api.qa.aukeyit.com/api/v1/mcp-accounts?platform=xiyou",
    )
    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli_module.XiyouCredentialProvider,
        "get_default",
        lambda self: XiyouCredential(
            authorization="header.payload.signature",
            source="credential_service",
        ),
    )

    result = runner.invoke(app, ["credential", "status"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["has_credential_latest_url"] is True
