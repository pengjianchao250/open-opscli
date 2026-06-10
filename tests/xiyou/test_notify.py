import base64
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import respx
from httpx import Response

from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.notify import load_notify_config, notify_token_required


@pytest.fixture
def local_tmp_path():
    path = Path("output") / "test-runs" / f"xiyou-notify-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _jwt(*, seconds: int = 3600) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(seconds=seconds)).timestamp())
    payload = {"exp": exp, "UserId": "u-1"}
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}.signature"


def _b64(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _settings(local_tmp_path: Path) -> XiyouSettings:
    return XiyouSettings(
        credential_path=local_tmp_path / "credential.json",
        notify_path=local_tmp_path / "notify.yaml",
    )


def _write_notify_yaml(path: Path) -> str:
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"
    path.write_text(
        "\n".join(
            [
                "dedupe_minutes: 5",
                "quick_login_url: https://admin.example.com/xiyou/credential",
                "wechat_work:",
                f"  webhook_url: {webhook}",
                "mentions:",
                "  mentioned_list:",
                "    - zhangsan",
                "  mentioned_mobile_list:",
                "    - '13800138000'",
                "  mention_all: true",
            ]
        ),
        encoding="utf-8",
    )
    return webhook


def test_load_notify_config_reads_mentions(local_tmp_path: Path):
    settings = _settings(local_tmp_path)
    _write_notify_yaml(settings.notify_path)

    config = load_notify_config(settings)

    assert config.enabled is True
    assert config.quick_login_url == "https://admin.example.com/xiyou/credential"
    assert config.mentioned_list == ("zhangsan", "@all")
    assert config.mentioned_mobile_list == ("13800138000",)


@respx.mock
def test_notify_token_required_sends_and_dedupes(local_tmp_path: Path):
    settings = XiyouSettings(
        authorization=_jwt(),
        notify_path=local_tmp_path / "notify.yaml",
    )
    webhook = _write_notify_yaml(settings.notify_path)
    route = respx.post(webhook).mock(return_value=Response(200, json={"errcode": 0}))

    first = notify_token_required(
        reason="http_401",
        status_code=401,
        business_code="TokenInvalid",
        job_id="job-1",
        settings=settings,
    )
    second = notify_token_required(
        reason="http_401",
        status_code=401,
        business_code="TokenInvalid",
        job_id="job-1",
        settings=settings,
    )

    assert first["sent"] is True
    assert second["sent"] is False
    assert second["reason"] == "deduped"
    assert route.calls.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body["text"]["mentioned_list"] == ["zhangsan", "@all"]
    assert "TokenInvalid" in body["text"]["content"]
    assert "job-1" in body["text"]["content"]
    assert "当前过期时间" in body["text"]["content"]
    assert "https://admin.example.com/xiyou/credential" in body["text"]["content"]


@respx.mock
def test_notify_token_required_force_skips_dedupe(local_tmp_path: Path):
    settings = _settings(local_tmp_path)
    webhook = _write_notify_yaml(settings.notify_path)
    route = respx.post(webhook).mock(return_value=Response(200, json={"errcode": 0}))

    first = notify_token_required(
        reason="manual_verify",
        status_code=401,
        business_code="TokenInvalid",
        settings=settings,
        force=True,
    )
    second = notify_token_required(
        reason="manual_verify",
        status_code=401,
        business_code="TokenInvalid",
        settings=settings,
        force=True,
    )

    assert first["sent"] is True
    assert second["sent"] is True
    assert route.calls.call_count == 2


@respx.mock
def test_notify_token_required_reports_wecom_errcode(local_tmp_path: Path):
    settings = _settings(local_tmp_path)
    webhook = _write_notify_yaml(settings.notify_path)
    respx.post(webhook).mock(return_value=Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"}))

    result = notify_token_required(
        reason="manual_verify",
        status_code=401,
        business_code="TokenInvalid",
        settings=settings,
        force=True,
    )

    assert result["sent"] is False
    assert result["reason"] == "wecom_error"
    assert result["errcode"] == 93000

