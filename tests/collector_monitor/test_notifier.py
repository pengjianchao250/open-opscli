"""企业微信事故通知器安全契约测试。"""

from __future__ import annotations

from pathlib import Path

from opscli.collector_monitor.notifier import WeComIncidentNotifier
from opscli.collector_monitor.state import IncidentAction

ACTION = IncidentAction("opening", "stalled", "job-1", "high", "任务没有进度")


def test_notifier_reads_webhook_at_send_time_without_persisting_secret(
    tmp_path: Path, monkeypatch
) -> None:
    """Webhook 只能在发送时从受保护文件读取，实例和结果不得包含密钥。"""
    webhook_file = tmp_path / "webhook.txt"
    fake_webhook = "https://example.invalid/wecom-webhook"
    webhook_file.write_text(fake_webhook, encoding="utf-8")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "opscli.collector_monitor.notifier.send_wecom_markdown",
        lambda webhook, content: sent.append((webhook, content)) or {"sent": True},
    )
    notifier = WeComIncidentNotifier(webhook_file)

    result = notifier.send(ACTION)

    assert result == {"sent": True, "error_class": None}
    assert sent[0][0] == fake_webhook
    assert "Collector Monitor 告警" in sent[0][1]
    assert "job-1" in sent[0][1]
    assert fake_webhook not in repr(notifier)
    assert fake_webhook not in repr(result)


def test_notifier_is_fail_open_and_sanitizes_error_class(tmp_path: Path, monkeypatch) -> None:
    """通知失败应返回安全错误类，不能中断监控或回显原始异常。"""
    webhook_file = tmp_path / "webhook.txt"
    webhook_file.write_text(
        "https://example.invalid/wecom-webhook",
        encoding="utf-8",
    )

    class SecretNetworkError(RuntimeError):
        pass

    monkeypatch.setattr(
        "opscli.collector_monitor.notifier.send_wecom_markdown",
        lambda *_: (_ for _ in ()).throw(SecretNetworkError("key=secret")),
    )

    result = WeComIncidentNotifier(webhook_file).send(ACTION)

    assert result == {"sent": False, "error_class": "SecretNetworkError"}
    assert "secret" not in repr(result)


def test_notifier_escapes_dynamic_markdown_and_control_characters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """任务标识和消息不得通过换行或 Markdown 伪造告警结构。"""
    webhook_file = tmp_path / "webhook.txt"
    webhook_file.write_text(
        "https://example.invalid/wecom-webhook",
        encoding="utf-8",
    )
    sent: list[str] = []
    monkeypatch.setattr(
        "opscli.collector_monitor.notifier.send_wecom_markdown",
        lambda _webhook, content: sent.append(content),
    )
    malicious = IncidentAction(
        "opening",
        "stalled\n### forged-rule",
        "job`\r\n> forged-subject",
        "high**",
        "任务异常\n### forged-message",
    )

    assert WeComIncidentNotifier(webhook_file).send(malicious)["sent"] is True
    content = sent[0]
    assert "\n### forged" not in content
    assert "\\`" in content
    assert "\\#\\#\\# forged-message" in content
    assert "\\> forged-subject" in content


def test_notifier_without_configuration_is_disabled() -> None:
    """未配置 Webhook 时应返回可持久化的终态跳过结果。"""
    result = WeComIncidentNotifier(None).send(ACTION)

    assert result == {
        "sent": False,
        "disabled": True,
        "error_class": "NotificationDisabled",
    }
