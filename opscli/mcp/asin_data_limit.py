"""ASIN MCP 取数并发限流。

该限流只保护本进程内的重型 ASIN 实时取数工具，避免部署到服务端后被多个
AI 客户端同时触发，压垮 BI 接口或 OSS 上传服务。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any


ENV_ASIN_DATA_MCP_MAX_CONCURRENT = "OPSCLI_ASIN_DATA_MCP_MAX_CONCURRENT"
ENV_ASIN_DATA_MCP_QUEUE_TIMEOUT = "OPSCLI_ASIN_DATA_MCP_QUEUE_TIMEOUT"

DEFAULT_MAX_CONCURRENT = 2
DEFAULT_QUEUE_TIMEOUT_SECONDS = 10.0


class AsinDataMcpRateLimitedError(RuntimeError):
    """ASIN MCP 取数超过服务端并发保护阈值。"""

    def to_dict(self) -> dict:
        return {
            "code": "ASIN_DATA_MCP_RATE_LIMITED",
            "message": str(self),
        }


@dataclass
class _LimiterState:
    max_concurrent: int
    semaphore: asyncio.Semaphore
    loop: Any | None


_state: _LimiterState | None = None


def _max_concurrent() -> int:
    return max(_int_env(ENV_ASIN_DATA_MCP_MAX_CONCURRENT, DEFAULT_MAX_CONCURRENT), 1)


def queue_timeout_seconds() -> float:
    return max(_float_env(ENV_ASIN_DATA_MCP_QUEUE_TIMEOUT, DEFAULT_QUEUE_TIMEOUT_SECONDS), 0.1)


def get_limiter_status() -> dict:
    """返回当前 ASIN MCP 限流配置和可用令牌数。"""
    state = _get_state()
    value = getattr(state.semaphore, "_value", None)
    return {
        "max_concurrent": state.max_concurrent,
        "available": value if isinstance(value, int) else None,
        "queue_timeout_seconds": queue_timeout_seconds(),
    }


async def acquire_asin_data_slot() -> asyncio.Semaphore:
    """获取 ASIN 取数并发令牌，超时则抛出限流异常。"""
    state = _get_state()
    timeout = queue_timeout_seconds()
    try:
        await asyncio.wait_for(state.semaphore.acquire(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise AsinDataMcpRateLimitedError(
            f"ASIN 取数服务繁忙，请稍后重试；max_concurrent={state.max_concurrent}，queue_timeout={timeout}s"
        ) from exc
    return state.semaphore


def _get_state() -> _LimiterState:
    global _state
    max_concurrent = _max_concurrent()
    loop = _running_loop_or_none()
    if _state is None or _state.max_concurrent != max_concurrent or _state.loop is not loop:
        _state = _LimiterState(
            max_concurrent=max_concurrent,
            semaphore=asyncio.Semaphore(max_concurrent),
            loop=loop,
        )
    return _state


def _running_loop_or_none() -> Any | None:
    """获取当前事件循环；同步健康检查等场景没有事件循环时返回 None。"""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default
