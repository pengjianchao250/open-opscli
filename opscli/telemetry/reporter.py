# opscli/telemetry/reporter.py
"""遥测事件后台上报器。

使用后台守护线程异步发送，主进程立即返回不阻塞用户。
网络失败静默丢弃，绝不影响主流程。

退出等待上限：进程退出时最多等待 _EXIT_WAIT_TIMEOUT 秒让在途发送完成，
超时即强制放行，避免遥测端点缓慢/不可达时长时间卡住命令退出。
"""
from __future__ import annotations

import atexit
import os
import threading
import time
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

# 进程退出时等待在途遥测发送完成的总时长上限（秒）。
# 遥测为 fire-and-forget，正常内网发送通常 <1s；此上限保证即便遥测端点
# 缓慢或不可达，进程退出最多多等这么久便强制放行，不会长时间卡住命令退出。
_EXIT_WAIT_TIMEOUT = 2.0

# 在途发送线程跟踪：退出时据此做"有上限"的 join（区别于 ThreadPoolExecutor
# 内置 atexit 的"无上限" join，后者会被在途 POST 阻塞到 httpx 超时）
_inflight_lock = threading.Lock()
_inflight_threads: set[threading.Thread] = set()


class TelemetryReporter:
    """遥测事件发送器，所有方法均为非阻塞。"""

    @staticmethod
    def fire(**kwargs: Any) -> None:
        """启动后台守护线程发送事件，立即返回。

        Args:
            **kwargs: 事件字段，会被包装进 {"events": [...]} 发送
        """
        # daemon=True：进程退出不会被该线程无限期阻塞；退出时的有限等待
        # 统一交给 _wait_inflight_on_exit 负责，而非依赖线程池的无上限 join
        thread = threading.Thread(target=_do_send, args=(kwargs,), daemon=True)
        with _inflight_lock:
            _inflight_threads.add(thread)
        thread.start()


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
    finally:
        # 发送结束（无论成败）从在途集合移除，避免退出时对已完成线程多余 join
        with _inflight_lock:
            _inflight_threads.discard(threading.current_thread())


def _wait_inflight_on_exit() -> None:
    """进程退出时最多等待 _EXIT_WAIT_TIMEOUT 秒让在途遥测发完，超时即放行。

    逐个 join 在途线程，并以"总截止时间"约束累计等待：一旦达到上限立即 break，
    剩余未完成的发送随进程退出被丢弃（daemon 线程不阻止解释器退出）。
    """
    # 计算总截止时间点，保证多个在途线程的累计等待不超过上限
    deadline = time.monotonic() + _EXIT_WAIT_TIMEOUT
    with _inflight_lock:
        threads = list(_inflight_threads)
    for thread in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # 已达总上限，剩余在途发送不再等待，随进程退出被丢弃
            break
        thread.join(timeout=remaining)


# 注册退出钩子：以有上限的等待替代 ThreadPoolExecutor 内置的无上限 join
atexit.register(_wait_inflight_on_exit)
