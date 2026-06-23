# Seller Sprite Remote MCP Config CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将正式用户使用的 `opscli seller-sprite` 切换为基于远端 MCP 配置直连的 CLI 入口，同时保留本地直跑能力作为 `seller-sprite-debug` 开发调试命令。

**Architecture:** 公开 CLI 不再假设存在单独的“JWT 换 api_key/base_url”接口，而是直接复用现有 `AuthClient` 登录态请求 `/v1/mcp-api-keys/config`。CLI 从返回的 `http.mcpServers` 中选择远端 MCP URL，再通过 MCP client 调用既有 `seller_sprite_*` tool；`seller-sprite-debug` 继续保留本地 `SellerSpriteApiManager` 链路。

**Tech Stack:** Python 3.10+、Typer、httpx、`opscli.auth.AuthClient`、`opscli.shared.http.parse_remote_response`、`mcp.ClientSession`、`mcp.client.streamable_http`、pytest。

---

### Task 1: 固化 remote MCP config 契约并废弃旧 auth-bridge 假设

**Files:**
- Create: `docs/spec/卖家精灵远端MCP配置契约.md`
- Create: `tests/seller_sprite/test_remote_mcp_config_contract.py`
- Delete: `docs/spec/seller-sprite-remote-mcp-auth-contract.md`
- Delete: `tests/seller_sprite/test_remote_auth_contract.py`

- [ ] **Step 1: Write the failing contract tests**

```python
from pathlib import Path


DOC_PATH = Path("docs/spec/卖家精灵远端MCP配置契约.md")


def test_remote_mcp_config_contract_accepts_http_server_url():
    payload = {
        "success": True,
        "data": {
            "http": {
                "mcpServers": {
                    "BI运营系统": {
                        "type": "http",
                        "url": "https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
                    }
                }
            }
        },
    }
    server = payload["data"]["http"]["mcpServers"]["BI运营系统"]
    assert server["type"] == "http"
    assert server["url"].startswith("https://")
    assert "api_key=" in server["url"]


def test_remote_mcp_config_contract_doc_freezes_endpoint_and_transport():
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "GET /api/v1/mcp-api-keys/config" in content
    assert "http.mcpServers" in content
    assert '"type": "http"' in content
    assert "https://ops.mcp.xenkee.com/mcp?api_key=" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_mcp_config_contract.py -q
```

Expected: FAIL because the new contract document and test file do not exist yet.

- [ ] **Step 3: Write the config contract document**

```markdown
# 卖家精灵远端MCP配置契约

## Endpoint

`GET /api/v1/mcp-api-keys/config`

## Request Auth

- Authorization: Bearer <ops_jwt>
- X-Opscli-Version: <version>

## Success Response

{
  "success": true,
  "data": {
    "http": {
      "mcpServers": {
        "BI运营系统": {
          "type": "http",
          "url": "https://ops.mcp.xenkee.com/mcp?api_key=mcp_xxx"
        }
      }
    }
  }
}

## Gate Rules

- public `opscli seller-sprite` only consumes this config endpoint for remote MCP discovery
- CLI prefers `http.mcpServers` over `sse.mcpServers`
- URL logs and errors must redact the `api_key` query value
```

- [ ] **Step 4: Remove the obsolete auth-bridge contract artifacts**

```powershell
git rm docs/spec/seller-sprite-remote-mcp-auth-contract.md tests/seller_sprite/test_remote_auth_contract.py
```

- [ ] **Step 5: Re-run the contract tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_mcp_config_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/spec/卖家精灵远端MCP配置契约.md tests/seller_sprite/test_remote_mcp_config_contract.py
git commit -m "docs: freeze seller sprite remote mcp config contract"
```

### Task 2: 新增 CLI 侧 MCP config client

**Files:**
- Create: `opscli/mcp_client/__init__.py`
- Create: `opscli/mcp_client/config_client.py`
- Create: `tests/mcp/test_config_client.py`

- [ ] **Step 1: Write the failing unit tests**

```python
import httpx
import respx

from opscli.mcp_client.config_client import McpConfigClient


class DummyAuthClient:
    def build_request_auth(self, alias):
        assert alias == "ops"
        return {"Authorization": "Bearer jwt-demo", "X-Opscli-Version": "0.0.97"}, {"polarisUserToken": "sid-demo"}


@respx.mock
def test_fetch_remote_config_uses_cli_auth_headers():
    route = respx.get("https://ops.example.com/api/v1/mcp-api-keys/config").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "http": {
                        "mcpServers": {
                            "BI运营系统": {
                                "type": "http",
                                "url": "https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
                            }
                        }
                    }
                },
            },
        )
    )
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")

    payload = client.fetch_remote_config()

    assert route.called
    assert payload["data"]["http"]["mcpServers"]["BI运营系统"]["type"] == "http"


def test_select_http_server_returns_named_server():
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    payload = {
        "data": {
            "http": {
                "mcpServers": {
                    "BI运营系统": {
                        "type": "http",
                        "url": "https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
                    }
                }
            }
        }
    }

    server = client.select_server(payload, transport="http", preferred_name="BI运营系统")

    assert server.name == "BI运营系统"
    assert server.transport == "http"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\mcp\test_config_client.py -q
```

Expected: FAIL because `opscli.mcp_client.config_client` does not exist.

- [ ] **Step 3: Implement the minimal config client**

```python
from dataclasses import dataclass

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.shared.http import parse_remote_response


@dataclass(frozen=True)
class RemoteMcpServerConfig:
    name: str
    transport: str
    url: str


class McpConfigClient:
    def __init__(self, auth_client: AuthClient | None = None, ops_url: str | None = None) -> None:
        self.auth_client = auth_client or AuthClient()
        self.ops_url = (ops_url or OPS_URL).rstrip("/")

    def fetch_remote_config(self) -> dict:
        headers, cookies = self.auth_client.build_request_auth("ops")
        response = httpx.get(
            f"{self.ops_url}/v1/mcp-api-keys/config",
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        return parse_remote_response(
            response,
            http_error_cls=RuntimeError,
            business_error_cls=RuntimeError,
            bad_json_error_cls=ValueError,
        )

    def select_server(self, payload: dict, *, transport: str = "http", preferred_name: str | None = None) -> RemoteMcpServerConfig:
        servers = (((payload.get("data") or {}).get(transport) or {}).get("mcpServers") or {})
        if preferred_name and preferred_name in servers:
            item = servers[preferred_name]
            return RemoteMcpServerConfig(name=preferred_name, transport=transport, url=str(item["url"]))
        for name, item in servers.items():
            return RemoteMcpServerConfig(name=str(name), transport=transport, url=str(item["url"]))
        raise ValueError(f"remote MCP config 缺少 {transport}.mcpServers")
```

- [ ] **Step 4: Re-run the tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\mcp\test_config_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add opscli/mcp_client/__init__.py opscli/mcp_client/config_client.py tests/mcp/test_config_client.py
git commit -m "feat: add cli remote mcp config client"
```

### Task 3: 新增 URL 直连型 MCP remote client

**Files:**
- Modify: `opscli/mcp_client/__init__.py`
- Create: `opscli/mcp_client/remote_client.py`
- Create: `tests/mcp/test_remote_client.py`

- [ ] **Step 1: Write the failing unit tests**

```python
import json

import pytest

from opscli.mcp_client.remote_client import RemoteMcpClient


class DummyToolResult:
    def __init__(self, payload):
        self.content = [type("TextPart", (), {"text": json.dumps(payload)})()]


class DummySession:
    async def initialize(self):
        return None

    async def call_tool(self, tool_name, arguments):
        assert tool_name == "seller_sprite_scenarios"
        return DummyToolResult({"success": True, "data": []})


def test_remote_mcp_client_requires_url():
    with pytest.raises(ValueError):
        RemoteMcpClient(url="")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\mcp\test_remote_client.py -q
```

Expected: FAIL because `RemoteMcpClient` does not exist.

- [ ] **Step 3: Implement the thin remote client wrapper**

```python
import json

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


class RemoteMcpClient:
    def __init__(self, url: str) -> None:
        if not url:
            raise ValueError("remote MCP url is required")
        self.url = url

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        http_client = create_mcp_http_client()
        async with streamable_http_client(self.url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
        text = result.content[0].text
        return json.loads(text)
```

- [ ] **Step 4: Re-run the tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\mcp\test_remote_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add opscli/mcp_client/__init__.py opscli/mcp_client/remote_client.py tests/mcp/test_remote_client.py
git commit -m "feat: add url-based remote mcp client wrapper"
```

### Task 4: 增加 seller-sprite remote adapter 并切换公开 CLI

**Files:**
- Create: `opscli/seller_sprite/remote_adapter.py`
- Modify: `opscli/seller_sprite/cli.py`
- Create: `tests/seller_sprite/test_remote_adapter.py`
- Create: `tests/seller_sprite/test_cli.py`

- [ ] **Step 1: Write the failing adapter tests**

```python
from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.seller_sprite.remote_adapter import SellerSpriteRemoteAdapter


class FakeConfigClient:
    def fetch_remote_config(self):
        return {"data": {}}

    def select_server(self, payload, *, transport="http", preferred_name=None):
        return RemoteMcpServerConfig(
            name="BI运营系统",
            transport="http",
            url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
        )


class FakeRemoteClient:
    async def call_tool(self, tool_name, arguments):
        return {"success": True, "data": {"tool": tool_name, "arguments": arguments}, "error": None}


def test_remote_adapter_maps_run_to_seller_sprite_run():
    adapter = SellerSpriteRemoteAdapter(
        config_client=FakeConfigClient(),
        remote_client_factory=lambda url: FakeRemoteClient(),
    )

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
    assert result["data"]["arguments"]["scenario"] == "keyword-reverse"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_cli.py -q
```

Expected: FAIL because the adapter and public CLI path are not implemented yet.

- [ ] **Step 3: Implement the adapter**

```python
import asyncio

from opscli.mcp_client.config_client import McpConfigClient
from opscli.mcp_client.remote_client import RemoteMcpClient


class SellerSpriteRemoteAdapter:
    def __init__(self, config_client=None, remote_client_factory=None) -> None:
        self.config_client = config_client or McpConfigClient()
        self.remote_client_factory = remote_client_factory or (lambda url: RemoteMcpClient(url))

    def _client(self):
        payload = self.config_client.fetch_remote_config()
        server = self.config_client.select_server(payload, transport="http", preferred_name="BI运营系统")
        return self.remote_client_factory(server.url)

    def scenarios(self) -> dict:
        return asyncio.run(self._client().call_tool("seller_sprite_scenarios", {}))

    def run(self, *, scenario: str, site: str, period: str, params: dict, page_size: int, export_format: str, output_dir: str | None, job_id: str | None) -> dict:
        return asyncio.run(
            self._client().call_tool(
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
                },
            )
        )
```

- [ ] **Step 4: Replace the public CLI with the remote adapter**

```python
@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    payload = SellerSpriteRemoteAdapter().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
```

The public CLI must expose only:
- `scenarios`
- `run`
- `job-status`
- `export`

The public CLI must not expose:
- `--mode`
- `--page-prepare`
- `--task-interval-seconds`
- `--cooldown-seconds`

- [ ] **Step 5: Re-run the tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_cli.py tests\seller_sprite\test_cli_split.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add opscli/seller_sprite/remote_adapter.py opscli/seller_sprite/cli.py tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli.py tests/seller_sprite/test_cli_split.py
git commit -m "feat: route seller sprite public cli through remote mcp config"
```

### Task 5: 处理 config 刷新、401 重试和 URL 脱敏

**Files:**
- Modify: `opscli/seller_sprite/remote_adapter.py`
- Modify: `opscli/mcp_client/config_client.py`
- Modify: `opscli/mcp_client/remote_client.py`
- Create: `tests/seller_sprite/test_remote_refresh.py`

- [ ] **Step 1: Write the failing behavior tests**

```python
import pytest


def test_remote_adapter_refetches_config_once_on_unauthorized():
    calls = {"config": 0, "tool": 0}

    class FakeConfigClient:
        def fetch_remote_config(self):
            calls["config"] += 1
            key = "old" if calls["config"] == 1 else "new"
            return {
                "data": {
                    "http": {
                        "mcpServers": {
                            "BI运营系统": {
                                "type": "http",
                                "url": f"https://ops.mcp.xenkee.com/mcp?api_key={key}",
                            }
                        }
                    }
                }
            }

        def select_server(self, payload, *, transport="http", preferred_name=None):
            server = payload["data"]["http"]["mcpServers"]["BI运营系统"]
            from opscli.mcp_client.config_client import RemoteMcpServerConfig
            return RemoteMcpServerConfig(name="BI运营系统", transport="http", url=server["url"])

    class UnauthorizedRemoteClient:
        def __init__(self, url):
            self.url = url

        async def call_tool(self, tool_name, arguments):
            calls["tool"] += 1
            if "api_key=old" in self.url:
                raise PermissionError("401 unauthorized")
            return {"success": True, "data": {"job_id": "job-1"}, "error": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_refresh.py -q
```

Expected: FAIL because retry and redaction logic are not implemented.

- [ ] **Step 3: Implement one refresh retry and URL redaction**

```python
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def redact_mcp_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, "***" if key == "api_key" else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _call_with_refresh(self, tool_name: str, arguments: dict) -> dict:
    try:
        return asyncio.run(self._client().call_tool(tool_name, arguments))
    except PermissionError as exc:
        if "401" not in str(exc):
            raise
        return asyncio.run(self._refreshed_client().call_tool(tool_name, arguments))
```

- [ ] **Step 4: Re-run the tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_refresh.py tests\mcp\test_config_client.py tests\mcp\test_remote_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add opscli/seller_sprite/remote_adapter.py opscli/mcp_client/config_client.py opscli/mcp_client/remote_client.py tests/seller_sprite/test_remote_refresh.py
git commit -m "feat: add remote mcp config refresh retry and url redaction"
```

### Task 6: 更新上游文档与最终验证

**Files:**
- Modify: `docs/spec/卖家精灵MCP接口直连接入说明.md`
- Modify: `opscli/skills/templates/ops-asin-data-collector/references/source-mapping.md`
- Modify: `docs/change-log-pending.md`

- [ ] **Step 1: Write or update the upstream regression test**

```python
def test_public_seller_sprite_command_contract_stays_remote_first():
    command = ["opscli", "seller-sprite", "run", "keyword-reverse", "--site", "JP"]
    assert command[:3] == ["opscli", "seller-sprite", "run"]
```

- [ ] **Step 2: Run the focused verification suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_cli_split.py tests\seller_sprite\test_remote_mcp_config_contract.py tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_remote_refresh.py tests\mcp\test_config_client.py tests\mcp\test_remote_client.py -q
```

Expected: PASS.

- [ ] **Step 3: Update the public docs**

```markdown
- 正式 CLI：`opscli seller-sprite ...`
- 开发调试 CLI：`opscli seller-sprite-debug ...`
- 正式 CLI 通过 CLI auth 请求 `/api/v1/mcp-api-keys/config` 获取远端 MCP URL
- 正式 CLI 优先使用 `http.mcpServers`，不走本地浏览器账号链路
```

- [ ] **Step 4: Record the change log entry**

Append to `docs/change-log-pending.md`:

```markdown
## 2026-06-23 seller-sprite 远端MCP配置直连

**变更原因**：后端已提供 `/api/v1/mcp-api-keys/config`，无需再实现单独的 JWT 换远端 key 接口。
**改动点**：新增 CLI 侧 MCP config client、URL 直连 remote client、seller-sprite remote adapter，并将公开 CLI 切换到远端 MCP。
**验证结果**：记录 seller-sprite / mcp client 相关 pytest 命令与通过结果。
**影响范围**：`opscli seller-sprite` 正式入口；`seller-sprite-debug` 不受影响。
**回滚方式**：回退 `opscli/seller_sprite/cli.py` 到当前桥接版本，并移除 remote adapter 与 mcp_client 新增文件。
---
```

- [ ] **Step 5: Commit**

```bash
git add docs/spec/卖家精灵MCP接口直连接入说明.md opscli/skills/templates/ops-asin-data-collector/references/source-mapping.md docs/change-log-pending.md
git commit -m "docs: align seller sprite public cli with remote mcp config flow"
```

## Self-Review

- Spec coverage: this plan covers config contract freeze, CLI auth-based config fetch, URL-based remote MCP client, seller-sprite adapter, one-time config refresh retry, URL redaction, and public/debug doc alignment.
- Placeholder scan: no TBD/TODO markers remain; every task names exact files, commands, and expected checks.
- Type consistency: the plan consistently uses `McpConfigClient`, `RemoteMcpServerConfig`, `RemoteMcpClient`, and `SellerSpriteRemoteAdapter` as the public implementation types.
