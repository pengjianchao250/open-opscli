# opscli MCP 模块接入规范

> 本文档描述如何将新开发的 CLI 子模块快速接入 MCP（Model Context Protocol）无状态服务模式。

---

## 一、架构原则

### 1.1 无状态核心约束

| 约束 | 说明 |
|------|------|
| **服务器不保存用户凭证** | 禁止读写 `~/.config/opscli/credentials.bin`，禁止调用 `CredentialStore.save_session()` |
| **认证信息由调用方传入** | 所有敏感 Tool 必须接受 `session_id` 参数（必填），可选接受 `jwt` |
| **实时换取 JWT** | 无 `jwt` 时，使用 `session_id` 向后端实时请求，不依赖本地缓存 |
| **统一响应格式** | 所有 Tool 返回 `{"success": bool, "data": ..., "error": ...}` |

### 1.2 安全分层

```
API Key（SSE headers）        → 谁可以连接 MCP 服务器
    session_id（Tool 参数）    → 谁可以发起后端请求
        JWT（向后端换取）      → 后端最终鉴权
```

---

## 二、目录结构规范

新增模块 `xxx` 的完整目录结构：

```
opscli/
├── xxx/                          # 新模块目录
│   ├── __init__.py               # 模块标识，可导出 SDK 入口
│   ├── cli.py                    # CLI 命令（ Typer app）
│   ├── client.py                 # HTTP 客户端（改造支持外部凭证）
│   ├── manager.py                # 业务编排层（改造支持外部凭证）
│   ├── models.py                 # 数据模型
│   └── exceptions.py             # 异常类
├── mcp/
│   └── server.py                 # MCP Tool 注册入口（在此添加 @mcp.tool()）
└── cli.py                        # 顶级 Typer app（注册 xxx_app）
```

> **铁律**：新增模块必须遵循 [CLAUDE.md 铁律1](CLAUDE.md)，目录包含 `__init__.py` 和 `cli.py`。

---

## 三、最小改造清单

假设已有一个完整的 CLI 子模块 `xxx`，以下步骤将其接入 MCP。

### 步骤 1：改造 Manager 支持外部凭证

```python
# opscli/xxx/manager.py

from opscli.xxx.client import XXXClient

class XXXManager:
    """xxx 业务编排层（支持无状态 MCP 模式）。"""

    def __init__(self, jwt: str | None = None, session_id: str | None = None):
        # 传入外部凭证，优先使用；否则回退到本地 AuthClient
        self.client = XXXClient(jwt=jwt, session_id=session_id)

    def do_something(self, param: str) -> dict:
        """示例业务方法。"""
        return self.client.call_backend(param)
```

### 步骤 2：改造 Client 支持外部凭证

```python
# opscli/xxx/client.py

from opscli.auth import AuthClient

class XXXClient:
    """xxx HTTP 客户端（支持无状态 MCP 模式）。"""

    def __init__(self, jwt: str | None = None, session_id: str | None = None):
        self.auth_client = AuthClient()
        self.jwt = jwt
        self.session_id = session_id

    def _get_auth(self, alias: str = "ops") -> tuple[dict, dict]:
        """获取请求认证头。优先外部凭证，否则回退本地存储。"""
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                # 无状态模式：用 session_id 实时向后端换取 JWT
                jwt = self.auth_client.get_token_by_session(self.session_id, alias)
            headers = {"Authorization": f"Bearer {jwt}"}
            cookies = {"polarisUserToken": self.session_id}
            return headers, cookies
        # 回退到本地存储（兼容 stdio / CLI 模式）
        return self.auth_client.build_request_auth(alias)

    def call_backend(self, param: str) -> dict:
        headers, cookies = self._get_auth("ops")
        # ... 发送 HTTP 请求 ...
        pass
```

**关键改造点**：
- `__init__` 新增 `jwt` 和 `session_id` 参数
- `_get_auth()` 优先使用外部传入的凭证
- 无 `jwt` 但有 `session_id` 时，调用 `auth_client.get_token_by_session()` 实时换取

### 步骤 3：在 server.py 注册 MCP Tool

在 `opscli/mcp/server.py` 中添加：

```python
# ── xxx tools ────────────────────────────────────────────────────

@mcp.tool()
async def xxx_do_something(
    param: str,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """xxx 模块示例 Tool：执行业务操作。

    需要认证：必须提供 session_id。
    """
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))
    try:
        from opscli.xxx.manager import XXXManager
        result = XXXManager(jwt=jwt, session_id=session_id).do_something(param)
        return _ok(result)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def xxx_list_items() -> dict:
    """xxx 模块示例 Tool：列出所有项。

    不需要认证：直接返回本地数据。
    """
    try:
        from opscli.xxx.manager import XXXManager
        result = XXXManager().list_items()
        return _ok(result)
    except Exception as exc:
        return _err(exc)
```

**Tool 分类规则**：

| 是否需要认证 | 参数要求 | 示例 |
|------------|---------|------|
| **不需要** | 无 `session_id` / `jwt` | `query_metadata`、`auth_system_list`、`skills_list` |
| **需要** | 必须有 `session_id`（提前校验），`jwt` 可选 | `query_build_and_run`、`auth_get_token` |

### 步骤 4：更新 pyproject.toml scripts（如有独立启动入口）

如果 `xxx` 需要独立的 CLI 入口：

```toml
[project.scripts]
opscli = "opscli.cli:app"
opscli-mcp = "opscli.mcp.server:run"
opscli-xxx = "opscli.xxx.cli:app"   # 如需要
```

### 步骤 5：编写 SKILL_MCP.md

在 `opscli/skills/templates/ops-xxx/` 下创建 `SKILL_MCP.md`：

```markdown
---
name: ops-xxx
mcp-version: v1.0.0
description: xxx 模块的 MCP 无状态接口
---

# ops-xxx (MCP 无状态模式)

...
```

---

## 四、认证参数处理模式

### 模式 A：Tool 需要认证（推荐模板）

```python
@mcp.tool()
async def xxx_sensitive_action(
    business_param: str,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """需要认证的业务 Tool。

    Args:
        business_param: 业务参数
        session_id: 用户授权后获得的 session_id（必填）
        jwt: JWT，不传则自动用 session_id 换取
    """
    # 1. 提前校验 session_id
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))

    try:
        # 2. 创建 Manager，传入外部凭证
        mgr = XXXManager(jwt=jwt, session_id=session_id)
        # 3. 执行业务
        result = mgr.sensitive_action(business_param)
        return _ok(result)
    except Exception as exc:
        return _err(exc)
```

### 模式 B：Tool 不需要认证

```python
@mcp.tool()
async def xxx_public_action(
    business_param: str,
) -> dict:
    """不需要认证的业务 Tool。"""
    try:
        mgr = XXXManager()
        result = mgr.public_action(business_param)
        return _ok(result)
    except Exception as exc:
        return _err(exc)
```

### 模式 C：Device Flow 授权类 Tool

```python
@mcp.tool()
async def auth_login_start() -> dict:
    """发起 Device Flow。服务器不保存 session。"""
    from opscli.auth.core.device_flow import DeviceFlow
    try:
        flow = DeviceFlow(ops_url=OPS_URL, store=None)  # store=None = 不保存
        return _ok(flow.request_device_code())
    except Exception as exc:
        return _err(exc)
```

---

## 五、快速接入检查清单

新增模块接入 MCP 时，逐项确认：

| 检查项 | 状态 | 说明 |
|--------|------|------|
| Manager 支持 `jwt` / `session_id` 参数 | ☐ | 改造 `__init__` |
| Client 支持 `_get_auth()` 外部凭证优先 | ☐ | 改造 HTTP 请求头构造 |
| server.py 注册 `@mcp.tool()` | ☐ | 按"模式 A/B/C"编写 |
| 需要认证的 Tool 提前校验 `session_id` | ☐ | `if not session_id: return _err(...)` |
| 统一使用 `_ok()` / `_err()` 响应 | ☐ | 禁止直接 `raise` 或 `return` 原始数据 |
| SKILL_MCP.md 已编写 | ☐ | 描述 Tool 调用方式和认证流程 |
| 测试通过：无 session_id → 返回错误 | ☐ | 验证认证门禁 |
| 测试通过：仅 session_id → 自动换取 JWT | ☐ | 验证无状态模式 |
| 测试通过：session_id + jwt → 直接使用 | ☐ | 验证性能优化路径 |

---

## 六、完整示例：新增 `ops-notify` 模块

### 6.1 目录结构

```
opscli/notify/
├── __init__.py
├── cli.py
├── client.py
├── manager.py
├── models.py
└── exceptions.py
```

### 6.2 client.py

```python
"""notify 模块 HTTP 客户端。"""
from opscli.auth import AuthClient

class NotifyClient:
    def __init__(self, jwt: str | None = None, session_id: str | None = None):
        self.auth_client = AuthClient()
        self.jwt = jwt
        self.session_id = session_id

    def _get_auth(self):
        if self.session_id:
            jwt = self.jwt or self.auth_client.get_token_by_session(self.session_id, "ops")
            return {"Authorization": f"Bearer {jwt}"}, {"polarisUserToken": self.session_id}
        return self.auth_client.build_request_auth("ops")

    def send(self, message: str, channel: str) -> dict:
        headers, cookies = self._get_auth()
        # ... httpx post ...
        return {"sent": True, "channel": channel}
```

### 6.3 manager.py

```python
"""notify 模块业务编排层。"""
from opscli.notify.client import NotifyClient

class NotifyManager:
    def __init__(self, jwt: str | None = None, session_id: str | None = None):
        self.client = NotifyClient(jwt=jwt, session_id=session_id)

    def send(self, message: str, channel: str) -> dict:
        return self.client.send(message, channel)
```

### 6.4 server.py 注册

```python
@mcp.tool()
async def notify_send(
    message: str,
    channel: str = "default",
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """发送通知消息。需要认证。"""
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))
    try:
        from opscli.notify.manager import NotifyManager
        result = NotifyManager(jwt=jwt, session_id=session_id).send(message, channel)
        return _ok(result)
    except Exception as exc:
        return _err(exc)
```

### 6.5 验证

```python
# 测试1: 无 session_id → 错误
notify_send(message="hello")
# → {"success": false, "error": {"code": "ValueError", "message": "无状态模式下必须提供 session_id"}}

# 测试2: 有 session_id → 成功
notify_send(message="hello", session_id="860b0636485b5188a2b9b4ed5210e736")
# → {"success": true, "data": {"sent": true, "channel": "default"}}
```

---

## 七、常见问题

### Q1: 模块已有 CLI，需要重写业务逻辑吗？

**不需要**。业务逻辑保留在 Manager/Client 中，只需：
1. Manager `__init__` 新增 `jwt` / `session_id` 参数
2. Client `_get_auth()` 优先使用外部凭证
3. 在 `server.py` 添加 `@mcp.tool()` 包装层

### Q2: 无状态模式和本地 CLI 模式如何共存？

Manager/Client 同时支持两种模式：
- **CLI 模式**：不传 `jwt`/`session_id`，回退到 `AuthClient.build_request_auth()`（读取本地存储）
- **MCP 模式**：传入 `jwt`/`session_id`，优先使用外部凭证

### Q3: 所有 Tool 都需要 `session_id` 吗？

**不是**。只读本地数据、不涉及后端请求的 Tool 不需要认证：
- `query_metadata`（读本地 metadata）
- `auth_system_list`（读本地系统注册表）
- `skills_list`（扫描本地目录）

### Q4: 如何测试新 Tool？

```bash
# 1. 启动 MCP 服务
opscli-mcp --transport sse --port 8765

# 2. 用 Python MCP SDK 测试
python3 -c "
import asyncio
import json
from mcp import ClientSession
from mcp.client.sse import sse_client

async def test():
    headers = {'Authorization': 'Bearer opscli-mcp-xxx'}
    async with sse_client('http://127.0.0.1:8765/sse', headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool('notify_send', {
                'message': 'test',
                'session_id': '860b0636485b5188a2b9b4ed5210e736'
            })
            print(result.content[0].text)

asyncio.run(test())
"
```

---

## 八、引用文件

| 文件 | 说明 |
|------|------|
| `opscli/mcp/server.py` | MCP Tool 注册主入口 |
| `opscli/query/services/manager.py` | QueryManager（已改造，参考示例） |
| `opscli/query/transport/client.py` | QueryClient（已改造，参考示例） |
| `opscli/auth/__init__.py` | AuthClient.get_token_by_session() |
| `README_MCP.md` | MCP 服务部署与使用指南 |
| `CLAUDE.md` | 项目开发铁律与规范 |
