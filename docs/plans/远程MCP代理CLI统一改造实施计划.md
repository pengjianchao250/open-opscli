# 远程MCP代理CLI统一改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 `seller-sprite`、`keepa`、`google-trends`、`canopy` 的正式 CLI 为远程 MCP 代理模式，并将本地直连能力收敛到各自的 `*-debug` 命令。

**Architecture:** 先抽取一个共享远程 MCP CLI 代理基座，再让 `seller_sprite` 复用该基座作为回归样板，随后按相同分轨模式改造 `keepa`、`google-trends`、`canopy`。正式命令只负责远程 tool 参数映射，本地 service 和内部调试能力迁移到 `*_debug` 模块，避免用户接触额度、API key、pytrends、本地 Canopy key 等内部细节。

**Tech Stack:** Python 3.10+, Typer, pytest, MCP HTTP client, opscli 现有 `McpConfigClient` / `RemoteMcpClient`

---

## 文件结构锁定

### 共享层

- Create: `opscli/shared/remote_mcp_adapter.py`
- Modify: `opscli/seller_sprite/remote_adapter.py`
- Test: `tests/shared/test_remote_mcp_adapter.py`

### Keepa

- Modify: `opscli/keepa/cli.py`
- Create: `opscli/keepa/remote_adapter.py`
- Create: `opscli/keepa_debug/__init__.py`
- Create: `opscli/keepa_debug/cli.py`
- Modify: `opscli/cli.py`
- Test: `tests/keepa/test_remote_adapter.py`
- Test: `tests/keepa/test_cli_remote.py`
- Test: `tests/keepa/test_cli_split.py`

### Google Trends

- Modify: `opscli/google_trends/cli.py`
- Create: `opscli/google_trends/remote_adapter.py`
- Create: `opscli/google_trends_debug/__init__.py`
- Create: `opscli/google_trends_debug/cli.py`
- Modify: `opscli/mcp/server.py`
- Modify: `opscli/cli.py`
- Test: `tests/google_trends/test_remote_adapter.py`
- Test: `tests/google_trends/test_cli_remote.py`
- Test: `tests/google_trends/test_cli_split.py`
- Test: `tests/mcp/test_server_google_trends_registration.py`

### Canopy

- Create: `opscli/canopy/__init__.py`
- Create: `opscli/canopy/cli.py`
- Create: `opscli/canopy/remote_adapter.py`
- Create: `opscli/canopy_debug/__init__.py`
- Create: `opscli/canopy_debug/cli.py`
- Modify: `opscli/cli.py`
- Test: `tests/canopy/test_remote_adapter.py`
- Test: `tests/canopy/test_cli_remote.py`
- Test: `tests/canopy/test_cli_split.py`

### 文档与回归

- Modify: `docs/design/2026-06-25远程MCP代理CLI统一方案.md`
- Modify: `docs/change-log-pending.md` 或项目要求的待发布变更记录文件
- Test: `tests/seller_sprite/test_remote_adapter.py`
- Test: `tests/seller_sprite/test_cli_split.py`
- Test: `tests/mcp/test_google_trends_tools.py`

## Task 1: 抽取共享远程 MCP 代理基座并让 seller_sprite 复用

**Files:**
- Create: `opscli/shared/remote_mcp_adapter.py`
- Modify: `opscli/seller_sprite/remote_adapter.py`
- Test: `tests/shared/test_remote_mcp_adapter.py`
- Test: `tests/seller_sprite/test_remote_adapter.py`

- [ ] **Step 1: 先写共享基座的失败测试**

```python
from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.shared.remote_mcp_adapter import RemoteMcpCliAdapter


class FakeConfigClient:
    def __init__(self) -> None:
        self.calls = []

    def fetch_remote_config(self):
        self.calls.append(("fetch",))
        return {"data": {}}

    def select_server(self, payload, *, transport="http", preferred_name=None):
        self.calls.append(("select", payload, transport, preferred_name))
        return RemoteMcpServerConfig(
            name="BI运营系统",
            transport="http",
            url="https://ops.example.com/mcp?api_key=demo",
        )


class FakeRemoteClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.calls = []

    async def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return {"success": True, "data": {"tool": tool_name, "arguments": arguments}}


def test_remote_mcp_cli_adapter_filters_none_and_calls_selected_server():
    config_client = FakeConfigClient()
    created_clients = []

    def factory(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = RemoteMcpCliAdapter(
        config_client=config_client,
        remote_client_factory=factory,
        preferred_name="BI运营系统",
    )

    result = adapter.call_tool("keepa_run", {"scenario": "product", "job_id": None})

    assert result["success"] is True
    assert result["data"]["arguments"] == {"scenario": "product"}
    assert config_client.calls == [
        ("fetch",),
        ("select", {"data": {}}, "http", "BI运营系统"),
    ]
    assert created_clients[0].calls == [("keepa_run", {"scenario": "product"})]
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `pytest tests/shared/test_remote_mcp_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opscli.shared.remote_mcp_adapter'`

- [ ] **Step 3: 写共享基座的最小实现**

```python
"""正式 CLI 远程 MCP 代理基座。"""

from __future__ import annotations

import asyncio
from typing import Any

from opscli.mcp_client import McpConfigClient, RemoteMcpClient


class RemoteMcpCliAdapter:
    """封装正式 CLI 复用的远程 MCP 调用流程。"""

    def __init__(
        self,
        *,
        config_client=None,
        remote_client_factory=None,
        preferred_name: str = "BI运营系统",
    ) -> None:
        self.config_client = config_client or McpConfigClient()
        self.remote_client_factory = remote_client_factory or RemoteMcpClient
        self.preferred_name = preferred_name

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self._filter_none(arguments)
        client = self._build_remote_client()
        try:
            return asyncio.run(client.call_tool(tool_name, payload))
        except PermissionError as exc:
            if "401" not in str(exc):
                raise
        retry_client = self._build_remote_client()
        return asyncio.run(retry_client.call_tool(tool_name, payload))

    def _build_remote_client(self):
        payload = self.config_client.fetch_remote_config()
        server = self.config_client.select_server(
            payload,
            transport="http",
            preferred_name=self.preferred_name,
        )
        return self.remote_client_factory(server.url)

    def _filter_none(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in arguments.items() if value is not None}
```

- [ ] **Step 4: 运行共享基座测试，确认通过**

Run: `pytest tests/shared/test_remote_mcp_adapter.py -v`
Expected: PASS

- [ ] **Step 5: 写 seller_sprite 回归测试，约束它改为复用基座后行为不变**

```python
from opscli.seller_sprite.remote_adapter import SellerSpriteRemoteAdapter


class FakeBaseAdapter:
    def __init__(self) -> None:
        self.calls = []

    def call_tool(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, arguments))
        return {"success": True, "data": {"tool": tool_name, "arguments": arguments}}


class FakeAuthClient:
    def get_session(self, alias: str | None = None) -> str:
        assert alias == "ops"
        return "sid-cli-123"


def test_seller_sprite_remote_adapter_uses_shared_base_for_run():
    base = FakeBaseAdapter()
    adapter = SellerSpriteRemoteAdapter(base_adapter=base, auth_client=FakeAuthClient())

    result = adapter.run(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": "B07YRMT36L"},
        page_size=100,
        export_format="json",
        output_dir=None,
        job_id=None,
    )

    assert result["data"]["tool"] == "seller_sprite_run"
    assert base.calls == [
        (
            "seller_sprite_run",
            {
                "scenario": "keyword-reverse",
                "site": "JP",
                "period": "nearly",
                "params": {"asin": "B07YRMT36L"},
                "page_size": 100,
                "export_format": "json",
                "session_id": "sid-cli-123",
            },
        )
    ]
```

- [ ] **Step 6: 修改 seller_sprite adapter 为组合共享基座**

```python
from opscli.auth import AuthClient
from opscli.shared.remote_mcp_adapter import RemoteMcpCliAdapter


class SellerSpriteRemoteAdapter:
    """将正式 CLI 动作映射到远端卖家精灵 MCP 工具。"""

    def __init__(
        self,
        *,
        base_adapter: RemoteMcpCliAdapter | None = None,
        auth_client: AuthClient | None = None,
    ) -> None:
        self.base_adapter = base_adapter or RemoteMcpCliAdapter(preferred_name="BI运营系统")
        self.auth_client = auth_client or AuthClient()

    def run(self, *, scenario, site, period, params, page_size, export_format, output_dir, job_id):
        session_id = self.auth_client.get_session("ops")
        return self.base_adapter.call_tool(
            "seller_sprite_run",
            {
                "scenario": scenario,
                "site": site,
                "period": period,
                "params": params,
                "page_size": page_size,
                "export_format": export_format,
                "output_dir": output_dir,
                "job_id": job_id,
                "session_id": session_id,
            },
        )
```

- [ ] **Step 7: 运行 seller_sprite 回归测试**

Run: `pytest tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli_split.py -v`
Expected: PASS

- [ ] **Step 8: 提交共享层和 seller_sprite 回归改造**

```bash
git add opscli/shared/remote_mcp_adapter.py opscli/seller_sprite/remote_adapter.py tests/shared/test_remote_mcp_adapter.py tests/seller_sprite/test_remote_adapter.py
git commit -m "refactor: share remote mcp cli adapter base"
```

## Task 2: 改造 Keepa 为正式远程 CLI 并下沉本地直连到 keepa-debug

**Files:**
- Modify: `opscli/keepa/cli.py`
- Create: `opscli/keepa/remote_adapter.py`
- Create: `opscli/keepa_debug/__init__.py`
- Create: `opscli/keepa_debug/cli.py`
- Modify: `opscli/cli.py`
- Test: `tests/keepa/test_remote_adapter.py`
- Test: `tests/keepa/test_cli_remote.py`
- Test: `tests/keepa/test_cli_split.py`

- [ ] **Step 1: 先写 Keepa 远程 adapter 的失败测试**

```python
from opscli.keepa.remote_adapter import KeepaRemoteAdapter


class FakeBaseAdapter:
    def __init__(self) -> None:
        self.calls = []

    def call_tool(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, arguments))
        return {"success": True, "data": {"tool": tool_name, "arguments": arguments}}


def test_keepa_remote_adapter_maps_run_to_keepa_run():
    base = FakeBaseAdapter()
    adapter = KeepaRemoteAdapter(base_adapter=base)

    result = adapter.run(
        scenario="product",
        site="US",
        params={"asin": "B0088PUEPK"},
        output_dir=None,
        job_id=None,
        export_format="xls",
        reserve_tokens=None,
        force=False,
        wait=False,
    )

    assert result["data"]["tool"] == "keepa_run"
    assert base.calls == [
        (
            "keepa_run",
            {
                "scenario": "product",
                "site": "US",
                "params": {"asin": "B0088PUEPK"},
                "export_format": "xls",
                "force": False,
                "wait": False,
            },
        )
    ]
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `pytest tests/keepa/test_remote_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opscli.keepa.remote_adapter'`

- [ ] **Step 3: 实现 KeepaRemoteAdapter**

```python
"""Keepa 正式 CLI 的远端 MCP 适配层。"""

from __future__ import annotations

from opscli.shared.remote_mcp_adapter import RemoteMcpCliAdapter


class KeepaRemoteAdapter:
    """将正式 Keepa CLI 动作映射到远端 keepa_* tools。"""

    def __init__(self, *, base_adapter: RemoteMcpCliAdapter | None = None) -> None:
        self.base_adapter = base_adapter or RemoteMcpCliAdapter(preferred_name="BI运营系统")

    def scenarios(self):
        return self.base_adapter.call_tool("keepa_scenarios", {})

    def run(self, *, scenario, site, params, output_dir, job_id, export_format, reserve_tokens, force, wait):
        return self.base_adapter.call_tool(
            "keepa_run",
            {
                "scenario": scenario,
                "site": site,
                "params": params,
                "output_dir": output_dir,
                "job_id": job_id,
                "export_format": export_format,
                "reserve_tokens": reserve_tokens,
                "force": force,
                "wait": wait,
            },
        )

    def job_status(self, job_id: str):
        return self.base_adapter.call_tool("keepa_job_status", {"job_id": job_id})

    def export(self, job_id: str):
        return self.base_adapter.call_tool("keepa_export", {"job_id": job_id})
```

- [ ] **Step 4: 写 Keepa CLI 分轨测试，锁定正式命令不再暴露 token-status**

```python
import json

from typer.testing import CliRunner

from opscli.cli import app
from opscli.keepa import cli as keepa_cli
from opscli.keepa_debug import cli as keepa_debug_cli

runner = CliRunner()


def test_public_keepa_help_hides_token_status():
    result = runner.invoke(app, ["keepa", "--help"])
    assert result.exit_code == 0
    assert "token-status" not in result.stdout
    assert "job-status" in result.stdout


def test_debug_keepa_help_keeps_token_status():
    result = runner.invoke(app, ["keepa-debug", "--help"])
    assert result.exit_code == 0
    assert "token-status" in result.stdout


def test_public_keepa_run_uses_remote_adapter(monkeypatch):
    captured = {}

    class FakeAdapter:
        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"success": True, "data": {"job_id": "keepa-public-job"}}

    monkeypatch.setattr(keepa_cli, "KeepaRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        app,
        [
            "keepa",
            "run",
            "product",
            "--site",
            "US",
            "--params",
            json.dumps({"asin": "B0088PUEPK"}),
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"]["scenario"] == "product"
    assert captured["kwargs"]["params"] == {"asin": "B0088PUEPK"}
    assert '"job_id": "keepa-public-job"' in result.stdout
```

- [ ] **Step 5: 将当前本地 Keepa CLI 逻辑迁入 keepa-debug**

```python
"""Keepa 本地直连调试 CLI。"""

from __future__ import annotations

import asyncio
import json

import typer

from opscli.keepa.domain.models import KeepaScenarioRequest
from opscli.keepa.services import KeepaApiManager


app = typer.Typer(help="Keepa 本地直连调试命令面。")


@app.command("token-status")
def token_status() -> None:
    payload = asyncio.run(KeepaApiManager().token_status())
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
```

- [ ] **Step 6: 将正式 keepa CLI 改为远程代理版本**

```python
"""Keepa 正式 CLI。"""

from __future__ import annotations

import json
from typing import Any

import typer

from opscli.keepa.remote_adapter import KeepaRemoteAdapter


app = typer.Typer(help="Keepa 远端 MCP 正式命令面。")


@app.command("scenarios")
def scenarios() -> None:
    payload = KeepaRemoteAdapter().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    payload = KeepaRemoteAdapter().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
```

- [ ] **Step 7: 在顶级 CLI 挂载 keepa-debug**

```python
from opscli.keepa_debug.cli import app as keepa_debug_app

app.add_typer(keepa_app, name="keepa")
app.add_typer(keepa_debug_app, name="keepa-debug")
```

- [ ] **Step 8: 运行 Keepa 改造相关测试**

Run: `pytest tests/keepa/test_remote_adapter.py tests/keepa/test_cli_remote.py tests/keepa/test_cli_split.py -v`
Expected: PASS

- [ ] **Step 9: 提交 Keepa 分轨改造**

```bash
git add opscli/keepa/cli.py opscli/keepa/remote_adapter.py opscli/keepa_debug opscli/cli.py tests/keepa/test_remote_adapter.py tests/keepa/test_cli_remote.py tests/keepa/test_cli_split.py
git commit -m "feat: route keepa cli through remote mcp"
```

## Task 3: 恢复 Google Trends MCP 注册并改造正式 CLI

**Files:**
- Modify: `opscli/mcp/server.py`
- Modify: `opscli/google_trends/cli.py`
- Create: `opscli/google_trends/remote_adapter.py`
- Create: `opscli/google_trends_debug/__init__.py`
- Create: `opscli/google_trends_debug/cli.py`
- Modify: `opscli/cli.py`
- Test: `tests/mcp/test_server_google_trends_registration.py`
- Test: `tests/google_trends/test_remote_adapter.py`
- Test: `tests/google_trends/test_cli_remote.py`
- Test: `tests/google_trends/test_cli_split.py`

- [ ] **Step 1: 先写 MCP 注册回归测试**

```python
from pathlib import Path


def test_mcp_server_registers_google_trends_tools():
    content = Path("opscli/mcp/server.py").read_text(encoding="utf-8")
    assert "from opscli.mcp.tools import google_trends as _google_trends_tools" in content
    assert "_google_trends_tools.register(_telemetry_mcp)" in content
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `pytest tests/mcp/test_server_google_trends_registration.py -v`
Expected: FAIL because the import or register line is currently commented out

- [ ] **Step 3: 恢复 google_trends tools 注册**

```python
from opscli.mcp.tools import google_trends as _google_trends_tools

_google_trends_tools.register(_telemetry_mcp)
```

- [ ] **Step 4: 写 Google Trends 远程 adapter 测试**

```python
from opscli.google_trends.remote_adapter import GoogleTrendsRemoteAdapter


class FakeBaseAdapter:
    def __init__(self) -> None:
        self.calls = []

    def call_tool(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, arguments))
        return {"success": True, "data": {"tool": tool_name, "arguments": arguments}}


def test_google_trends_remote_adapter_maps_run_to_google_trends_run():
    base = FakeBaseAdapter()
    adapter = GoogleTrendsRemoteAdapter(base_adapter=base)

    result = adapter.run(
        scenario="interest-over-time",
        geo="US",
        params={"keyword": "flashlight", "timeframe": "today 12-m"},
        output_dir=None,
        job_id=None,
        export_format="xls",
        hl=None,
        tz=None,
    )

    assert result["data"]["tool"] == "google_trends_run"
    assert base.calls == [
        (
            "google_trends_run",
            {
                "scenario": "interest-over-time",
                "geo": "US",
                "params": {"keyword": "flashlight", "timeframe": "today 12-m"},
                "export_format": "xls",
            },
        )
    ]
```

- [ ] **Step 5: 实现 GoogleTrendsRemoteAdapter，并新增 google-trends-debug**

```python
class GoogleTrendsRemoteAdapter:
    def __init__(self, *, base_adapter=None) -> None:
        self.base_adapter = base_adapter or RemoteMcpCliAdapter(preferred_name="BI运营系统")

    def scenarios(self):
        return self.base_adapter.call_tool("google_trends_scenarios", {})

    def run(self, *, scenario, geo, params, output_dir, job_id, export_format, hl, tz):
        return self.base_adapter.call_tool(
            "google_trends_run",
            {
                "scenario": scenario,
                "geo": geo,
                "params": params,
                "output_dir": output_dir,
                "job_id": job_id,
                "export_format": export_format,
                "hl": hl,
                "tz": tz,
            },
        )
```

- [ ] **Step 6: 写 CLI 分轨测试，锁定正式 google-trends 和 google-trends-debug**

```python
import json

from typer.testing import CliRunner

from opscli.cli import app
from opscli.google_trends import cli as google_trends_cli

runner = CliRunner()


def test_public_google_trends_run_uses_remote_adapter(monkeypatch):
    captured = {}

    class FakeAdapter:
        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"success": True, "data": {"job_id": "gt-public-job"}}

    monkeypatch.setattr(google_trends_cli, "GoogleTrendsRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        app,
        [
            "google-trends",
            "run",
            "interest-over-time",
            "--geo",
            "US",
            "--params",
            json.dumps({"keyword": "flashlight", "timeframe": "today 12-m"}),
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"]["scenario"] == "interest-over-time"
    assert '"job_id": "gt-public-job"' in result.stdout
```

- [ ] **Step 7: 在顶级 CLI 挂载 google-trends-debug**

```python
from opscli.google_trends_debug.cli import app as google_trends_debug_app

app.add_typer(google_trends_app, name="google-trends")
app.add_typer(google_trends_debug_app, name="google-trends-debug")
```

- [ ] **Step 8: 运行 Google Trends 注册与 CLI 改造测试**

Run: `pytest tests/mcp/test_server_google_trends_registration.py tests/google_trends/test_remote_adapter.py tests/google_trends/test_cli_remote.py tests/google_trends/test_cli_split.py tests/mcp/test_google_trends_tools.py -v`
Expected: PASS

- [ ] **Step 9: 提交 Google Trends 改造**

```bash
git add opscli/mcp/server.py opscli/google_trends/cli.py opscli/google_trends/remote_adapter.py opscli/google_trends_debug opscli/cli.py tests/mcp/test_server_google_trends_registration.py tests/google_trends/test_remote_adapter.py tests/google_trends/test_cli_remote.py tests/google_trends/test_cli_split.py
git commit -m "feat: route google trends cli through remote mcp"
```

## Task 4: 新增 canopy / canopy-debug 命令面并映射 beta_canopy_* tools

**Files:**
- Create: `opscli/canopy/__init__.py`
- Create: `opscli/canopy/cli.py`
- Create: `opscli/canopy/remote_adapter.py`
- Create: `opscli/canopy_debug/__init__.py`
- Create: `opscli/canopy_debug/cli.py`
- Modify: `opscli/cli.py`
- Test: `tests/canopy/test_remote_adapter.py`
- Test: `tests/canopy/test_cli_remote.py`
- Test: `tests/canopy/test_cli_split.py`

- [ ] **Step 1: 先写 Canopy 远程 adapter 的失败测试**

```python
from opscli.canopy.remote_adapter import CanopyRemoteAdapter


class FakeBaseAdapter:
    def __init__(self) -> None:
        self.calls = []

    def call_tool(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, arguments))
        return {"success": True, "data": {"tool": tool_name, "arguments": arguments}}


def test_canopy_remote_adapter_maps_run_to_beta_canopy_run():
    base = FakeBaseAdapter()
    adapter = CanopyRemoteAdapter(base_adapter=base)

    result = adapter.run(
        scenario="product",
        domain="US",
        params={"asin": "B0B3JBVDYP"},
        api_key=None,
        timeout_seconds=60,
        export_format="xls",
        output_dir=None,
        job_id=None,
    )

    assert result["data"]["tool"] == "beta_canopy_run"
    assert base.calls == [
        (
            "beta_canopy_run",
            {
                "scenario": "product",
                "domain": "US",
                "params": {"asin": "B0B3JBVDYP"},
                "timeout_seconds": 60,
                "export_format": "xls",
            },
        )
    ]
```

- [ ] **Step 2: 实现 CanopyRemoteAdapter**

```python
class CanopyRemoteAdapter:
    def __init__(self, *, base_adapter=None) -> None:
        self.base_adapter = base_adapter or RemoteMcpCliAdapter(preferred_name="BI运营系统")

    def scenarios(self):
        return self.base_adapter.call_tool("beta_canopy_scenarios", {})

    def run(self, *, scenario, domain, params, api_key, timeout_seconds, export_format, output_dir, job_id):
        return self.base_adapter.call_tool(
            "beta_canopy_run",
            {
                "scenario": scenario,
                "domain": domain,
                "params": params,
                "api_key": api_key,
                "timeout_seconds": timeout_seconds,
                "export_format": export_format,
                "output_dir": output_dir,
                "job_id": job_id,
            },
        )
```

- [ ] **Step 3: 写 canopy CLI 分轨测试**

```python
import json

from typer.testing import CliRunner

from opscli.cli import app
from opscli.canopy import cli as canopy_cli

runner = CliRunner()


def test_public_canopy_help_exposes_formal_commands():
    result = runner.invoke(app, ["canopy", "--help"])
    assert result.exit_code == 0
    assert "scenarios" in result.stdout
    assert "run" in result.stdout


def test_public_canopy_run_uses_remote_adapter(monkeypatch):
    captured = {}

    class FakeAdapter:
        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"success": True, "data": {"job_id": "canopy-job"}}

    monkeypatch.setattr(canopy_cli, "CanopyRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        app,
        [
            "canopy",
            "run",
            "product",
            "--domain",
            "US",
            "--params",
            json.dumps({"asin": "B0B3JBVDYP"}),
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"]["scenario"] == "product"
    assert '"job_id": "canopy-job"' in result.stdout
```

- [ ] **Step 4: 新增 canopy 正式 CLI 和 canopy-debug CLI**

```python
"""Canopy 远端 MCP 正式命令面。"""

from __future__ import annotations

import json
from typing import Any

import typer

from opscli.canopy.remote_adapter import CanopyRemoteAdapter


app = typer.Typer(help="Canopy 远端 MCP 正式命令面。")


@app.command("scenarios")
def scenarios() -> None:
    payload = CanopyRemoteAdapter().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
```

```python
"""Canopy 本地直连调试命令面。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

from opscli.beta.canopy.domain.models import CanopyScenarioRequest
from opscli.beta.canopy.services import CanopyApiManager
```

- [ ] **Step 5: 在顶级 CLI 挂载 canopy 和 canopy-debug**

```python
from opscli.canopy.cli import app as canopy_app
from opscli.canopy_debug.cli import app as canopy_debug_app

app.add_typer(canopy_app, name="canopy")
app.add_typer(canopy_debug_app, name="canopy-debug")
```

- [ ] **Step 6: 运行 Canopy 相关测试**

Run: `pytest tests/canopy/test_remote_adapter.py tests/canopy/test_cli_remote.py tests/canopy/test_cli_split.py tests/mcp/test_beta_tools.py -v`
Expected: PASS

- [ ] **Step 7: 提交 Canopy 正式命令面改造**

```bash
git add opscli/canopy opscli/canopy_debug opscli/cli.py tests/canopy/test_remote_adapter.py tests/canopy/test_cli_remote.py tests/canopy/test_cli_split.py
git commit -m "feat: add formal canopy cli backed by remote mcp"
```

## Task 5: 帮助文案、文档与全链路回归收尾

**Files:**
- Modify: `opscli/keepa/cli.py`
- Modify: `opscli/keepa_debug/cli.py`
- Modify: `opscli/google_trends/cli.py`
- Modify: `opscli/google_trends_debug/cli.py`
- Modify: `opscli/canopy/cli.py`
- Modify: `opscli/canopy_debug/cli.py`
- Modify: `docs/design/2026-06-25远程MCP代理CLI统一方案.md`
- Modify: `docs/change-log-pending.md`

- [ ] **Step 1: 统一正式 CLI / debug CLI 的 help 文案**

```python
app = typer.Typer(help="Keepa 远端 MCP 正式命令面。")
app = typer.Typer(help="Keepa 本地直连调试命令面。")

app = typer.Typer(help="Google Trends 远端 MCP 正式命令面。")
app = typer.Typer(help="Google Trends 本地直连调试命令面。")

app = typer.Typer(help="Canopy 远端 MCP 正式命令面。")
app = typer.Typer(help="Canopy 本地直连调试命令面。")
```

- [ ] **Step 2: 追加变更记录**

```markdown
## 2026-06-25 远程MCP代理CLI统一改造

**变更原因**：统一 keepa、google-trends、canopy 与 seller-sprite 的正式 CLI 行为，减少用户接触内部账号与本地调试能力。
**改动点**：新增共享远程 MCP 代理基座；新增 keepa-debug、google-trends-debug、canopy、canopy-debug；恢复 google_trends MCP 注册；正式 CLI 切换为远程代理。
**验证结果**：执行相关 pytest 命令并通过。
**影响范围**：keepa、google-trends、canopy、seller-sprite 正式 CLI 与调试命令面。
**回滚方式**：回退本次提交，恢复原 keepa/google-trends 本地 CLI 和 canopy 未挂载状态。
---
```

- [ ] **Step 3: 跑全链路回归测试**

Run: `pytest tests/shared/test_remote_mcp_adapter.py tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli_split.py tests/keepa/test_remote_adapter.py tests/keepa/test_cli_remote.py tests/keepa/test_cli_split.py tests/google_trends/test_remote_adapter.py tests/google_trends/test_cli_remote.py tests/google_trends/test_cli_split.py tests/canopy/test_remote_adapter.py tests/canopy/test_cli_remote.py tests/canopy/test_cli_split.py tests/mcp/test_keepa_tools.py tests/mcp/test_google_trends_tools.py tests/mcp/test_beta_tools.py -v`
Expected: PASS

- [ ] **Step 4: 手工检查顶级命令帮助**

Run: `python -m opscli.cli --help`
Expected: stdout contains `keepa-debug`, `google-trends-debug`, `canopy`, `canopy-debug`

- [ ] **Step 5: 提交文档与收尾**

```bash
git add opscli docs/design/2026-06-25远程MCP代理CLI统一方案.md docs/change-log-pending.md tests
git commit -m "docs: finalize remote mcp cli unification rollout"
```

## 自检

- 规格覆盖检查：
  - 正式 CLI 全部走远程 MCP：Task 2/3/4 覆盖
  - 本地直连能力下沉 debug：Task 2/3/4 覆盖
  - `keepa token-status` 不进入正式 CLI：Task 2 覆盖
  - `google_trends` 恢复 MCP 注册：Task 3 覆盖
  - `canopy` 对外替代 `beta` 命名：Task 4 覆盖
  - `seller_sprite` 无回归：Task 1 与 Task 5 覆盖

- 占位符检查：
  - 没有使用 TBD/TODO/后续补充等占位语
  - 每个代码步骤都给出明确示例
  - 每个验证步骤都给出命令和预期结果

- 类型与命名一致性检查：
  - 共享基座统一为 `RemoteMcpCliAdapter`
  - 模块适配层统一为 `KeepaRemoteAdapter`、`GoogleTrendsRemoteAdapter`、`CanopyRemoteAdapter`
  - 正式命令与 debug 命令命名统一为 `模块` / `模块-debug`
