# opscli MCP Server（无状态模式）

将 opscli 核心能力以 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 的形式暴露，AI Agent 可直接调用，无需通过 CLI subprocess。

**关键特性**：
- **无状态设计**：服务器不保存任何用户 OAuth 凭证（session_id / jwt），所有认证信息由调用方传入
- **固定 API Key**：SSE 连接层通过自动生成的固定 API Key 进行访问控制
- **按需授权**：调用敏感 Tool 时自动触发 Device Flow，用户在浏览器完成授权

---

## 架构概览

```
用户 OpenCode / AI Agent
  → headers: Authorization: Bearer opscli-mcp-xxx  （API Key，控制谁可连服务器）
    → MCP 服务器（无状态，不保存 OAuth 凭证）
      → Tool 参数: session_id + jwt（可选）  （控制谁可访问后端数据）
        → 后端 ops / polaris（最终鉴权）
```

**安全分层**：
1. **API Key**：控制谁能连接到 MCP 服务器（由服务器自动生成，管理员分发给用户）
2. **session_id / JWT**：控制谁能访问后端业务数据（由用户通过 Device Flow 授权获得）

---

## 安装依赖

```bash
pip install "aukeys-opscli[mcp]"
# 或本地开发环境
uv pip install -e ".[mcp]"
```

---

## 启动 MCP 服务器

### SSE 模式（推荐，用于 OpenCode / Inspector）

```bash
opscli-mcp --transport sse --host 127.0.0.1 --port 8765
```

启动后会在控制台输出自动生成的 API Key：

```
[opscli-mcp] SSE 服务已启用 API Key 鉴权
[opscli-mcp] API Key: opscli-mcp-H0BWl9L8PC84OSBMRzGW1psUJ0L2aaqd

请将此 Key 配置到客户端 headers: Authorization: Bearer <api_key>
```

**首次启动时自动生成**，API Key 持久化保存在：
```
~/.config/opscli/mcp_api_key
```

- 重启后自动复用同一 API Key
- 文件权限 `600`（仅所有者可读写）
- 删除该文件后下次启动会重新生成

**后台运行**：

```bash
nohup opscli-mcp --transport sse --host 127.0.0.1 --port 8765 > /tmp/opscli-mcp-sse.log 2>&1 &
```

### stdio 模式（Claude Desktop）

不需要手动启动，在配置文件中注册后由 AI 工具自动管理。

**Claude Desktop** — 编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "opscli": {
      "command": "/path/to/.venv/bin/opscli-mcp"
    }
  }
}
```

> stdio 模式下 API Key 鉴权不生效（无 HTTP 层），所有 Tool 仍需传入 session_id。

---

## 客户端连接配置

### OpenCode

编辑 `~/.config/opencode/opencode.json`：

```json
{
  "mcp": {
    "opscli": {
      "type": "remote",
      "url": "http://127.0.0.1:8765/sse",
      "headers": {
        "Authorization": "Bearer opscli-mcp-H0BWl9L8PC84OSBMRzGW1psUJ0L2aaqd"
      },
      "enabled": true
    }
  }
}
```

> `headers.Authorization` 中的 `opscli-mcp-xxx` 替换为服务器实际生成的 API Key。

### Inspector 调试

安装 Inspector（仅需一次）：

```bash
sudo npm install -g @modelcontextprotocol/inspector
```

启动 Inspector：

```bash
mcp-inspector --port 5173
```

在浏览器打开输出的链接：
- Transport 选 **SSE**
- URL 填 `http://127.0.0.1:8765/sse`
- Headers 填 `{"Authorization": "Bearer opscli-mcp-xxx"}`
- 点击 Connect 即可交互调用所有 Tools

---

## 授权流程（Device Flow）

无状态模式下，服务器不保存用户凭证。**每次调用需要认证的 Tool 时，必须传入 `session_id`**（和可选的 `jwt`）。

### 典型授权流程

```text
1. 用户首次调用 query_build_and_run(...)
   → 错误："无状态模式下必须提供 session_id"

2. AI 自动调用 auth_login_start()
   → 返回 {verification_url, user_code, device_code, interval}

3. 用户在浏览器中打开 verification_url，输入 user_code

4. AI 按 interval 轮询 auth_login_poll(device_code)
   → 返回 {status: "authorized", session_id, email, expires_at}

5. AI 将 session_id 保存到当前对话上下文

6. 自动重试 query_build_and_run(session_id=xxx)
   → 成功返回数据
```

### 凭证刷新

- **JWT 即将过期**：AI 调用 `auth_token_refresh(session_id)` 自动换取新 JWT
- **session_id 过期**：返回 `NOT_AUTHENTICATED` 错误，AI 提示用户重新执行 Device Flow 授权

---

## 可用 Tools

### 数据查询（query_*）

#### `query_metadata`

查询指定数据集的 metadata（维度/指标字段列表）。**不需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dataset` | string | 二选一 | 数据集别名（dataset_alias） |
| `table_id` | integer | 二选一 | 数据集表 ID |
| `skills_dir` | string | 否 | 指定 Skill 安装根目录 |

**返回示例：**
```json
{
  "success": true,
  "data": {
    "dataset": { "dataset_alias": "ds_xxx", "table_id": 1 },
    "fields": [
      { "field_name": "date_id", "global_alias": "date_id", "field_type": "dimension", "verbose_name": "日期" }
    ],
    "source": "local"
  },
  "error": null
}
```

---

#### `query_build`

基于简化参数构造标准 query payload（不执行查询）。**不需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dataset` | string | 二选一 | 数据集别名 |
| `table_id` | integer | 二选一 | 数据集表 ID |
| `dimensions` | string[] | 否 | 维度列表，格式 `"field_name[:alias]"` |
| `metrics` | string[] | 否 | 指标列表，格式 `"field_name:aggregation[:alias]"` |
| `where_conditions` | string[] | 否 | 筛选条件，格式 `"field\|operator\|value_json"` |
| `where_json` | string | 否 | where 条件 JSON 字符串 |
| `order_by` | string[] | 否 | 排序，格式 `"expr[:asc\|desc]"` |
| `having_conditions` | string[] | 否 | having 条件 |
| `limit` | integer | 否 | 返回行数上限，默认 20 |
| `offset` | integer | 否 | 偏移量，默认 0 |
| `dry_run` | boolean | 否 | 仅生成 SQL 不执行，默认 false |
| `data_comparison` | string | 否 | 数据对比，格式 `"field,start_date,end_date"` |
| `output_path` | string | 否 | 将 payload 写入本地文件路径 |
| `skills_dir` | string | 否 | 指定 Skill 目录 |

---

#### `query_run`

读取本地 payload JSON 文件并转发至服务端执行查询。**需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `payload_path` | string | 是 | 本地 payload 文件路径 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

---

#### `query_build_and_run`

构造 query payload 并立即执行，一步返回数据结果。**需要认证**。

参数包含 `query_build` 的全部参数（不含 `output_path`），外加：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

**典型用法：**
```python
query_build_and_run(
  table_id=1,
  dimensions=["date_id", "channel_name"],
  metrics=["reviews_qty:SUM"],
  where_conditions=["date_id|>=|\"2026-01-01\""],
  limit=50,
  session_id="860b0636485b5188a2b9b4ed5210e736",
)
```

> 如果 `jwt` 未提供，服务器会自动用 `session_id` 向后端换取 JWT，无需调用方手动管理。

---

### 认证（auth_*）

#### `auth_login_start`

发起 Device Flow 登录第一步。返回验证地址、用户码、设备码和有效期。**不需要认证**。

**返回：**
```json
{
  "success": true,
  "data": {
    "verification_url": "https://ops.api.qa.aukeyit.com/cli-auth",
    "user_code": "OKP2-CN1E",
    "device_code": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "expires_in": 300,
    "interval": 3
  },
  "error": null
}
```

---

#### `auth_login_poll`

单次轮询 Device Flow 授权状态。服务器不保存 session，授权成功后直接返回 session_id。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `device_code` | string | 必填 | `auth_login_start` 返回的设备码 |
| `timeout` | integer | `10` | 单次 HTTP 请求超时，最大 30 秒 |

**状态说明**：
- `pending`：等待用户授权
- `authorized`：授权成功，返回 `session_id` / `email` / `expires_at`
- `expired`：设备码超时
- `denied`：用户拒绝授权

---

#### `auth_get_token`

获取指定系统的有效 JWT。**无状态模式下必须传入 `session_id`**，服务器直接用其向后端请求 JWT，不读取本地存储。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `system` | string | `"ops"` | 系统别名，可选 `"polaris"` 等 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |

**返回：** `{ "success": true, "data": "<JWT 字符串>", "error": null }`

---

#### `auth_check_token`

检测 JWT 有效性及剩余有效时间（秒）。**纯本地解析**，不向后端发请求。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `jwt` | string | **是** | JWT 字符串 |

**返回：** `{ "success": true, "data": { "valid": true, "expires_in": 86399 }, "error": null }`

---

#### `auth_is_authenticated`

检查 session_id 是否有效（尝试用其获取 JWT）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | **是** | 用户授权后获得的 session_id |

**返回：** `{ "success": true, "data": true, "error": null }`

---

#### `auth_token_refresh`

刷新指定系统 JWT。必须有 `session_id`。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"__all__"` | 系统别名，或 `__all__` 刷新全部 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |

---

#### `auth_system_list`

列出所有已注册系统（builtin / local / ops_sync）。**不需要认证**。

#### `auth_system_add`

添加或更新用户自定义系统。不需要认证。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alias` | string | 是 | 系统别名 |
| `url` | string | 是 | 系统地址 |
| `key` | string | 否 | 系统 key |
| `token_endpoint` | string | `"/api/auth/cli-token"` | Token 端点 |

#### `auth_system_remove`

移除用户自定义系统；内置系统不可删除。不需要认证。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alias` | string | 是 | 系统别名 |

#### `auth_system_sync`

从 ops 后端同步系统列表。**需要 `session_id`**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | **是** | 用户授权后获得的 session_id |

---

#### `auth_build_request_auth`

构造统一请求认证参数（JWT Bearer + Session Cookie）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `system` | string | `"ops"` | 系统别名 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动换取 |

**返回：** `{ "success": true, "data": { "headers": {...}, "cookies": {...} }, "error": null }`

---

#### `auth_doctor`

检查 session 有效性与各系统连通性，返回结构化诊断结果。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | 传入时检查该 session 有效性 |

---

### Skill 管理（skills_*）

Skill 相关 Tool **不需要认证**。

#### `skills_list`

列出当前环境中所有已安装的 Skill。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 指定扫描目录（默认自动检测） |

---

#### `skills_status`

查询 Skill 安装状态，包含本地版本与远端最新版本对比。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 指定扫描目录 |

---

#### `skills_install`

从内置模板安装 Skill。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | Skill 名称，如 `ops-auth` |
| `skills_dir` | string | 否 | 指定安装目录 |
| `runtime` | string | 否 | `claude`、`openclaw`、`codex`、`opencode`、`all` |
| `force` | boolean | 否 | 是否覆盖已有安装 |

---

#### `skills_upgrade`

升级指定 Skill 到远端最新版本。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 默认 `ops-dataset-query` |
| `skills_dir` | string | 否 | 指定扫描目录 |
| `force` | boolean | 否 | 是否强制升级 |

---

## 统一响应格式

所有 Tools 均返回统一结构：

```json
{
  "success": true | false,
  "data": <业务数据 或 null>,
  "error": null | {
    "code": "ERROR_CODE",
    "message": "错误描述"
  }
}
```

常见错误码：

| 错误码 | 说明 |
|--------|------|
| `NOT_AUTHENTICATED` | session_id 缺失或无效，需要重新 Device Flow 授权 |
| `DATASET_NOT_FOUND` | 未找到目标数据集，检查 alias 或 table_id |
| `QUERY_METADATA_NOT_READY` | 本地 metadata 未就绪，请先安装并升级 `ops-dataset-query` |
| `INVALID_PAYLOAD` | 参数格式不合法 |
| `REMOTE_HTTP_ERROR` | 远端 HTTP 请求失败 |
| `REMOTE_BUSINESS_ERROR` | 远端业务层返回失败 |

---

## 开发与调试

### 查看实时日志

```bash
# SSE Server 日志
tail -f /tmp/opscli-mcp-sse.log

# Inspector 日志
tail -f /tmp/opscli-inspector.log
```

### 停止服务

```bash
pkill -f "opscli.mcp.server"   # 停止 SSE Server
pkill -f "mcp-inspector"        # 停止 Inspector
```

### 用 Python 客户端直接测试

```python
import asyncio
import json
from mcp import ClientSession
from mcp.client.sse import sse_client

API_KEY = "opscli-mcp-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

async def main():
    async with sse_client("http://127.0.0.1:8765/sse", headers=HEADERS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # 列出工具
            tools = await session.list_tools()
            print(f"Tools: {[t.name for t in tools.tools]}")
            
            # 发起 Device Flow
            result = await session.call_tool("auth_login_start", {})
            data = json.loads(result.content[0].text)
            print(f"Login: {data}")

asyncio.run(main())
```

---

## 文件结构

```
opscli/mcp/
├── __init__.py          # 模块标识
├── auth_middleware.py   # SSE 层固定 API Key 鉴权
├── cli.py               # opscli mcp user 命令（遗留兼容）
├── context.py           # 无状态模式空兼容
├── server.py            # FastMCP Server 定义，注册所有 Tools（无状态）
└── user_store.py        # MCP 用户注册表（遗留兼容）
```

启动入口由 `pyproject.toml` 的 `[project.scripts]` 注册：

```toml
opscli-mcp = "opscli.mcp.server:run"
```
