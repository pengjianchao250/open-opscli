---
name: ops-auth
mcp-version: v1.0.0
description: 通过 MCP Tool 管理 Aukeys 内部系统的 OAuth2 Device Flow 登录授权与 JWT Token（无状态模式）
---

# ops-auth (MCP 无状态模式)

通过 MCP Tool 完成 Device Flow 授权、JWT 获取、Token 刷新和系统管理。**服务器不保存任何用户凭证**，所有 session_id / jwt 由调用方管理。

---

## 何时使用本 Skill

以下场景应使用 `ops-auth` Skill：

- **首次登录**：需要通过 Device Flow 完成 OAuth2 授权
- **Token 管理**：获取、校验、刷新各系统的 JWT
- **认证排查**：遇到 401、未登录、Token 过期等认证报错时
- **系统管理**：查看、添加、同步、移除已注册系统
- **其他 Skill 前置**：`ops-dataset-query`、`ops-amazon` 等 Skill 调用前必须先确认 session 有效

---

## 关键概念

### 无状态架构

| 层级 | 作用 | 管理方式 |
|------|------|---------|
| **API Key** | 控制谁能连接 MCP 服务器 | 服务器自动生成，管理员分发 |
| **session_id** | 用户登录凭证（Device Flow 授权后获得） | 由调用方（AI 对话上下文）保存和管理 |
| **JWT** | 访问后端业务系统的 Token | 用 session_id 实时向后端换取，不过期自动刷新 |

### Token 三态（本地解析）

| 状态 | 条件 | 行为 |
|------|------|------|
| `valid` | 距过期 > 300s | 直接使用 |
| `expiring_soon` | 距过期 ≤ 300s | 调用 `auth_token_refresh` 刷新 |
| `expired` | 已过期 | session 可能也过期，需重新 Device Flow 授权 |

### 凭证管理

- **服务器不保存**：MCP 服务器无 CredentialStore，不读写 `~/.config/opscli/credentials.bin`
- **AI 上下文保存**：`session_id` 保存在当前 AI 对话上下文中
- **用户本地保存**：可选将 `session_id` 写入 `~/.config/opencode/opscli-session.json`，跨对话复用

---

## 内置系统

| 别名 | System Key | URL | 用途 |
|------|-----------|-----|------|
| `ops` | ops | https://ops.api.qa.aukeyit.com | 运营系统，数据查询、Skill 升级等 |
| `polaris` | polaris_sys | https://bi.aukeys.com | 刊登系统 |

---

## 快速参考

### 登录与状态检查

```python
# 发起 Device Flow（服务器不保存，返回 session_id 由调用方管理）
auth_login_start()

# 检查 session 有效性（用 session_id 尝试换取 JWT）
auth_is_authenticated(session_id="860b0636485b5188a2b9b4ed5210e736")

# 环境检查 + 连通性诊断
auth_doctor(session_id="860b0636485b5188a2b9b4ed5210e736")
```

### Token 操作

```python
# 获取 JWT（必须用 session_id，服务器实时向后端换取）
auth_get_token(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")

# 检查 JWT 有效期（纯本地解析，不向后端发请求）
auth_check_token(jwt="eyJhbG...")

# 主动刷新单个系统
auth_token_refresh(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")

# 刷新所有系统
auth_token_refresh(system="__all__", session_id="860b0636485b5188a2b9b4ed5210e736")
```

### 系统管理

```python
# 列出所有系统（不需要认证）
auth_system_list()

# 从 ops 同步系统列表（需要 session_id）
auth_system_sync(session_id="860b0636485b5188a2b9b4ed5210e736")

# 添加自定义系统（不需要认证）
auth_system_add(alias="my-ops", url="https://ops-staging.aukeys.com")

# 移除自定义系统（不需要认证）
auth_system_remove(alias="my-ops")
```

---

## 完整 Tool 参考

### `auth_login_start`

发起 Device Flow 授权（RFC 8628）。**服务器不保存 session**，授权成功后返回的 `session_id` 由调用方管理。

**不需要认证**。

**返回示例**：
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

**登录流程**：
1. 调用 `auth_login_start()` 获取设备码和验证 URL
2. 提示用户在浏览器打开 `verification_url`，输入 `user_code`
3. 按 `interval`（秒）轮询 `auth_login_poll(device_code)`
4. 用户授权后返回 `session_id`、`email`、`expires_at`
5. **调用方保存 `session_id`**，后续所有 Tool 调用传入

```python
auth_login_start()
```

---

### `auth_login_poll`

单次轮询 Device Flow 授权状态。**服务器不保存 session**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `device_code` | string | 必填 | `auth_login_start` 返回的设备码 |
| `timeout` | integer | `10` | 单次 HTTP 请求超时，最大 30 秒 |

**状态说明**：
- `pending`：等待用户授权
- `authorized`：授权成功，返回 `session_id` / `email` / `expires_at`
- `expired`：设备码超时（300 秒内未完成授权）
- `denied`：用户拒绝授权

```python
auth_login_poll(device_code="xxx", timeout=10)
```

---

### `auth_get_token`

获取指定系统的有效 JWT。**无状态模式下必须传入 `session_id`**，服务器直接用其向后端请求 JWT，不读取本地存储。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"ops"` | 系统别名（ops、polaris 等） |
| `session_id` | string | **必填** | 用户授权后获得的 session_id |

**返回：** `{ "success": true, "data": "<JWT 字符串>", "error": null }`

```python
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

检查 session_id 是否有效（尝试用其获取 JWT）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | **必填** | 用户授权后获得的 session_id |

**返回：** `{ "success": true, "data": true, "error": null }`

```python
auth_is_authenticated(session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

### `auth_token_refresh`

刷新指定系统 JWT。必须有 `session_id`。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"__all__"` | 系统别名，或 `__all__` 刷新全部 |
| `session_id` | string | **必填** | 用户授权后获得的 session_id |

```python
# 刷新单个系统
auth_token_refresh(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")

# 刷新所有系统
auth_token_refresh(system="__all__", session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

### `auth_system_list`

列出所有已注册系统（builtin / local / ops_sync）。**不需要认证**。

```python
auth_system_list()
```

---

### `auth_system_sync`

从 ops 后端同步多实例系统列表。需要 `session_id`。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | **必填** | 用户授权后获得的 session_id |

```python
auth_system_sync(session_id="860b0636485b5188a2b9b4ed5210e736")
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
# 添加 staging 环境
auth_system_add(
    alias="my-ops",
    url="https://ops-staging.aukeys.com"
)
```

---

### `auth_system_remove`

移除手动添加的系统（内置系统 ops / polaris 不可移除）。**不需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alias` | string | 是 | 系统别名 |

```python
auth_system_remove(alias="my-ops")
```

---

### `auth_build_request_auth`

构造统一请求认证参数，返回 `headers` 与 `cookies`。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | string | `"ops"` | 系统别名 |
| `session_id` | string | **必填** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

**返回：** `{ "success": true, "data": { "headers": {...}, "cookies": {...} }, "error": null }`

```python
auth_build_request_auth(
    system="ops",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

---

### `auth_doctor`

检查 session 有效性与各系统连通性，返回结构化诊断结果。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | 传入时检查该 session 有效性 |

```python
auth_doctor(session_id="860b0636485b5188a2b9b4ed5210e736")
```

**返回示例**：
```json
{
  "success": true,
  "data": {
    "authenticated": true,
    "systems": [
      { "alias": "ops", "url": "...", "reachable": true, "error": null },
      { "alias": "polaris", "url": "...", "reachable": false, "error": "..." }
    ]
  }
}
```

---

## 典型工作流

### 入门：首次 Device Flow 授权

```python
# 1. 发起 Device Flow
result = auth_login_start()
device_code = result["data"]["device_code"]
user_code = result["data"]["user_code"]
interval = result["data"]["interval"]

# 2. 提示用户：请在浏览器打开 URL，输入 user_code
#    URL: https://ops.api.qa.aukeyit.com/cli-auth
#    验证码: user_code

# 3. 轮询等待授权
import time
for i in range(30):
    time.sleep(interval)
    poll = auth_login_poll(device_code=device_code, timeout=10)
    status = poll["data"]["status"]
    if status == "authorized":
        session_id = poll["data"]["session_id"]
        print(f"授权成功! session_id: {session_id}")
        break
    elif status in ("expired", "denied"):
        print(f"授权失败: {status}")
        break

# 4. 确认登录状态
auth_is_authenticated(session_id=session_id)

# 5. 环境诊断
auth_doctor(session_id=session_id)
```

### 进阶：Token 管理

```python
# 获取 JWT
jwt = auth_get_token(system="ops", session_id=session_id)["data"]

# 检查 JWT 有效期
auth_check_token(jwt=jwt)

# 主动刷新
auth_token_refresh(system="ops", session_id=session_id)

# 刷新后重新获取
new_jwt = auth_get_token(system="ops", session_id=session_id)["data"]
```

### 高级：构造请求认证参数

```python
# 获取 headers 和 cookies（用于手动向后端发请求）
result = auth_build_request_auth(system="ops", session_id=session_id)
headers = result["data"]["headers"]
cookies = result["data"]["cookies"]

# headers: {"Authorization": "Bearer eyJhbG..."}
# cookies: {"polarisUserToken": "860b0636485b5188a2b9b4ed5210e736"}
```

---

## 常见错误排查

| 错误现象 | 解决方案 |
|---------|---------|
| `NOT_AUTHENTICATED` / session_id 无效 | 重新执行 Device Flow：`auth_login_start()` → 浏览器授权 → `auth_login_poll()` |
| JWT 过期 | `auth_token_refresh(session_id)`；如 session 也过期则重新授权 |
| 系统不可达 | `auth_doctor(session_id)` 确认连通性 |
| 系统别名不存在 | `auth_system_list()` 查看可用别名 |
| Device Flow 超时（> 300s）| 重新执行 `auth_login_start()` |
| 授权被拒绝 | 确认在浏览器页面点击了"允许"，重新执行 `auth_login_start()` |

---

## Token 生命周期常量

| 常量 | 值 | 说明 |
|------|----|------|
| `REFRESH_THRESHOLD` | 300s | 距过期 5 分钟内自动刷新 |
| `MAX_JWT_TTL` | 86400s | 最大 JWT 有效期（24小时） |
| `Device Flow 有效期` | 300s | 用户需在 5 分钟内完成浏览器授权 |

---

## 本地配置文件

无状态模式下，服务器不保存 OAuth 凭证，但以下配置文件仍可用于自定义：

```
~/.config/opscli/
├── config.ini         # 可选，覆盖服务地址
├── systems.json       # 用户自定义 + ops_sync 系统列表
└── mcp_api_key        # MCP 服务固定 API Key（仅服务器端使用）
```

**覆盖服务地址示例**（开发调试用）：

```ini
# ~/.config/opscli/config.ini
[systems]
ops_url = http://localhost/api
ops_system_url = http://ops.cm
ops_token_endpoint = /api/v1/auth/cli-token
polaris_system_url = http://po2.cm
polaris_token_endpoint = /api/auth/cli-token
```

---

## 跨对话复用 session_id

AI 对话结束后 `session_id` 丢失。如需跨对话复用，可保存到本地文件：

```python
# 保存（AI 在对话结束时执行）
import json
with open("~/.config/opencode/opscli-session.json", "w") as f:
    json.dump({"session_id": "860b0636485b5188a2b9b4ed5210e736"}, f)

# 恢复（新对话开始时读取）
import json
session_id = json.load(open("~/.config/opencode/opscli-session.json"))["session_id"]
```

> 目前 OpenCode 无标准机制，建议 AI 在对话中主动提示用户保存。

---

## 与其他 Skill 的协作

`ops-auth` 是 `ops-dataset-query`、`ops-amazon` 等 Skill 的前置依赖：

```python
# 1. ops-auth: 确保 session 有效
auth_is_authenticated(session_id="xxx")
# 如无效，重新 Device Flow 授权

# 2. ops-dataset-query: 使用同一 session_id 执行查询
query_build_and_run(
    table_id=1,
    dimensions=["channel_name"],
    metrics=["reviews_qty:SUM"],
    session_id="xxx"   # 同一 session_id
)

# 3. ops-amazon: 使用同一 session_id 抓取
amazon_scrape(
    asin="B09LCJPZ1P",
    session_id="xxx"   # 同一 session_id
)
```

---

## 异常类型参考

| 异常类 | 含义 | 常见触发场景 |
|--------|------|------------|
| `NOT_AUTHENTICATED` | 未登录 / session 无效 | 未执行 Device Flow 就调用需要认证的 Tool |
| `TokenFetchError` | 获取 JWT 失败 | session_id 过期或后端服务异常 |
| `DeviceFlowExpiredError` | 授权码超时 | 300s 内未在浏览器完成授权 |
| `DeviceFlowDeniedError` | 用户拒绝授权 | 浏览器点击"拒绝" |
| `SystemNotFoundError` | 系统别名不存在 | `system` 参数传了未注册的别名 |
| `NetworkError` | 网络连接异常 | 无法访问后端服务 |
