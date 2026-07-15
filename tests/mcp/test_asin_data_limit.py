"""ASIN MCP 取数并发限流测试。"""

import asyncio

import pytest

from opscli.mcp import asin_data_limit


def _run(coro):
    return asyncio.run(coro)


def test_asin_data_limiter_returns_rate_limited_error(monkeypatch):
    monkeypatch.setenv("OPSCLI_ASIN_DATA_MCP_MAX_CONCURRENT", "1")
    monkeypatch.setenv("OPSCLI_ASIN_DATA_MCP_QUEUE_TIMEOUT", "0.01")
    asin_data_limit._state = None

    async def scenario():
        slot = await asin_data_limit.acquire_asin_data_slot()
        try:
            with pytest.raises(asin_data_limit.AsinDataMcpRateLimitedError) as exc:
                await asin_data_limit.acquire_asin_data_slot()
            error = exc.value.to_dict()
            assert error["code"] == "ASIN_DATA_MCP_RATE_LIMITED"
            assert "max_concurrent=1" in error["message"]
        finally:
            slot.release()

    _run(scenario())
    asin_data_limit._state = None


def test_asin_data_limiter_status_uses_env(monkeypatch):
    monkeypatch.setenv("OPSCLI_ASIN_DATA_MCP_MAX_CONCURRENT", "3")
    monkeypatch.setenv("OPSCLI_ASIN_DATA_MCP_QUEUE_TIMEOUT", "2.5")
    asin_data_limit._state = None

    status = asin_data_limit.get_limiter_status()

    assert status["max_concurrent"] == 3
    assert status["available"] == 3
    assert status["queue_timeout_seconds"] == 2.5
    asin_data_limit._state = None
