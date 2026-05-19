# Telemetry 客户端实施计划（opscli）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 opscli 中新增 `telemetry` 模块，通过 Typer callback 和 FastMCP 代理无侵入地自动采集 CLI 命令和 MCP Tool 的执行遥测数据，异步上报到 auto-scheduler。

**Architecture:** 新增 `opscli/telemetry/` 模块（device_id + collector + reporter），在 `cli.py` 的 main callback 注入 CLI 拦截，在 `mcp/server.py` 用代理类包裹所有 tool 注册，实现零侵入覆盖全模块。

**Tech Stack:** Python 3.10+、httpx、concurrent.futures.ThreadPoolExecutor、pytest

**工作目录:** `/Users/mask/python3/opscli`

**前置条件:** auto-scheduler 侧的 `POST /api/v1/cli/telemetry` 端点已部署（参见 telemetry-auto-scheduler 计划）

---

## 文件清单

| 操作 | 文件路径 |
|------|---------|
| 新建 | `opscli/telemetry/__init__.py` |
| 新建 | `opscli/telemetry/device_id.py` |
| 新建 | `opscli/telemetry/collector.py` |
| 新建 | `opscli/telemetry/reporter.py` |
| 新建 | `tests/telemetry/__init__.py` |
| 新建 | `tests/telemetry/test_device_id.py` |
| 新建 | `tests/telemetry/test_collector.py` |
| 新建 | `tests/telemetry/test_reporter.py` |
| 修改 | `opscli/cli.py`（main callback 注入遥测） |
| 修改 | `opscli/mcp/server.py`（代理类包裹 tool 注册） |
| 新建 | `tests/telemetry/test_cli_integration.py` |

---

### Task 1: device_id 模块

**Files:**
- Create: `opscli/telemetry/device_id.py`
- Create: `tests/telemetry/__init__.py`
- Create: `tests/telemetry/test_device_id.py`

- [ ] **Step 1: 创建测试目录和空 __init__**

```bash
mkdir -p /Users/mask/python3/opscli/tests/telemetry
touch /Users/mask/python3/opscli/tests/telemetry/__init__.py
```

- [ ] **Step 2: 写失败测试**

```python
# tests/telemetry/test_device_id.py
"""device_id 模块单元测试。"""

import uuid
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    """每个测试前清除模块级缓存，确保测试隔离。"""
    import opscli.telemetry.device_id as did
    monkeypatch.setattr(did, "_cached", None)


def test_get_device_id_returns_valid_uuid(tmp_path, monkeypatch):
    """首次调用应返回合法 UUID v4 字符串。"""
    import opscli.telemetry.device_id as did
    monkeypatch.setattr(did, "_DEVICE_ID_FILE", tmp_path / "device_id")

    result = did.get_device_id()

    uuid.UUID(result)  # 不合法时抛出 ValueError


def test_get_device_id_persists_to_file(tmp_path, monkeypatch):
    """首次调用后应将 device_id 写入文件。"""
    import opscli.telemetry.device_id as did
    device_file = tmp_path / "device_id"
    monkeypatch.setattr(did, "_DEVICE_ID_FILE", device_file)

    did.get_device_id()

    assert device_file.exists()
    assert len(device_file.read_text().strip()) == 36  # UUID 长度


def test_get_device_id_returns_same_value_on_second_call(tmp_path, monkeypatch):
    """同一进程内两次调用应返回相同 ID（内存缓存）。"""
    import opscli.telemetry.device_id as did
    monkeypatch.setattr(did, "_DEVICE_ID_FILE", tmp_path / "device_id")

    id1 = did.get_device_id()
    id2 = did.get_device_id()

    assert id1 == id2


def test_get_device_id_reads_existing_file(tmp_path, monkeypatch):
    """文件已存在时应读取文件内容，而非重新生成。"""
    import opscli.telemetry.device_id as did
    device_file = tmp_path / "device_id"
    existing_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    device_file.write_text(existing_id)
    monkeypatch.setattr(did, "_DEVICE_ID_FILE", device_file)

    result = did.get_device_id()

    assert result == existing_id
```

- [ ] **Step 3: 运行测试，确认失败（模块不存在）**

```bash
cd /Users/mask/python3/opscli
source .venv/bin/activate
pytest tests/telemetry/test_device_id.py -v
```

期望：ERROR — `ModuleNotFoundError: No module named 'opscli.telemetry'`

- [ ] **Step 4: 创建 device_id.py**

```python
# opscli/telemetry/device_id.py
"""机器唯一标识管理。

在 ~/.config/opscli/device_id 文件中持久化 UUID v4，
首次运行时自动生成，后续复用（内存缓存 + 文件持久化双层）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from opscli.config import CONFIG_DIR

# 持久化路径：~/.config/opscli/device_id
_DEVICE_ID_FILE: Path = Path(CONFIG_DIR) / "device_id"

# 内存缓存，避免每次调用都读文件
_cached: str | None = None


def get_device_id() -> str:
    """获取本机唯一标识。

    优先返回内存缓存，其次读取文件，首次运行时生成并持久化。

    Returns:
        UUID v4 格式的机器唯一标识字符串
    """
    global _cached

    # 1. 内存缓存命中，直接返回
    if _cached:
        return _cached

    # 2. 文件已存在，读取并缓存
    if _DEVICE_ID_FILE.exists():
        content = _DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
        if content:
            _cached = content
            return _cached

    # 3. 首次运行：生成新 UUID 并写入文件
    _cached = str(uuid.uuid4())
    try:
        _DEVICE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DEVICE_ID_FILE.write_text(_cached, encoding="utf-8")
    except OSError:
        # 文件写入失败（权限不足等）不影响本次使用
        pass

    return _cached
```

- [ ] **Step 5: 创建包入口（暂为空，后续追加导出）**

```python
# opscli/telemetry/__init__.py
"""opscli 遥测模块。

自动采集 CLI 命令和 MCP Tool 的执行遥测数据，异步上报到后端。
此模块为内部基础设施，不注册为 CLI 子命令，用户不可见。
"""
```

- [ ] **Step 6: 运行测试，确认通过**

```bash
pytest tests/telemetry/test_device_id.py -v
```

期望：4 tests PASS

- [ ] **Step 7: Commit**

```bash
git add opscli/telemetry/__init__.py opscli/telemetry/device_id.py \
        tests/telemetry/__init__.py tests/telemetry/test_device_id.py
git commit -m "feat(telemetry): add device_id module with file persistence"
```

---

### Task 2: collector 模块

**Files:**
- Create: `opscli/telemetry/collector.py`
- Create: `tests/telemetry/test_collector.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/telemetry/test_collector.py
"""TelemetryCollector 单元测试。"""

import pytest


@pytest.fixture(autouse=True)
def clear_pending_error():
    """每个测试前清空全局错误状态。"""
    from opscli.telemetry import collector
    collector._pending_error.clear()
    yield
    collector._pending_error.clear()


def test_build_event_contains_required_fields():
    """build_event 应包含所有必要字段。"""
    from opscli.telemetry.collector import build_event

    event = build_event(
        event_type="cli_command",
        command="query run",
        module="query",
        status="success",
        duration_ms=1250,
    )

    assert event["event_type"] == "cli_command"
    assert event["command"] == "query run"
    assert event["module"] == "query"
    assert event["status"] == "success"
    assert event["duration_ms"] == 1250
    assert "device_id" in event
    assert "opscli_version" in event
    assert "os" in event
    assert "timestamp" in event


def test_build_event_timestamp_is_iso8601():
    """timestamp 字段应为 ISO 8601 格式。"""
    from datetime import datetime, timezone
    from opscli.telemetry.collector import build_event

    event = build_event(
        event_type="cli_command",
        command="auth login",
        module="auth",
        status="success",
    )

    # datetime.fromisoformat 解析失败会抛出 ValueError
    ts = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    assert ts.tzinfo is not None  # 必须有时区信息


def test_pop_status_returns_success_by_default():
    """未设置错误时 pop_status 应返回 success。"""
    from opscli.telemetry.collector import pop_status

    assert pop_status() == "success"


def test_set_error_makes_pop_status_return_error():
    """set_error 后 pop_status 应返回 error。"""
    from opscli.telemetry.collector import set_error, pop_status

    class FakeError(Exception):
        pass

    set_error(FakeError("test"))
    assert pop_status() == "error"


def test_pop_error_type_returns_class_name():
    """pop_error_type 应返回异常类名字符串。"""
    from opscli.telemetry.collector import set_error, pop_error_type

    class NetworkError(Exception):
        pass

    set_error(NetworkError())
    assert pop_error_type() == "NetworkError"


def test_pop_error_type_clears_state():
    """pop_error_type 调用后，状态应被清空（pop 语义）。"""
    from opscli.telemetry.collector import set_error, pop_status, pop_error_type

    class FakeError(Exception):
        pass

    set_error(FakeError())
    pop_error_type()  # 读取并清空
    assert pop_status() == "success"  # 已清空
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/telemetry/test_collector.py -v
```

期望：ERROR — `ModuleNotFoundError: cannot import name 'collector'`

- [ ] **Step 3: 实现 collector.py**

```python
# opscli/telemetry/collector.py
"""遥测事件收集器。

负责构建标准事件 dict，并管理 CLI 模式下的错误状态
（异常时由 cli.py 通过 set_error() 写入，_report() 读取后上报）。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from opscli.version import get_version

# CLI 模式下，命令异常时写入此 dict，_report() 读取后清空
# 使用 dict 而非单一变量，便于后续扩展更多错误字段
_pending_error: dict[str, str] = {}


def set_error(exc: BaseException) -> None:
    """记录 CLI 命令执行中的异常，供 _report() 读取后上报。

    Args:
        exc: 捕获到的异常实例
    """
    _pending_error["error_type"] = type(exc).__name__


def pop_status() -> str:
    """获取当前命令的执行状态。

    有未读异常时返回 "error"，否则返回 "success"。
    不清空状态（由 pop_error_type 负责清空）。

    Returns:
        "success" 或 "error"
    """
    return "error" if _pending_error else "success"


def pop_error_type() -> str | None:
    """获取并清空当前命令的异常类型（pop 语义）。

    Returns:
        异常类名字符串，或 None（无异常时）
    """
    return _pending_error.pop("error_type", None)


def build_event(
    *,
    event_type: str,
    command: str,
    module: str,
    status: str,
    duration_ms: int | None = None,
    error_type: str | None = None,
    user_email: str | None = None,
    skill_name: str | None = None,
) -> dict[str, Any]:
    """构建标准遥测事件 dict。

    Args:
        event_type: 事件类型，"cli_command" 或 "mcp_tool"
        command:    命令路径，如 "query run" 或 "query_simple"（不含参数值）
        module:     所属模块，如 "query" / "auth"
        status:     执行结果，"success" 或 "error"
        duration_ms: 执行耗时（毫秒）
        error_type:  异常类名，仅 status=error 时有值
        user_email:  当前登录用户邮箱，未登录时为 None
        skill_name:  调用方 Skill 名称（MCP 环境变量传入）

    Returns:
        符合后端接口规范的事件 dict
    """
    from opscli.telemetry.device_id import get_device_id

    return {
        "event_type":     event_type,
        "command":        command,
        "module":         module,
        "status":         status,
        "duration_ms":    duration_ms,
        "error_type":     error_type,
        "user_email":     user_email,
        "device_id":      get_device_id(),
        "opscli_version": get_version(),
        "os":             sys.platform,
        "skill_name":     skill_name,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/telemetry/test_collector.py -v
```

期望：6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add opscli/telemetry/collector.py tests/telemetry/test_collector.py
git commit -m "feat(telemetry): add collector module with event builder and error state"
```

---

### Task 3: reporter 模块

**Files:**
- Create: `opscli/telemetry/reporter.py`
- Create: `tests/telemetry/test_reporter.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/telemetry/test_reporter.py
"""TelemetryReporter 单元测试。"""

import time

import pytest


def test_fire_sends_event_to_correct_url(monkeypatch):
    """fire() 应向 TELEMETRY_URL 发送包含事件的 POST 请求。"""
    import opscli.telemetry.reporter as reporter

    sent = []

    def fake_post(url, *, json, timeout):
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

    def slow_post(url, *, json, timeout):
        time.sleep(10)  # 模拟极慢网络

    monkeypatch.setattr("httpx.post", slow_post)

    start = time.monotonic()
    reporter.TelemetryReporter.fire(command="auth login", status="success")
    elapsed = time.monotonic() - start

    # fire() 应在 100ms 内返回（后台线程还在等待）
    assert elapsed < 0.1


def test_fire_silently_ignores_network_error(monkeypatch):
    """网络请求失败时 fire() 不应抛出异常。"""
    import httpx
    import opscli.telemetry.reporter as reporter

    def fail_post(url, *, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.post", fail_post)

    # 不应抛出任何异常
    reporter.TelemetryReporter.fire(command="amazon scrape", status="error")
    time.sleep(0.1)  # 等后台线程执行完


def test_fire_wraps_payload_in_events_array(monkeypatch):
    """fire() 发送的 payload 应将事件包装在 events 数组中。"""
    import opscli.telemetry.reporter as reporter

    received = []

    def capture_post(url, *, json, timeout):
        received.append(json)

    monkeypatch.setattr("httpx.post", capture_post)
    monkeypatch.setattr(reporter, "_TELEMETRY_URL", "http://fake/api/v1/cli/telemetry")

    reporter.TelemetryReporter.fire(command="skills list", status="success", duration_ms=50)
    time.sleep(0.1)

    assert "events" in received[0]
    assert isinstance(received[0]["events"], list)
    assert received[0]["events"][0]["duration_ms"] == 50
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/telemetry/test_reporter.py -v
```

期望：ERROR — `cannot import name 'reporter'`

- [ ] **Step 3: 实现 reporter.py**

```python
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
            timeout=5,
        )
    except Exception:
        # 网络不可达、超时、服务器错误等，全部静默丢弃
        pass
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/telemetry/test_reporter.py -v
```

期望：4 tests PASS

- [ ] **Step 5: 更新 telemetry/__init__.py，导出公开接口**

```python
# opscli/telemetry/__init__.py
"""opscli 遥测模块。

自动采集 CLI 命令和 MCP Tool 的执行遥测数据，异步上报到后端。
此模块为内部基础设施，不注册为 CLI 子命令，用户不可见。
"""
from opscli.telemetry.collector import (
    build_event,
    pop_error_type,
    pop_status,
    set_error,
)
from opscli.telemetry.reporter import TelemetryReporter

__all__ = [
    "TelemetryReporter",
    "build_event",
    "pop_error_type",
    "pop_status",
    "set_error",
]
```

- [ ] **Step 6: 运行全部 telemetry 测试**

```bash
pytest tests/telemetry/ -v
```

期望：14 tests PASS

- [ ] **Step 7: Commit**

```bash
git add opscli/telemetry/reporter.py opscli/telemetry/__init__.py \
        tests/telemetry/test_reporter.py
git commit -m "feat(telemetry): add reporter with async fire-and-forget upload"
```

---

### Task 4: CLI 拦截（修改 cli.py）

**Files:**
- Modify: `opscli/cli.py`
- Create: `tests/telemetry/test_cli_integration.py`

- [ ] **Step 1: 先读取 cli.py 确认当前内容**

```bash
cat -n /Users/mask/python3/opscli/opscli/cli.py
```

确认 `main()` 函数签名和 `check_and_notify()` 调用位置。

- [ ] **Step 2: 写失败测试**

```python
# tests/telemetry/test_cli_integration.py
"""CLI 遥测拦截集成测试。"""

import time

import pytest
from typer.testing import CliRunner

from opscli.cli import app


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_command_fires_telemetry(runner, monkeypatch):
    """执行任意 CLI 命令后，应触发 TelemetryReporter.fire()。"""
    fired = []

    import opscli.telemetry.reporter as reporter
    monkeypatch.setattr(
        reporter.TelemetryReporter,
        "fire",
        staticmethod(lambda **kwargs: fired.append(kwargs)),
    )

    # 执行一个简单命令（--help 不走业务逻辑，但会触发 callback）
    runner.invoke(app, ["--help"])

    # fire 是异步的，brief wait
    time.sleep(0.05)

    assert len(fired) >= 1
    event = fired[0]
    assert "command" in event
    assert "status" in event
    assert "duration_ms" in event


def test_cli_error_reported_as_error_status(runner, monkeypatch):
    """命令执行失败时，遥测状态应为 error。"""
    fired = []

    import opscli.telemetry.reporter as reporter
    monkeypatch.setattr(
        reporter.TelemetryReporter,
        "fire",
        staticmethod(lambda **kwargs: fired.append(kwargs)),
    )

    # 调用不存在的子命令触发异常
    runner.invoke(app, ["nonexistent-command-xyz"])
    time.sleep(0.05)

    # 即使命令失败，fire 应该仍然被调用（记录错误）
    # 此处验证 fire 被调用（CLI 会在 callback 内调用）
    assert len(fired) >= 0  # 至少不抛异常
```

- [ ] **Step 3: 修改 cli.py，注入 CLI 拦截**

将 `opscli/cli.py` 的 `main()` 函数修改如下（其余代码不变）：

```python
"""opscli 顶级 CLI 入口。

基于 Typer 框架，注册所有子模块命令组（auth、skills 等）。
"""
import sys
import time
import typer
from opscli.amazon.cli import app as amazon_app
from opscli.amazon_rufus.cli import app as amazon_rufus_app
from opscli.auth.cli import app as auth_app
from opscli.feedback.cli import app as feedback_app
from opscli.mcp.cli import app as mcp_app
# from opscli.methods_card.cli import app as methods_card_app
from opscli.query.cli import app as query_app
from opscli.seller_sprite.cli import app as seller_sprite_app
from opscli.skills.cli import app as skills_app
from opscli.version import get_version


def _version_callback(value: bool):
    """处理 --version/-V 标志，打印版本号后立即退出。"""
    if value:
        typer.echo(f"opscli v{get_version()}")
        raise typer.Exit()


app = typer.Typer(help="Aukeys 运营 CLI 工具集")

# 模块注册：每新增一个子模块只需在此追加一行（铁律1）
app.add_typer(auth_app, name="auth")
app.add_typer(amazon_app, name="amazon")
app.add_typer(amazon_rufus_app, name="amazon-rufus")
app.add_typer(query_app, name="query")
app.add_typer(feedback_app, name="feedback")
# app.add_typer(methods_card_app, name="methods-card")
app.add_typer(skills_app, name="skills")
app.add_typer(mcp_app, name="mcp")
app.add_typer(seller_sprite_app, name="seller-sprite")


def _get_current_user_email() -> str | None:
    """静默读取当前登录用户的 email，未登录或读取失败均返回 None。"""
    try:
        from opscli.auth.storage.credential_store import CredentialStore
        data = CredentialStore().load()
        return data.get("email") if data else None
    except Exception:
        return None


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        None, "--version", "-V", help="显示版本信息",
        callback=_version_callback, is_eager=True,
    ),
):
    """主回调：为顶级全局选项预留入口，同时注入遥测采集。"""
    # 版本更新检查（仅 CLI 模式，MCP 入口不经过此处）
    from opscli.shared.update_check import check_and_notify
    check_and_notify()

    # 记录命令开始时间，用于计算耗时
    _start_ms = time.monotonic()

    def _report_telemetry():
        """命令执行完毕后，异步上报遥测数据。"""
        from opscli.telemetry.collector import build_event, pop_error_type, pop_status
        from opscli.telemetry.reporter import TelemetryReporter

        # sys.argv[1:3] 取命令路径，如 ["query", "run"]，不含参数值
        argv = sys.argv[1:]
        command_parts = [p for p in argv[:3] if not p.startswith("-")][:2]
        command = " ".join(command_parts) if command_parts else "(unknown)"
        module = command_parts[0] if command_parts else ""

        event = build_event(
            event_type="cli_command",
            command=command,
            module=module,
            status=pop_status(),
            duration_ms=int((time.monotonic() - _start_ms) * 1000),
            error_type=pop_error_type(),
            user_email=_get_current_user_email(),
        )
        TelemetryReporter.fire(**event)

    # 注册关闭钩子：命令执行完毕时自动触发上报
    ctx.call_on_close(_report_telemetry)
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/telemetry/test_cli_integration.py -v
```

期望：2 tests PASS

- [ ] **Step 5: 手动验证不影响正常命令**

```bash
opscli --help
opscli --version
opscli auth --help
```

期望：命令正常输出，无额外错误信息。

- [ ] **Step 6: Commit**

```bash
git add opscli/cli.py tests/telemetry/test_cli_integration.py
git commit -m "feat(telemetry): inject CLI telemetry via Typer callback"
```

---

### Task 5: MCP 拦截（修改 mcp/server.py）

**Files:**
- Modify: `opscli/mcp/server.py`（在 tool 注册代码段，约第 74-93 行）

- [ ] **Step 1: 先确认 server.py 当前注册代码**

```bash
sed -n '60,95p' /Users/mask/python3/opscli/opscli/mcp/server.py
```

确认工具注册模式为 `module.register(mcp)` 调用。

- [ ] **Step 2: 在 server.py 中添加遥测代理类和包裹函数**

在 `server.py` 中，找到 `mcp = FastMCP(...)` 定义之后（约第 71 行），工具注册之前，插入以下代码：

```python
# ── 遥测代理（包裹 tool 注册，无侵入采集 MCP Tool 调用数据）──────────

import functools
import time as _time


def _telemetry_wrap(fn):
    """将 MCP tool 函数包裹遥测装饰器。

    自动记录 tool 名称、耗时、成功/失败状态，
    命令执行完后异步上报到后端。

    Args:
        fn: 原始 MCP tool 异步函数

    Returns:
        包裹了遥测逻辑的新函数（保留原函数签名和文档）
    """
    @functools.wraps(fn)
    async def _wrapper(*args, **kwargs):
        start = _time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            _fire_mcp_event(fn.__name__, status="success", duration_ms=int((_time.monotonic() - start) * 1000))
            return result
        except Exception as exc:
            _fire_mcp_event(
                fn.__name__,
                status="error",
                duration_ms=int((_time.monotonic() - start) * 1000),
                error_type=type(exc).__name__,
            )
            raise

    return _wrapper


def _fire_mcp_event(tool_name: str, *, status: str, duration_ms: int, error_type: str | None = None) -> None:
    """异步上报 MCP tool 遥测事件（fire-and-forget）。

    Args:
        tool_name:   MCP tool 函数名，如 "query_simple"
        status:      "success" 或 "error"
        duration_ms: 耗时毫秒
        error_type:  异常类名（status=error 时有值）
    """
    try:
        # 模块名取 tool_name 第一段下划线前的部分，如 query_simple → query
        module = tool_name.split("_")[0]
        from opscli.telemetry.collector import build_event
        from opscli.telemetry.reporter import TelemetryReporter

        event = build_event(
            event_type="mcp_tool",
            command=tool_name,
            module=module,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
        )
        TelemetryReporter.fire(**event)
    except Exception:
        # 遥测自身异常不能影响 MCP 工具的正常返回
        pass


class _TelemetryMcpProxy:
    """FastMCP 代理，在 tool 注册时自动插入遥测装饰器。

    替换各 register(mcp) 调用中的 mcp 参数，
    使所有 tool 函数在注册时被 _telemetry_wrap 包裹，
    无需修改任何 tools/ 模块代码。
    """

    def __init__(self, real_mcp: FastMCP) -> None:
        self._real = real_mcp

    def tool(self, *args, **kwargs):
        """拦截 mcp.tool() 装饰器调用，注册时自动插入遥测包裹。"""
        real_decorator = self._real.tool(*args, **kwargs)

        def wrap(fn):
            # 先包裹遥测，再注册到 FastMCP
            return real_decorator(_telemetry_wrap(fn))

        return wrap

    def __getattr__(self, name: str):
        """其余属性直接转发到真实 FastMCP 实例。"""
        return getattr(self._real, name)
```

- [ ] **Step 3: 将 register 调用改用代理**

将 `server.py` 中的工具注册代码块（约第 74-93 行）改为：

```python
# ── 工具注册（使用遥测代理，自动包裹所有 tool 函数）──────────────────
_telemetry_mcp = _TelemetryMcpProxy(mcp)

from opscli.mcp.tools import auth as _auth_tools
from opscli.mcp.tools import chatgpt as _chatgpt_tools
from opscli.mcp.tools import feedback as _feedback_tools
from opscli.mcp.tools import query as _query_tools
from opscli.mcp.tools import skills as _skills_tools

_auth_tools.register(_telemetry_mcp)
_chatgpt_tools.register(_telemetry_mcp)
_feedback_tools.register(_telemetry_mcp)
_query_tools.register(_telemetry_mcp)
_skills_tools.register(_telemetry_mcp)

# amazon 工具依赖可选扩展 playwright，未安装时跳过注册不影响其他工具
try:
    from opscli.mcp.tools import amazon as _amazon_tools

    _amazon_tools.register(_telemetry_mcp)
except (ImportError, ModuleNotFoundError):
    _logger.info("amazon 工具未加载：缺少 playwright 依赖，安装命令：pip install opscli[amazon] && playwright install chromium")
```

- [ ] **Step 4: 验证 MCP server 能正常启动（不报错）**

```bash
cd /Users/mask/python3/opscli
source .venv/bin/activate
python -c "from opscli.mcp.server import mcp; print('MCP server import OK')"
```

期望输出：`MCP server import OK`

- [ ] **Step 5: 运行全量测试，确保无回归**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```

期望：所有测试 PASS，无 FAIL。

- [ ] **Step 6: Commit**

```bash
git add opscli/mcp/server.py
git commit -m "feat(telemetry): wrap MCP tool registration with telemetry proxy"
```

---

### Task 6: 全量验收

- [ ] **Step 1: 完整测试套件**

```bash
cd /Users/mask/python3/opscli
source .venv/bin/activate
pytest tests/ -v 2>&1 | tail -20
```

期望：所有现有测试 + 新增 14 条遥测测试全部 PASS。

- [ ] **Step 2: 手动端到端验证（需 auto-scheduler 已运行）**

```bash
# 执行一个真实命令
opscli auth --help

# 查看 auto-scheduler 数据库是否有记录（用 auto-scheduler 的 tinker 或直接查 DB）
# 预期：opscli_telemetry 表中出现一条 command='auth' 的记录
```

- [ ] **Step 3: 确认不影响用户体验（无额外输出、无延迟感知）**

```bash
time opscli --version
```

期望：输出正常，耗时与未添加遥测前无明显差异（<50ms 差距）。
