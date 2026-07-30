"""通用通知 CLI 契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import opscli.notify.client as client_module
from opscli.notify.cli import app


runner = CliRunner()


def _write_inputs(tmp_path: Path, webhook: str) -> tuple[Path, Path]:
    """写入测试凭据和 Markdown 内容文件。"""
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"wecom_webhook_url": webhook}), encoding="utf-8")
    content = tmp_path / "summary.md"
    content.write_text("### 反馈日报\n> 问题反馈：**3**", encoding="utf-8")
    return credentials, content


def _response(payload: object, status_code: int = 200) -> httpx.Response:
    """构造带请求上下文的企业微信响应。"""
    request = httpx.Request("POST", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    return httpx.Response(status_code, json=payload, request=request)


def test_wecom_markdown_command_reads_files_and_sends_payload(tmp_path: Path, monkeypatch):
    """命令应从本地文件读取 Webhook 和 Markdown，不把凭据放入参数。"""
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=local-secret"
    credentials, content = _write_inputs(tmp_path, webhook)
    sent: dict = {}

    def fake_post(url: str, **kwargs):
        sent.update(url=url, **kwargs)
        return _response({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr(client_module.httpx, "post", fake_post)

    result = runner.invoke(
        app,
        [
            "wecom-markdown",
            "--credentials-file",
            str(credentials),
            "--content-file",
            str(content),
        ],
    )
    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert sent["url"] == webhook
    assert sent["timeout"] == 5.0
    assert sent["json"] == {
        "msgtype": "markdown_v2",
        "markdown_v2": {"content": "### 反馈日报\n> 问题反馈：**3**"},
    }
    assert payload["success"] is True
    assert payload["data"] == {"sent": True}
    assert webhook not in result.output
    assert "local-secret" not in result.output


def test_wecom_markdown_v2_allows_4096_bytes_and_rejects_larger_content(monkeypatch):
    """Markdown V2 内容必须遵循官方 4096 字节上限。"""
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=local-secret"
    calls: list[dict] = []

    def fake_post(url: str, **kwargs):
        calls.append(kwargs["json"])
        return _response({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr(client_module.httpx, "post", fake_post)

    assert client_module.send_wecom_markdown(webhook, "a" * 4096) == {"sent": True}
    assert calls[0]["msgtype"] == "markdown_v2"
    with pytest.raises(client_module.NotifyError, match="4096 字节"):
        client_module.send_wecom_markdown(webhook, "a" * 4097)


def test_wecom_markdown_command_rejects_untrusted_webhook_without_leak(tmp_path: Path):
    """非官方地址必须在 HTTP 请求前拒绝，且输出不得回显地址。"""
    webhook = "https://attacker.example/cgi-bin/webhook/send?key=must-not-leak"
    credentials, content = _write_inputs(tmp_path, webhook)

    result = runner.invoke(
        app,
        [
            "wecom-markdown",
            "--credentials-file",
            str(credentials),
            "--content-file",
            str(content),
        ],
    )

    assert result.exit_code == 1
    assert "企业微信机器人 Webhook 地址无效" in result.output
    assert webhook not in result.output
    assert "must-not-leak" not in result.output


def test_wecom_markdown_command_reports_business_error_without_leak(tmp_path: Path, monkeypatch):
    """企业微信业务码失败应返回安全错误，不输出 Webhook 或响应正文。"""
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=must-not-leak"
    credentials, content = _write_inputs(tmp_path, webhook)
    monkeypatch.setattr(
        client_module.httpx,
        "post",
        lambda *args, **kwargs: _response({"errcode": 93000, "errmsg": webhook}),
    )

    result = runner.invoke(
        app,
        [
            "wecom-markdown",
            "--credentials-file",
            str(credentials),
            "--content-file",
            str(content),
        ],
    )

    assert result.exit_code == 1
    assert "errcode=93000" in result.output
    assert webhook not in result.output
    assert "must-not-leak" not in result.output
