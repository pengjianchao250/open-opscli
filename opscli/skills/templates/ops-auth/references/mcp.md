---
name: ops-auth
mcp-version: v1.1.0
description: 通过 MCP Tool 管理 Aukeys 内部系统的 OAuth2 登录授权与 JWT Token（服务端持久化凭证，按 Agent 自动隔离）
---

# ops-auth (MCP 模式)

通过 MCP Tool 完成一步式登录授权、JWT 获取、Token 刷新和系统管理。**服务端自动持久化凭证**，凭证按 `API Key + Agent 工具名` 隔离存储，无需调用方手动管理 `session_id`。

---

## 何时使用本 Skill

以下场景应使用 `ops-auth` Skill（MCP 模式）：

- **首次登录**：在当前 Agent 工具中完成 OAuth2 一步式授权（`auth_mcp_login`）
- **Token 管理**：获取、校验、刷新各系统的 JWT
- **认证排查**：遇到 `NOT_AUTHENTICATED`、401、Token 过期等报错时
- **系统管理**：查看、添加、同步、移除已注册系统
- **其他 Skill 前置**：`ops-dataset-query`、`ops-amazon` 等 Skill 调用前先确认登录状态

---

## 关键概念

### 服务端持久化凭证架构

| 层级 | 作用 | 管理方式 |
|------|------|---------|
| **API Key** | 控制谁能连接 MCP 服务器 | 服务器自动生成，管理员分发 |
| **Agent 隔离目录** | 按 `API Key + Agent 名称` 区分凭证目录 | 服务器自动读取 MCP `initialize` 握手中的 `clientInfo.name` |
| **session_id** | 用户登录凭证（OAuth2 授权后获得） | 服务器写入隔离目录，工具调用时自动读取，**无需调用方传入** |
| **JWT** | 访问后端业务系统的 Token | 用 session_id 向后端换取；服务器自动缓存，**无需调用方传入** |

### Agent 自动隔离

同一 API Key 在不同 Agent 工具（Claude Code、Cursor、Cherry Studio 等）下连接 MCP 服务器时，服务器根据 MCP 协议 `initialize` 握手中的 `clientInfo.name` 自动计算各自独立的凭证目录：

```
~/.config/opscli/credentials_by_key/
    SHA256(api_key + "::" + "claude-code")[:16]/   ← Claude Code 独立凭证
    SHA256(api_key + "::" + "cursor")[:16]/         ← Cursor 独立凭证
    SHA256(api_key + "::" + "cherry-studio")[:16]/  ← Cherry Studio 独立凭证
```

**用户零配置**：无需手动传入 `agent_name`，服务器自动读取客户端标识。

**隔离效果**：在 Claude Code 登录后，切换到 Cursor 需要重新执行 `auth_mcp_login`，两者凭证完全独立。

### Token 三态（本地解析）

| 状态 | 条件 | 行为 |
|------|------|------|
| `valid` | 距过期 > 300s | 直接使用 |
| `expiring_soon` | 距过期 ≤ 300s | 调用 `auth_token_refresh` 刷新 |
| `expired` | 已过期 | 服务器清除本地缓存；需重新执行 `auth_mcp_login` |

---

## 内置系统

| 别名 | URL | 用途 |
|------|-----|------|
| `ops` | https://ops.api.xenkee.com | 运营系统，数据查询、Skill 升级等 |

---

## 快速参考

### 登录与状态检查

```python
# 发起一步式登录（服务端持久化凭证，无需管理 session_id）
auth_mcp_login()

# 检查当前登录状态（无需传 session_id，服务器自动读取本地凭证）
auth_is_authenticated()

# 环境检查 + 连通性诊断
auth_doctor()
```

### Token 操作

```python
# 获取 JWT（服务器自动从本地凭证读取 session_id）
auth_get_token(system="ops")

# 检查 JWT 有效期（纯本地解析）
auth_check_token(jwt="eyJhbG...")

# 刷新指定系统 JWT
auth_token_refresh(system="ops")

# 刷新所有系统
auth_token_refresh(system="__all__")
```

### 系统管理

```python
# 列出所有系统（不需要认证）
auth_system_list()

# 从 ops 同步系统列表（服务器自动读取凭证）
auth_system_sync()

# 添加自定义系统（不需要认证）
auth_system_add(alias="my-ops", url="https://ops-staging.aukeys.com")

# 移除自定义系统
auth_system_remove(alias="my-ops")
```

---

## 完整 Tool 参考

### `auth_mcp_login`

发起 OAuth2 一步式登录。服务端自动完成 Device Flow 轮询，将 `session_id` 写入当前 Agent 对应的凭证隔离目录，**无需浏览器 code 手动传参**。

**不需要认证**。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `agent_name` | string | 自动读取 | Agent 名称（审计用），默认从 `clientInfo.name` 自动获取，无需手动传入 |
| `timeout` | integer | `120` | 等待用户在浏览器完成授权的最长秒数 |

**登录流程（服务端自动完成）**：
1. 服务端向后端发起 Device Flow，返回验证 URL 和用户码
2. **提示用户**在浏览器打开 URL，输入 `user_code` 完成授权
3. 服务端自动轮询，授权成功后将 `session_id` 写入当前 Agent 的凭证目录
4. 后续所有工具调用无需传入 `session_id`，服务器自动读取

**返回示例**：
```json
{
  "success": true,
  "data": {
    "email": "user@aukeys.com",
    "session_id": "860b0636485b5188a2b9b4ed5210e736",
    "expires_at": "2026-05-13T10:00:00+00:00",
    "agent_name": "claude-code"
  },
  "error": null
}
```

```python
# 最简调用（agent_name 自动获取）
auth_mcp_login()

# 超时设置（默认 120 秒）
auth_mcp_login(timeout=180)
```

---

### `auth_get_token`

获取指定系统的有效 JWT。服务端自动从凭证目录读取 `session_id`，**无需传入**。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"ops"` | 系统别名（如 ops） |
| `session_id` | string | 自动读取 | 可选，显式传入时优先使用 |

**返回：** `{ "success": true, "data": "<JWT 字符串>", "error": null }`

```python
# 服务端自动读取凭证（推荐）
auth_get_token(system="ops")

# 显式传入 session_id（可选）
auth_get_token(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

### `auth_check_token`

检测 JWT 有效性及剩余有效时间（秒）。**纯本地解析 JWT payload**，不向后端发请求。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `jwt` | string | **必填** | JWT 字符串 |

**返回：** `{ "success": true, "data": { "valid": true, "expires_in": 86399 }, "error": null }`

```python
auth_check_token(jwt="eyJhbG...")
```

---

### `auth_is_authenticated`

检查当前登录状态（尝试用本地凭证获取 JWT）。服务端自动读取凭证目录，**无需传入 `session_id`**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | 可选，显式传入时优先使用 |

**返回：** `{ "success": true, "data": true, "error": null }`

```python
# 服务端自动读取凭证（推荐）
auth_is_authenticated()

# 显式传入 session_id（可选）
auth_is_authenticated(session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

### `auth_token_refresh`

刷新指定系统 JWT。服务端自动读取凭证，**无需传入 `session_id`**。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"__all__"` | 系统别名，或 `__all__` 刷新全部 |
| `session_id` | string | 自动读取 | 可选，显式传入时优先使用 |

```python
# 刷新单个系统
auth_token_refresh(system="ops")

# 刷新所有系统
auth_token_refresh(system="__all__")
```

---

### `auth_system_list`

列出所有已注册系统（builtin / local / ops_sync）。**不需要认证**。

```python
auth_system_list()
```

---

### `auth_system_sync`

从 ops 后端同步多实例系统列表。服务端自动读取凭证。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | 可选，显式传入时优先使用 |

```python
auth_system_sync()
```

---

### `auth_system_add`

手动添加自定义系统实例。**不需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alias` | string | 是 | 系统别名 |
| `url` | string | 是 | 系统 base URL |
| `key` | string | 否 | 存储键，默认由 alias 生成 |
| `token_endpoint` | string | `"/api/auth/cli-token"` | Token 端点 |

```python
auth_system_add(
    alias="my-ops",
    url="https://ops-staging.aukeys.com"
)
```

---

### `auth_system_remove`

移除手动添加的系统（内置系统 ops 不可移除）。**不需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alias` | string | 是 | 系统别名 |

```python
auth_system_remove(alias="my-ops")
```

---

### `auth_build_request_auth`

构造统一请求认证参数，返回 `headers` 与 `cookies`。服务端自动读取凭证。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"ops"` | 系统别名 |
| `session_id` | string | 自动读取 | 可选，显式传入时优先使用 |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

```python
# 服务端自动读取凭证（推荐）
auth_build_request_auth(system="ops")
```

---

### `auth_doctor`

检查登录状态与各系统连通性，返回结构化诊断结果。服务端自动读取凭证。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | 可选，显式传入时优先使用 |

```python
# 服务端自动读取凭证（推荐）
auth_doctor()
```

**返回示例**：
```json
{
  "success": true,
  "data": {
    "authenticated": true,
    "client_name": "claude-code",
    "systems": [
      { "alias": "ops", "url": "...", "reachable": true, "error": null }
    ]
  }
}
```

---

## 典型工作流

### 首次登录

```python
# 1. 发起一步式登录
result = auth_mcp_login()
# → 输出提示：请在浏览器打开 URL 并输入验证码
# → 服务端自动等待授权并保存凭证

# 2. 确认登录状态
auth_is_authenticated()

# 3. 环境诊断
auth_doctor()
```

### 日常 Token 使用

```python
# 获取 JWT（服务端自动读取凭证）
jwt = auth_get_token(system="ops")["data"]

# 检查 JWT 有效期
auth_check_token(jwt=jwt)

# 主动刷新
auth_token_refresh(system="ops")
```

### 构造请求认证参数

```python
# 获取 headers 和 cookies（用于手动向后端发请求）
result = auth_build_request_auth(system="ops")
headers = result["data"]["headers"]
cookies = result["data"]["cookies"]

# headers: {"Authorization": "Bearer eyJhbG..."}
# cookies: {"polarisUserToken": "860b0636485b5188a2b9b4ed5210e736"}
```

### 切换 Agent 工具后重新登录

由于凭证按 Agent 工具名隔离，切换到新 Agent 工具后需要重新登录：

```python
# 在新的 Agent 工具中（如从 Claude Code 切换到 Cursor）
# 先检查登录状态
auth_is_authenticated()
# → 返回 false 或 NOT_AUTHENTICATED（凭证与当前 Agent 不匹配）

# 重新登录
auth_mcp_login()
# → 服务端为当前 Agent 工具创建独立凭证目录并保存
```

---

## 常见错误排查

| 错误现象 | 解决方案 |
|---------|---------|
| `NOT_AUTHENTICATED` / 未登录 | 执行 `auth_mcp_login()` 完成登录 |
| 切换 Agent 工具后未登录 | 正常现象，凭证按 Agent 隔离；重新执行 `auth_mcp_login()` |
| JWT 过期 | `auth_token_refresh()`；如 session 也过期则重新 `auth_mcp_login()` |
| 系统不可达 | `auth_doctor()` 确认连通性 |
| 系统别名不存在 | `auth_system_list()` 查看可用别名 |
| 登录超时（浏览器 120s 内未完成授权）| 重新执行 `auth_mcp_login()` |
| 授权被拒绝 | 确认在浏览器点击了"允许"，重新执行 `auth_mcp_login()` |

---

## Token 生命周期常量

| 常量 | 值 | 说明 |
|------|----|------|
| `REFRESH_THRESHOLD` | 300s | 距过期 5 分钟内自动刷新 |
| `MAX_JWT_TTL` | 86400s | 最大 JWT 有效期（24小时） |
| `Device Flow 有效期` | 300s | 用户需在 5 分钟内完成浏览器授权 |

---

## 本地配置文件

```
~/.config/opscli/
├── config.ini                  # 可选，覆盖服务地址
├── systems.json                # 用户自定义 + ops_sync 系统列表
└── credentials_by_key/         # 凭证隔离目录（按 API Key + Agent 名自动创建）
    ├── <hash-claude-code>/     # Claude Code 凭证
    ├── <hash-cursor>/          # Cursor 凭证
    └── <hash-xxx>/             # 其他 Agent 凭证
```

**覆盖服务地址示例**（开发调试用）：

```ini
# ~/.config/opscli/config.ini
[systems]
ops_url = http://localhost/api
ops_system_url = http://ops.cm
ops_token_endpoint = /api/v1/auth/cli-token
```

---

## 与其他 Skill 的协作

`ops-auth` 是 `ops-dataset-query`、`ops-amazon` 等 Skill 的前置依赖。登录后无需传入 `session_id`：

```python
# 1. ops-auth: 确保已登录
auth_is_authenticated()
# 如未登录，执行 auth_mcp_login()

# 2. ops-dataset-query: 服务端自动读取凭证执行查询
query_build_and_run(
    table_id=1,
    dimensions=["channel_name"],
    metrics=["reviews_qty:SUM"]
    # 无需传 session_id
)
```

---

## 异常类型参考

| 异常类 | 含义 | 常见触发场景 |
|--------|------|------------|
| `NOT_AUTHENTICATED` | 未登录 / 本地凭证不存在 | 未执行 `auth_mcp_login` 就调用需要认证的 Tool |
| `TokenFetchError` | 获取 JWT 失败 | session_id 过期或后端服务异常 |
| `DeviceFlowExpiredError` | 授权码超时 | 300s 内未在浏览器完成授权 |
| `DeviceFlowDeniedError` | 用户拒绝授权 | 浏览器点击"拒绝" |
| `SystemNotFoundError` | 系统别名不存在 | `system` 参数传了未注册的别名 |
| `NetworkError` | 网络连接异常 | 无法访问后端服务 |
