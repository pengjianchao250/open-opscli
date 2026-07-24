# tests/telemetry/test_reporter.py
"""TelemetryReporter 单元测试。"""

import time

import pytest


def test_fire_sends_event_to_correct_url(monkeypatch):
    """fire() 应向 TELEMETRY_URL 发送包含事件的 POST 请求。"""
    import opscli.telemetry.reporter as reporter

    sent = []

    def fake_post(url, *, json, headers, timeout):
        sent.append({"url": url, "body": json})

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr(reporter, "_TELEMETRY_URL", "http://fake/api/v1/cli/telemetry")

    reporter.TelemetryReporter.fire(command="query run", status="success")

    # 后台线程异步执行，等待最多 1 秒
    deadline = time.time() + 1.0
    while not sent and time.time() < deadline:
        time.sleep(0.05)

    assert len(sent) == 1
    assert sent[0]["url"] == "http://fake/api/v1/cli/telemetry"
    assert sent[0]["body"]["events"][0]["command"] == "query run"


def test_fire_is_nonblocking(monkeypatch):
    """fire() 应立即返回，不等待网络请求完成。"""
    import opscli.telemetry.reporter as reporter

    # 使用 threading.Event 让 post 在 fire() 返回后才真正阻塞，
    # 而不是 sleep(10)，避免占用线程池唯一的 worker
    import threading
    block_event = threading.Event()

    def blocking_post(url, *, json, headers, timeout):
        block_event.wait(timeout=2)  # 短暂等待后释放

    monkeypatch.setattr("httpx.post", blocking_post)

    start = time.monotonic()
    reporter.TelemetryReporter.fire(command="auth login", status="success")
    elapsed = time.monotonic() - start

    # fire() 应在 100ms 内返回（后台线程还在等待 event）
    assert elapsed < 0.1

    # 释放后台线程，不污染后续测试
    block_event.set()
    time.sleep(0.1)


def test_fire_silently_ignores_network_error(monkeypatch):
    """网络请求失败时 fire() 不应抛出异常。"""
    import httpx
    import opscli.telemetry.reporter as reporter

    def fail_post(url, *, json, headers, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.post", fail_post)

    # 不应抛出任何异常
    reporter.TelemetryReporter.fire(command="amazon scrape", status="error")
    time.sleep(0.1)  # 等后台线程执行完


def test_exit_wait_is_bounded(monkeypatch):
    """在途遥测发送长时间阻塞时，退出等待不超过 _EXIT_WAIT_TIMEOUT 上限。"""
    import threading

    import opscli.telemetry.reporter as reporter

    release = threading.Event()

    def blocking_post(url, *, json, headers, timeout):
        # 模拟长时间阻塞的发送（远超退出等待上限）
        release.wait(timeout=10)

    monkeypatch.setattr("httpx.post", blocking_post)
    # 缩短退出等待上限以加速测试
    monkeypatch.setattr(reporter, "_EXIT_WAIT_TIMEOUT", 0.3)

    reporter.TelemetryReporter.fire(command="query run", status="success")

    start = time.monotonic()
    reporter._wait_inflight_on_exit()
    elapsed = time.monotonic() - start

    # 释放后台线程，避免污染后续测试
    release.set()
    time.sleep(0.05)

    # 应在 ~0.3s 达到上限后放行，远小于 post 的 10s 阻塞
    assert elapsed < 1.0
    # 确实等待到了上限附近（下限留出调度余量）
    assert elapsed >= 0.25


def test_fire_wraps_payload_in_events_array(monkeypatch):
    """fire() 发送的 payload 应将事件包装在 events 数组中。"""
    import opscli.telemetry.reporter as reporter

    received = []

    def capture_post(url, *, json, headers, timeout):
        received.append(json)

    monkeypatch.setattr("httpx.post", capture_post)
    monkeypatch.setattr(reporter, "_TELEMETRY_URL", "http://fake/api/v1/cli/telemetry")

    reporter.TelemetryReporter.fire(command="skills list", status="success", duration_ms=50)

    # 后台线程异步执行，等待最多 1 秒
    deadline = time.time() + 1.0
    while not received and time.time() < deadline:
        time.sleep(0.05)

    assert "events" in received[0]
    assert isinstance(received[0]["events"], list)
    assert received[0]["events"][0]["duration_ms"] == 50
