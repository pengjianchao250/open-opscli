"""Skill 使用次数上报模块。

每次调用 Skill 后通过 record() 直接上报到服务端，不经过本地队列。
保留 _get_client_id() 供 CLI 命令 report-usage 使用。
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import time
from pathlib import Path

_logger = logging.getLogger("opscli.skills.marketplace.usage_reporter")

_CLIENT_ID_FILE = Path.home() / ".opscli" / "client_id"


def _get_client_id() -> str:
    """获取或生成本机唯一客户端 ID，持久化到 ~/.opscli/client_id。"""
    try:
        if _CLIENT_ID_FILE.exists():
            return _CLIENT_ID_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    raw = f"{socket.gethostname()}-{os.getpid()}-{time.time()}"
    client_id = hashlib.sha1(raw.encode()).hexdigest()[:16]
    try:
        _CLIENT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CLIENT_ID_FILE.write_text(client_id, encoding="utf-8")
    except Exception:
        pass
    return client_id


class UsageReporter:
    """Skill 使用上报器（直接上报模式，不使用本地队列）。"""

    def record(self, identifier: str, client_id: str | None = None) -> None:
        """上报一次技能调用，直接发送到服务端。

        Args:
            identifier: Skill 标识符，如 pengjianchao@ops-auth
            client_id:  客户端机器 ID，可选
        """
        from datetime import datetime, timezone

        record = {
            "identifier": identifier,
            "used_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "client_id": client_id or _get_client_id(),
        }
        try:
            from opscli.skills.marketplace.client import MarketplaceClient
            MarketplaceClient().batch_usage([record])
            _logger.debug("使用上报成功: %s", identifier)
        except Exception as exc:
            _logger.warning("使用上报失败: %s — %s", identifier, exc)


# 全局单例
_reporter = UsageReporter()


def get_reporter() -> UsageReporter:
    return _reporter
