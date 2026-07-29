"""Collector Monitor 企业微信事故通知适配器。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from opscli.collector_monitor.config import read_protected_text
from opscli.collector_monitor.state import IncidentAction
from opscli.notify.client import send_wecom_markdown

_KIND_TITLE = {
    "opening": "告警",
    "escalation": "升级",
    "reminder": "提醒",
    "recovery": "恢复",
}


class WeComIncidentNotifier:
    """在每次发送时读取 Webhook 文件的失败开放通知器。"""

    def __init__(self, webhook_file: str | Path | None) -> None:
        self._webhook_file = Path(webhook_file) if webhook_file else None

    def __repr__(self) -> str:
        """返回不含配置路径或密钥的调试表示。"""
        return f"{type(self).__name__}(configured={self._webhook_file is not None})"

    def send(self, action: IncidentAction) -> dict[str, Any]:
        """发送开启、提醒或恢复通知，任何异常均转为安全结果。"""
        if self._webhook_file is None:
            return {
                "sent": False,
                "disabled": True,
                "error_class": "NotificationDisabled",
            }
        try:
            webhook = self._read_webhook()
            send_wecom_markdown(webhook, _content(action))
        except Exception as exc:
            return {"sent": False, "error_class": type(exc).__name__}
        return {"sent": True, "error_class": None}

    def _read_webhook(self) -> str:
        """从单行纯文本文件读取 Webhook，但不缓存内容。"""
        if self._webhook_file is None:
            raise RuntimeError("Webhook 未配置")
        content = read_protected_text(self._webhook_file)
        if not content or "\n" in content or "\r" in content:
            raise ValueError("Webhook 文件必须只含一行 URL")
        parsed = urlparse(content)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Webhook 必须是安全 HTTPS URL")
        return content


def _content(action: IncidentAction) -> str:
    """构造不含数据库路径、账号或凭据的安全 Markdown V2 内容。"""
    title = _KIND_TITLE.get(action.kind, "事件")
    rule = _markdown_text(action.rule)
    subject = _markdown_text(action.subject)
    severity = _markdown_text(action.severity)
    message = _markdown_text(action.message)
    state_line = "状态：**已恢复**" if action.kind == "recovery" else f"严重度：**{severity}**"
    return "\n".join(
        [
            f"### Collector Monitor {title}",
            f"> 规则：**{rule}**",
            f"> 对象：`{subject}`",
            f"> {state_line}",
            "",
            message,
        ]
    )


def _markdown_text(value: object) -> str:
    """清理控制字符并转义企业微信 Markdown 动态文本。"""
    normalized = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    normalized = " ".join(normalized.split())
    return re.sub(r"([\\`*_{}\[\]()#+.!>|~])", r"\\\1", normalized)
