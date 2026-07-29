"""企业微信等通知渠道的 HTTP 客户端。"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx


# 企业微信机器人只允许向官方固定地址发送，避免 Webhook 凭据外发。
WECOM_WEBHOOK_HOST = "qyapi.weixin.qq.com"
WECOM_WEBHOOK_PATH = "/cgi-bin/webhook/send"
WECOM_TIMEOUT = 5.0
# 企业微信 markdown_v2.content 官方上限为 4096 字节。
WECOM_CONTENT_BYTES = 4096


class NotifyError(Exception):
    """表示通知配置、网络或远端业务执行失败。"""


def _validate_wecom_webhook(webhook: str) -> None:
    """校验企业微信群机器人 Webhook。"""
    parsed = urlparse(webhook)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != WECOM_WEBHOOK_HOST
        or parsed.port is not None
        or parsed.path != WECOM_WEBHOOK_PATH
        or parsed.username
        or parsed.password
        or parsed.fragment
        or set(query) != {"key"}
        or len(query["key"]) != 1
        or not query["key"][0]
    ):
        raise NotifyError("企业微信机器人 Webhook 地址无效")


def send_wecom_markdown(webhook: str, content: str) -> dict[str, bool]:
    """向企业微信群机器人发送 Markdown V2 内容。

    Args:
        webhook: 企业微信群机器人官方 Webhook。
        content: 已脱敏的 Markdown V2 内容。

    Returns:
        包含发送结果的字典。

    Raises:
        NotifyError: 地址、内容、网络、HTTP 或业务码异常。
    """
    _validate_wecom_webhook(webhook)
    if not content.strip():
        raise NotifyError("企业微信 Markdown V2 内容不能为空")
    if len(content.encode("utf-8")) > WECOM_CONTENT_BYTES:
        raise NotifyError(f"企业微信 Markdown V2 内容不能超过 {WECOM_CONTENT_BYTES} 字节")

    try:
        response = httpx.post(
            webhook,
            json={"msgtype": "markdown_v2", "markdown_v2": {"content": content}},
            timeout=WECOM_TIMEOUT,
        )
    except Exception as exc:
        # 不拼接原始异常，避免 httpx 异常中的请求 URL 泄露 Webhook Key。
        raise NotifyError("企业微信机器人网络请求失败") from exc

    if response.status_code >= 400:
        raise NotifyError(f"企业微信机器人请求失败: HTTP {response.status_code}")
    try:
        body: Any = response.json()
    except Exception as exc:
        raise NotifyError("企业微信机器人返回了无法解析的 JSON") from exc
    if not isinstance(body, dict):
        raise NotifyError("企业微信机器人返回结构不是 JSON 对象")
    errcode = body.get("errcode")
    if errcode != 0:
        # 不输出远端 errmsg，避免上游意外回显 Webhook 或其他敏感内容。
        raise NotifyError(f"企业微信机器人业务执行失败: errcode={errcode}")
    return {"sent": True}
