# opscli MCP Server

将 opscli 核心能力以 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 的形式暴露，AI Agent 可直接调用，无需通过 CLI subprocess。

## 快速开始

### 安装依赖

```bash
pip install "aukeys-opscli[mcp]"
# 或本地开发环境
uv pip install -e ".[mcp]"
```

### 单用户模式确认已登录

MCP Server 复用本地凭证，使用前需先完成登录：

```bash
opscli auth login
opscli auth token status   # 确认登录状态
```

如希望完全通过 MCP 完成登录，可调用 `auth_login_start()` 获取验证地址和用户码，再按返回的 `interval` 调用 `auth_login_poll(device_code)`，直到返回 `status=authorized`。

---

## 启动方式

### 方式一：stdio（Claude Desktop / Claude Code）

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

**Claude Code** — 在项目的 `.mcp.json` 或全局 `~/.claude/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "opscli": {
      "command": "opscli-mcp",
      "type": "stdio"
    }
  }
}
```

### 方式二：SSE 服务器（本地 HTTP）

```bash
opscli-mcp --transport sse --host 127.0.0.1 --port 8765
```

启动后 SSE 端点为：`http://127.0.0.1:8765/sse`

后台运行：

```bash
nohup opscli-mcp --transport sse --port 8765 > /tmp/opscli-mcp.log 2>&1 &
```

### 方式三：多用户隔离模式

先创建 MCP 用户，API Key 只展示一次：

```bash
opscli mcp user add --desc "张三的工作站" --pretty
```

stdio 多用户模式：

```bash
OPSCLI_MCP_API_KEY=opscli-mcp-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
  opscli-mcp --multi-user
```

SSE 多用户模式：

```bash
opscli-mcp --transport sse --host 127.0.0.1 --port 8765 \
  --multi-user --require-auth
```

SSE 客户端需携带请求头：

```http
Authorization: Bearer opscli-mcp-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 方式四：Inspector 调试界面

先安装 Inspector（仅需一次）：

```bash
sudo npm install -g @modelcontextprotocol/inspector
```

启动 Inspector：

```bash
mcp-inspector --port 5173
```

在浏览器打开输出的链接，Transport 选 **SSE**，URL 填 `http://127.0.0.1:8765/sse`，点击 Connect 即可交互调用所有 Tools。

---

## 可用 Tools

### 数据查询（query_*）

#### `query_metadata`

查询指定数据集的 metadata（维度/指标字段列表）。

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
    "dataset": { "dataset_alias": "my_dataset", "table_id": 1 },
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

基于简化参数构造标准 query payload（不执行查询）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dataset` | string | 二选一 | 数据集别名 |
| `table_id` | integer | 二选一 | 数据集表 ID |
| `dimensions` | string[] | 否 | 维度列表，格式 `"field_name[:alias]"` |
| `metrics` | string[] | 否 | 指标列表，格式 `"field_name:aggregation[:alias]"` |
| `where_conditions` | string[] | 否 | 筛选条件，格式 `"field\|operator\|value_json"` |
| `where_json` | string | 否 | where 条件 JSON 字符串（与 where_conditions 二选一） |
| `order_by` | string[] | 否 | 排序，格式 `"expr[:asc\|desc]"` |
| `having_conditions` | string[] | 否 | having 条件，格式 `"expr\|operator\|value_json"` |
| `limit` | integer | 否 | 返回行数上限，默认 20 |
| `offset` | integer | 否 | 偏移量，默认 0 |
| `dry_run` | boolean | 否 | 仅生成 SQL 不执行，默认 false |
| `data_comparison` | string | 否 | 数据对比，格式 `"field,start_date,end_date"` |
| `output_path` | string | 否 | 将 payload 写入本地文件路径 |
| `skills_dir` | string | 否 | 指定 Skill 目录 |

**参数格式示例：**
```
dimensions: ["date_id", "country_code:country"]
metrics:    ["sales:SUM", "orders:COUNT:order_cnt"]
where:      ["date_id|>=|\"2026-01-01\"", "country_code|IN|[\"US\",\"UK\"]"]
order_by:   ["sales:desc"]
```

---

#### `query_run`

读取本地 payload JSON 文件并转发至服务端执行查询。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `payload_path` | string | 是 | 本地 payload 文件路径（可由 query_build 的 output_path 生成） |

---

#### `query_build_and_run`

构造 query payload 并立即执行，一步返回数据结果。参数与 `query_build` 相同（省略 `output_path`）。

**典型用法：**
```
query_build_and_run(
  dataset="my_dataset",
  dimensions=["date_id", "country_code"],
  metrics=["sales:SUM"],
  where_conditions=["date_id|>=|\"2026-01-01\""],
  limit=50
)
```

---

### 认证（auth_*）

#### `auth_login_start`

发起 Device Flow 登录第一步，返回验证地址、用户码、设备码和有效期。

**返回：** `{ "success": true, "data": { "verification_url": "...", "user_code": "...", "device_code": "...", "expires_in": 300, "interval": 3 }, "error": null }`

---

#### `auth_login_poll`

单次轮询 Device Flow 授权状态，不进行 300 秒长阻塞。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `device_code` | string | 必填 | `auth_login_start` 返回的设备码 |
| `timeout` | integer | `10` | 单次 HTTP 请求超时，最大 30 秒 |

---

#### `auth_logout`

清除当前用户凭证。多用户模式下只清除当前 API Key 对应的隔离凭证目录。

---

#### `auth_get_token`

获取指定系统的有效 JWT，过期时自动刷新。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"ops"` | 系统别名，可选 `"polaris"` 等已注册系统 |

**返回：** `{ "success": true, "data": "<JWT 字符串>", "error": null }`

---

#### `auth_check_token`

检测指定系统 Token 有效性及剩余有效时间（秒）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"ops"` | 系统别名 |

**返回：** `{ "success": true, "data": { "valid": true, "expires_in": 79707 }, "error": null }`

---

#### `auth_is_authenticated`

检查当前是否已登录（session_id 存在且未过期）。无参数。

**返回：** `{ "success": true, "data": true, "error": null }`

---

#### `auth_token_refresh`

刷新指定系统 JWT，`system="__all__"` 时刷新全部系统。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"__all__"` | 系统别名，或 `__all__` |

---

#### `auth_system_list` / `auth_system_add` / `auth_system_remove` / `auth_system_sync`

管理系统注册表，覆盖 CLI 中的 `opscli auth system` 能力。

---

#### `auth_build_request_auth`

构造统一请求认证参数，返回 `headers` 与 `cookies`。

---

#### `auth_doctor`

返回登录状态与各系统连通性诊断结果。

---

### Skill 管理（skills_*）

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
| `skills_dir` | string | 否 | 指定扫描目录（默认自动检测） |

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

升级指定 Skill，目前主要用于 `ops-dataset-query`。

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
| `NOT_AUTHENTICATED` | 未登录，请先执行 `opscli auth login` |
| `DATASET_NOT_FOUND` | 未找到目标数据集，检查 alias 或 table_id |
| `QUERY_METADATA_NOT_READY` | 本地 metadata 未就绪，请先安装并升级 `ops-dataset-query` |
| `INVALID_PAYLOAD` | 参数格式不合法 |
| `REMOTE_HTTP_ERROR` | 远端 HTTP 请求失败 |
| `REMOTE_BUSINESS_ERROR` | 远端业务层返回失败 |
| `MCP_AUTH_ERROR` | 多用户模式下 API Key 缺失或无效 |

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
from fastmcp import Client
from opscli.mcp.server import mcp

async def main():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        result = await client.call_tool("auth_is_authenticated", {})
        print(result.data)

asyncio.run(main())
```

---

## 文件结构

```
opscli/mcp/
├── __init__.py     # 模块标识
├── auth_middleware.py # 多用户鉴权中间件
├── cli.py          # opscli mcp user 命令
├── context.py      # 多用户凭证目录解析
├── server.py       # FastMCP Server 定义，注册所有 Tools
└── user_store.py   # MCP 用户注册表
```

启动入口由 `pyproject.toml` 的 `[project.scripts]` 注册：

```toml
opscli-mcp = "opscli.mcp.server:run"
```
