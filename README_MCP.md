# opscli MCP Server

将 opscli 核心能力以 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 的形式暴露，AI Agent 可直接调用，无需通过 CLI subprocess。

**关键特性**：
- **OPS 管控的 API Key**：每个用户拥有独立的 API Key，由 OPS 后端生成、校验和管理
- **凭证物理隔离**：按 API Key SHA256 哈希隔离凭证存储，彻底杜绝用户间 session 串用
- **自动远程校验**：HTTP/SSE 模式默认自动连接 OPS 后端校验 API Key，无需手动配置地址
- **无状态设计**：服务器本身不保存 OAuth 凭证，所有认证信息由调用方传入或在隔离目录中暂存
- **按需授权**：调用敏感 Tool 时自动触发 Device Flow，用户在浏览器完成授权

---

## 架构概览

### 多用户模式（推荐，生产环境）

```
用户 A（OpenCode / AI Agent）
  → headers: Authorization: Bearer mcp_usr_a_xxx...  （A 的独立 API Key）
    → MCP 服务器
      → 远程校验：调用 OPS /v1/mcp/verify-key 确认 Key 有效
        → 校验通过 → 将 API Key 注入请求上下文
          → 凭证操作：读写 ~/.config/opscli/credentials_by_key/<hash_a>/
            → Tool 参数: session_id + jwt（可选）
              → 后端 ops / polaris（最终鉴权）

用户 B（OpenCode / AI Agent）
  → headers: Authorization: Bearer mcp_usr_b_xxx...  （B 的独立 API Key）
    → MCP 服务器
      → 远程校验：同上
        → 校验通过 → 凭证操作：读写 ~/.config/opscli/credentials_by_key/<hash_b>/
          → 与 A 的凭证物理隔离，互不干扰
```

### 单用户模式（向后兼容）

```
用户（OpenCode / AI Agent）
  → headers: Authorization: Bearer opscli-mcp-xxx  （服务器自动生成的固定 Key）
    → MCP 服务器（固定 Key 比对，无远程校验）
      → 凭证操作：读写 ~/.config/opscli/credentials.bin
```

**安全分层**：
1. **API Key**（连接鉴权）：控制谁能连接到 MCP 服务器
   - 多用户模式：由 OPS 后端生成，每个用户独立，支持过期/禁用/轮换
   - 单用户模式：服务器自动生成固定 Key，管理员分发给用户
2. **session_id / JWT**（业务鉴权）：控制谁能访问后端业务数据，通过 Device Flow 授权获得
3. **凭证隔离**：多用户模式下按 API Key 哈希将凭证存储到独立目录，物理隔离

---

## 安装依赖

```bash
pip install aukeys-opscli
# 或本地开发环境
uv pip install -e .
```

---

## 启动 MCP 服务器

### 多用户模式（推荐，生产环境）

HTTP/SSE 模式默认启用 OPS 远程校验，从 `config.ini` 自动读取 `ops_system_url`：

```bash
opscli-mcp --transport both --port 8765
```

启动后自动输出：

```
[opscli-mcp] 服务已启动（模式：both）
[opscli-mcp] 远程校验模式：http://ops.cm/v1/mcp/verify-key
[opscli-mcp] 每个用户需使用独立的 API Key（由 OPS 后端生成）

鉴权方式（选其一）：
  Authorization: Bearer <your-api-key>
  ?api_key=<your-api-key>

SSE 端点（兼容 Cursor / Claude Desktop 等）：
  http://0.0.0.0:8765/sse
  http://0.0.0.0:8765/messages/  （SSE 消息投递）

Streamable HTTP 端点（ChatGPT / OpenAI Apps SDK 推荐）：
  http://0.0.0.0:8765/mcp
```

**如需覆盖默认校验地址**：
```bash
opscli-mcp --transport both --port 8765 \
  --auth-verify-url https://custom-domain.com/v1/mcp/verify-key
```

**后台运行**：
```bash
nohup opscli-mcp --transport both --port 8765 > /tmp/opscli-mcp.log 2>&1 &
```

### 单用户模式（向后兼容，开发测试）

不配置 `ops_system_url` 或显式不提供 `--auth-verify-url` 且无法从 `config.ini` 读取时，自动回退到单用户固定 API Key 模式：

```bash
opscli-mcp --transport sse --host 127.0.0.1 --port 8765
```

启动后会在控制台输出自动生成的 API Key：

```
[opscli-mcp] 服务已启动（模式：sse）
[opscli-mcp] 固定 API Key: opscli-mcp-H0BWl9L8PC84OSBMRzGW1psUJ0L2aaqd
```

- 首次启动时自动生成，持久化保存在 `~/.config/opscli/mcp_api_key`
- 重启后自动复用同一 API Key
- 文件权限 `600`（仅所有者可读写）
- 删除该文件后下次启动会重新生成

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

## OPS 后端 API Key 管理

### 生成 API Key

用户登录 OPS 后调用（需 JWT）：

```http
POST /v1/mcp-api-keys
Content-Type: application/json
Authorization: Bearer <jwt>

{
  "name": "我的 OpenCode Key",
  "expires_in_days": 90
}
```

**返回（明文 Key 仅展示一次）**：
```json
{
  "success": true,
  "data": {
    "api_key": "mcp_usr_a1b2c3d4e5f6...",
    "name": "我的 OpenCode Key",
    "expires_at": "2026-08-07T12:00:00Z",
    "warning": "API Key 仅展示一次，请妥善保存。"
  }
}
```

### 管理 API Key

| 操作 | 路由 | 说明 |
|------|------|------|
| 列表 | `GET /v1/mcp-api-keys` | 查看当前用户的所有 Key |
| 删除 | `DELETE /v1/mcp-api-keys/{id}` | 删除指定 Key |
| 启用/禁用 | `POST /v1/mcp-api-keys/{id}/toggle` | 切换 Key 状态 |
| 轮换 | `POST /v1/mcp-api-keys/{id}/rotate` | 删除旧 Key，生成新 Key |

### 校验接口（供 MCP Server 调用）

```http
GET /v1/mcp/verify-key?api_key=mcp_usr_xxx...
X-MCP-API-Key: mcp_usr_xxx...
```

**返回**：
```json
{
  "valid": true,
  "user_id": 101,
  "email": "user@example.com",
  "name": "张三"
}
```

---

## 客户端连接配置

### OpenCode（多用户模式）

编辑 `~/.config/opencode/opencode.json`：

```json
{
  "mcp": {
    "opscli": {
      "type": "remote",
      "url": "http://127.0.0.1:8765/sse",
      "headers": {
        "Authorization": "Bearer mcp_usr_a1b2c3d4e5f6..."
      },
      "enabled": true
    }
  }
}
```

> 每个用户需要使用 **自己独立的 API Key**（从 OPS 后端生成）。
>
> **Query 方式**（兼容模式）：如果客户端不支持自定义 headers：
> ```json
> {
>   "url": "http://127.0.0.1:8765/sse?api_key=mcp_usr_xxx..."
> }
> ```
>
> ⚠️ **注意**：标准 MCP SSE 客户端在建立 SSE 连接后，会通过独立的 HTTP POST 发送消息。
> 部分客户端不会自动将 query param 带到 POST 请求中，导致消息发送 401。
> **推荐优先使用 Header 方式**，Query 方式主要用于浏览器直接访问或特殊客户端场景。

### OpenCode（单用户模式，向后兼容）

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
- Headers 填 `{"Authorization": "Bearer mcp_usr_xxx..."}`（多用户）或固定 Key（单用户）
- 点击 Connect 即可交互调用所有 Tools

---

## ChatGPT / OpenAI 兼容模式

opscli MCP 服务器已实现 OpenAI [Company Knowledge](https://openai.com/index/introducing-company-knowledge/) 和 [Deep Research](https://platform.openai.com/docs/mcp) 兼容的两个标准工具：

| 工具 | 说明 | 是否需要认证 |
|------|------|------------|
| `search` | 在本地数据集和字段索引中搜索 | 否（本地数据） |
| `fetch` | 获取指定数据集/字段的详细信息 | 否（本地数据） |

**search** 返回格式（Company Knowledge 标准）：
```json
{
  "results": [
    {"id": "dataset:alias", "title": "数据集名称", "url": "opscli://dataset/alias"},
    {"id": "field:dataset.field", "title": "字段显示名", "url": "opscli://field/dataset.field"}
  ]
}
```

**fetch** 返回格式（Company Knowledge 标准）：
```json
{
  "id": "dataset:alias",
  "title": "数据集名称",
  "text": "数据集描述...",
  "url": "opscli://dataset/alias",
  "metadata": {"type": "dataset", "dimensions_count": 10, "metrics_count": 5}
}
```

### 在 ChatGPT 中连接

1. 部署 MCP 服务器到公网 HTTPS 端点（ChatGPT 要求 HTTPS）
2. 在 ChatGPT 开发者模式中创建 Connector，填写 SSE URL：
   ```
   https://your-domain.com/sse
   ```
3. ChatGPT 会自动识别 `search` 和 `fetch` 工具，将其纳入 Company Knowledge 源

### 工具注解（Annotations）

两个工具均标记为只读（`readOnlyHint: true`），符合 Company Knowledge 对安全性的要求：
- `readOnlyHint: true` — 仅检索信息，不修改数据
- `openWorldHint: false` — 仅影响 bounded target（本地数据集索引）
- `destructiveHint: false` — 无删除或不可逆副作用

---

## 授权流程（Device Flow）

MCP Server 不保存用户 OAuth 凭证到全局位置，而是按 API Key 隔离存储。**每次调用需要认证的 Tool 时，优先传入 `session_id`**（和可选的 `jwt`）。

### 典型授权流程

```text
1. 用户首次调用 query_build_and_run(...)
   → 错误："无 session_id：请完成授权登录"

2. AI 自动调用 auth_login_start()
   → 返回 {verification_url, user_code, device_code, interval}

3. 用户在浏览器中打开 verification_url，输入 user_code

4. AI 按 interval 轮询 auth_login_poll(device_code)
   → 返回 {status: "authorized", session_id, email, expires_at}
   → MCP Server 按当前 API Key 隔离保存 session

5. AI 将 session_id 保存到当前对话上下文

6. 自动重试 query_build_and_run(session_id=xxx)
   → 成功返回数据
```

### 同一用户换设备

由于凭证按 API Key 隔离存储在 MCP Server 本地，**同一 API Key 换设备、换浏览器、清缓存后无需重新授权**：

```text
设备 A：授权 → session 保存到 credentials_by_key/<hash>/
设备 B：同一 API Key → 直接读取 credentials_by_key/<hash>/ → 无需重新授权
```

### 凭证刷新

- **JWT 即将过期**：AI 调用 `auth_token_refresh(session_id)` 自动换取新 JWT
- **session_id 过期**：返回 `NOT_AUTHENTICATED` 错误，AI 提示用户重新执行 Device Flow 授权

---

## 凭证存储路径

### 多用户模式

```
~/.config/opscli/
├── credentials_by_key/
│   ├── a1b2c3d4e5f6.../     ← API Key "mcp_usr_a" 的 SHA256 哈希
│   │   └── credentials.bin  ← 用户 A 的 session + JWT（AES-256-GCM 加密）
│   ├── b2c3d4e5f6a7.../     ← API Key "mcp_usr_b" 的 SHA256 哈希
│   │   └── credentials.bin  ← 用户 B 的 session + JWT
│   └── ...
└── mcp_api_key              ← 单用户模式下的固定 Key（多用户模式下不使用）
```

### 单用户模式（向后兼容）

```
~/.config/opscli/
├── credentials.bin          ← 所有用户共享（已废弃，仅 stdio/单用户模式保留）
└── mcp_api_key              ← 固定 API Key
```

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

#### `query_chart_doc`

通过 chart_uuid 生成图表 API 调用 Markdown 文档，包含查询结构、字段映射、过滤规则与样例。**需要认证**。

文档包含七大章节：使用方式、关键术语、图表概览、API 调用流程、字段明细表、过滤规则、查询拆解与样例。适合 Skill / AI Agent 直接消费。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `chart_uuid` | string | 是 | 图表唯一标识 |
| `output_path` | string | 否 | 将 Markdown 写入指定文件路径 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

**返回示例：**
```json
{
  "success": true,
  "data": {
    "chart_uuid": "32f660fd-f62a-45c4-a443-e21f2edb0779",
    "markdown": "# 图表查询 API 开发文档\n...",
    "query_count": 3,
    "dataset_aliases": ["sales_order_d"],
    "dataset_count": 1,
    "output_path": "/path/to/chart-doc.md"
  },
  "error": null
}
```

**典型用法：**
```python
# 生成图表文档（Markdown 在返回数据中）
query_chart_doc(
  chart_uuid="32f660fd-f62a-45c4-a443-e21f2edb0779",
  session_id="860b0636485b5188a2b9b4ed5210e736",
)

# 生成文档并写入本地文件
query_chart_doc(
  chart_uuid="32f660fd-f62a-45c4-a443-e21f2edb0779",
  output_path="/tmp/chart-doc.md",
  session_id="860b0636485b5188a2b9b4ed5210e736",
)
```

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

单次轮询 Device Flow 授权状态。授权成功后按当前 API Key 隔离保存 session。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `device_code` | string | 必填 | `auth_login_start` 返回的设备码 |
| `timeout` | integer | `10` | 单次 HTTP 请求超时，最大 30 秒 |

**状态说明**：
- `pending`：等待用户授权
- `authorized`：授权成功，返回 `session_id` / `email` / `expires_at`，**并隔离保存**
- `expired`：设备码超时
- `denied`：用户拒绝授权

---

#### `auth_get_token`

获取指定系统的有效 JWT。**必须传入 `session_id`**，服务器直接用其向后端请求 JWT。

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

刷新指定系统 JWT。必须有 `session_id`。刷新后的 JWT 按 API Key 隔离保存。

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

#### `auth_logout`

清除当前 API Key 隔离目录下的 session 和 JWT（退出登录）。**不影响其他用户的凭证**。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"__all__"` | `"__all__"` 清除所有系统，或指定系统别名 |

---

#### `auth_doctor`

检查 session 有效性与各系统连通性，返回结构化诊断结果（按 API Key 隔离读取凭证概览）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | 传入时检查该 session 有效性 |

---

### Skill 管理（skills_*）

Skill 相关 Tool **不需要认证**（远程安装需先完成 ops 登录以获取下载授权）。

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

安装 Skill。支持内置模板（`name` 传技能名）和技能广场远程安装（`name` 传 `username@skill_name` 格式）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | Skill 名称（如 `ops-auth`）或广场标识符（如 `pengjianchao@ops-auth`） |
| `skills_dir` | string | 否 | 指定安装目录 |
| `runtime` | string | 否 | `claude`、`openclaw`、`codex`、`opencode`、`all` |
| `force` | boolean | 否 | 是否覆盖已有安装 |

远程安装时（`name` 含 `@`），自动解压 zip 到 `~/.opscli/skills/` 并软链接到全局 AI 工具目录。

---

#### `skills_upgrade`

升级指定 Skill 到远端最新版本。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 默认 `ops-dataset-query` |
| `skills_dir` | string | 否 | 指定扫描目录 |
| `force` | boolean | 否 | 是否强制升级 |

---

#### `skills_marketplace_list`

浏览技能广场列表，支持关键词搜索和分类筛选。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keyword` | string | 否 | 搜索关键词 |
| `category_id` | integer | 否 | 按分类 ID 筛选 |
| `sort` | string | 否 | 排序字段：`downloads`（默认）/ `rating` / `created_at` |
| `order` | string | 否 | 排序方向：`desc`（默认）/ `asc` |
| `page` | integer | 否 | 页码，默认 1 |
| `limit` | integer | 否 | 每页条数，默认 20 |

**返回示例：**
```json
{
  "success": true,
  "data": {
    "list": [
      {
        "id": 1,
        "identifier": "pengjianchao@ops-auth",
        "title": "Ops 认证授权",
        "description": "...",
        "install_count": 42,
        "rating": 4.8
      }
    ],
    "total": 1
  },
  "error": null
}
```

---

#### `skills_marketplace_info`

获取指定技能的详细信息，包含元数据、版本列表和下载统计。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `identifier` | string | 是 | 技能标识符，格式 `username@skill_name` |

---

#### `skills_record_usage`

记录技能使用事件（异步上报，不阻塞主流程）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skill_name` | string | 是 | Skill 名称 |
| `event` | string | 否 | 事件类型，默认 `use` |

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

API_KEY = "mcp_usr_a1b2c3d4e5f6..."  # 从 OPS 后端生成
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
├── __init__.py              # 模块标识
├── auth_middleware.py       # SSE/HTTP 层 API Key 鉴权（固定 Key / 远程校验）
├── cli.py                   # opscli mcp user 命令（遗留兼容）
├── context.py               # contextvars 请求上下文（API Key / user_id / email）
├── credential_cache.py      # 凭证内存缓存（支持多用户隔离）
├── key_based_storage.py     # API Key 哈希目录映射（凭证物理隔离）
├── server.py                # FastMCP Server 定义，注册所有 Tools
├── user_store.py            # MCP 用户注册表（遗留兼容）
└── tools/
    ├── helpers.py            # 共享辅助函数（按 API Key 隔离读取凭证）
    ├── auth.py               # 认证工具（隔离保存 session / JWT）
    ├── query.py              # 数据查询工具
    └── skills.py             # Skill 管理工具（含广场 list/info/record_usage）
```

启动入口由 `pyproject.toml` 的 `[project.scripts]` 注册：

```toml
opscli-mcp = "opscli.mcp.server:run"
```

---

## 常见问题

### Q1: 为什么 HTTP/SSE 模式下默认启用远程校验？

原设计使用固定 API Key + 共享 `credentials.bin`，在多用户共享同一 MCP Server 时会导致严重的 session 串用安全问题（后登录的用户直接复用前一个用户的 session）。多用户模式下每个用户拥有独立的 API Key，凭证按 Key 哈希物理隔离，彻底杜绝串用。

### Q2: stdio 模式会被影响吗？

不会。stdio 模式（如 Claude Desktop）没有 HTTP 层，不经过 `ApiKeyAuthMiddleware`，也不存在多用户共享问题，保持原有行为不变。

### Q3: 同一 API Key 换设备需要重新授权吗？

不需要。凭证存储在 MCP Server 本地（按 API Key 隔离的目录中），不是存在用户的浏览器里。同一 API Key 在任意设备、任意浏览器访问时，都会读取同一个隔离目录中的 session。

### Q4: API Key 泄露了怎么办？

在 OPS 后端立即禁用或删除该 Key：
```http
POST /v1/mcp-api-keys/{id}/toggle   # 禁用
DELETE /v1/mcp-api-keys/{id}        # 删除
```

MCP Server 的远程校验会立即拒绝该 Key 的后续请求。同时建议轮换 Key（生成新 Key）。

### Q5: 如何回退到单用户固定 API Key 模式？

确保 `config.ini` 中没有配置 `ops_system_url`（或配置为无效地址），且启动时不提供 `--auth-verify-url`，服务器会自动回退到单用户模式，生成并使用固定 API Key。
