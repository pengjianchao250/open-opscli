# opscli/telemetry/reporter.py
"""遥测事件后台上报器。

使用单后台线程异步发送，主进程立即返回不阻塞用户。
网络失败静默丢弃，绝不影响主流程。
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from opscli.config import __version__
from opscli.auth.config import get_ops_url

# 遥测接收端点：ops_url + /v1/cli/telemetry
# 可通过环境变量 OPSCLI_TELEMETRY_URL 覆盖（用于测试或本地开发）
_TELEMETRY_URL: str = os.environ.get(
    "OPSCLI_TELEMETRY_URL",
    f"{get_ops_url()}/v1/cli/telemetry",
)

# 单后台线程：足够满足 fire-and-forget 需求，不浪费连接资源
_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="opscli-telemetry",
)


class TelemetryReporter:
    """遥测事件发送器，所有方法均为非阻塞。"""

    @staticmethod
    def fire(**kwargs: Any) -> None:
        """将事件扔进后台线程池，立即返回。

        Args:
            **kwargs: 事件字段，会被包装进 {"events": [...]} 发送
        """
        _executor.submit(_do_send, kwargs)


def _do_send(payload: dict) -> None:
    """实际发送逻辑，运行在后台线程。

    任何异常均静默丢弃，绝不影响主流程。

    Args:
        payload: 单条事件 dict
    """
    try:
        httpx.post(
            _TELEMETRY_URL,
            json={"events": [payload]},
            headers={"X-Opscli-Version": __version__},
            timeout=5,
        )
    except Exception:
        # 网络不可达、超时、服务器错误等，全部静默丢弃
        pass
