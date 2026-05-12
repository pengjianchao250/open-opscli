# MCP 一步登录设计方案

> 版本：v1.1
> 日期：2026-05-12
> 状态：待实施

---

## 一、背景与目标

### 1.1 现有问题

当前 MCP 模式下，AI Agent 登录需经过两步 Tool 调用，且中间需要用户手动打开浏览器完成 OAuth 授权：

```
auth_login_start()   → 获取 verification_url + user_code
                       （需要用户打开浏览器，输入 user_code）
auth_login_poll()    → 轮询等待，最多调用 20 次，间隔 3-5 秒
```

**痛点：**
- AI Agent 无法自主完成登录，必须中断等待人工介入
- 轮询设计繁琐，AI Agent 需要自己管理轮询次数和退出条件
- MCP 连接已经携带 `X-MCP-API-Key`，该 Key 已绑定用户身份，重复走 OAuth 冗余

### 1.2 目标

在 MCP 模式下，利用连接层已有的 `X-MCP-API-Key` 直接完成身份绑定，**无需浏览器交互，一次 Tool 调用完成登录**。

### 1.3 非目标

- 不影响 CLI 模式的登录流程（`opscli auth login` 仍走 Device Flow）
- 不修改 `X-MCP-API-Key` 的发放和管理逻辑

---

## 二、新登录流程设计

### 2.1 流程概览

```
opscli (MCP Tool: auth_mcp_login)         OPS 后端                    DB (ops_user)
         │                                      │                           │
  Step1  │── POST /v1/cli/device/code ─────────►│── INSERT cli_device_codes►│
         │◄── { device_code, user_code } ────────│   (status=pending)        │
         │                                      │                           │
  Step2  │── POST /v1/mcp/auth/login ──────────►│                           │
         │   Header: X-MCP-API-Key: <key>        │── SELECT mcp_api_keys ───►│
         │   Body: {                             │◄── { user_id, email } ────│
         │     device_code: "xxx",               │── SELECT cli_device_codes►│
         │     user_code:   "AB12CD",            │◄── { pending record } ────│
         │     agent_name:  "Claude Code"        │   (校验 device_code +     │
         │   }                                   │    user_code 均匹配)      │
         │                                      │── INSERT shared_login_    │
         │                                      │   sessions ──────────────►│
         │                                      │── UPDATE cli_device_codes►│
         │                                      │   (status=authorized)     │
         │                                      │── UPDATE mcp_api_keys     │
         │                                      │   (last_used_at)          │
         │◄── { status: "authorized",            │                           │
         │      session_id, email,               │                           │
         │      expires_at, agent_name }─────────│                           │
         │                                      │                           │
  Step3  │  save_session(session_id, ...)        │                           │
         │  invalidate_credential_cache()        │                           │
         │◄── { success: true,                   │                           │
         │      saved_locally: true }            │                           │
```

### 2.2 与现有流程对比

| 维度 | 旧流程（MCP） | 新流程（MCP） |
|------|-------------|-------------|
| Tool 调用次数 | 2～21 次 | 1 次 |
| 是否需要浏览器 | 是 | 否 |
| 用户操作 | 打开链接 + 输入验证码 | 无需操作 |
| 轮询逻辑 | AI Agent 自行管理 | 无需轮询 |
| 审计链路 | device_code → session_id | 保持不变 |
| agentName 记录 | 无 | 可选写入 |

---

## 三、数据库变更

### 3.1 `shared_login_sessions` 表新增字段

在 `polaris_ops_user` 库的 `shared_login_sessions` 表中新增 `agent_name` 字段，用于记录发起本次登录的 AI Agent 名称：

```sql
ALTER TABLE polaris_ops_user_qa.shared_login_sessions
    ADD COLUMN agent_name varchar(128) DEFAULT NULL COMMENT 'AI Agent 名称（MCP 模式下由 Agent 传入，如 Claude Code）'
    AFTER user_agent;
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_name` | `varchar(128) NULL` | AI Agent 名称，仅 MCP 模式写入；CLI 登录为 NULL |

> 其余表（`cli_device_codes`、`mcp_api_keys`、`auth_token_records`）无需改动。

---

## 四、后端实现（PHP）

### 4.1 新建控制器 `McpAuthController.php`

**文件路径：**
`app/Http/Controllers/Api/McpAuthController.php`

#### 接口规范

```
POST /v1/mcp/auth/login
```

**请求头：**

| Header | 必须 | 说明 |
|--------|------|------|
| `X-MCP-API-Key` | 是 | MCP 连接 API Key（也支持 `Authorization: Bearer <key>`） |

**请求 Body（JSON）：**

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `device_code` | string | 是 | Step1 调用 `/v1/cli/device/code` 返回的设备码（UUID） |
| `user_code` | string | 是 | Step1 同步返回的用户短码，与 `device_code` 联合校验，防止单独泄露 `device_code` 后被滥用 |
| `agent_name` | string | 否 | AI Agent 名称，如 `"Claude Code"`、`"Cursor"`，传入后写入 session 记录 |

**成功响应（HTTP 200）：**

```json
{
    "status":     "authorized",
    "session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "email":      "user@example.com",
    "expires_at": "2026-05-13T10:00:00+00:00",
    "agent_name": "Claude Code"
}
```

> `expires_at` 格式为 ISO 8601，时区 UTC，与 `auth_login_poll` 返回保持一致。
> `agent_name` 若未传入则不返回该字段（或返回 null）。

**错误响应汇总：**

| HTTP | `error` 字段 | 触发条件 |
|------|-------------|---------|
| 400 | `missing_device_code` | Body 未传 `device_code` |
| 400 | `missing_user_code` | Body 未传 `user_code` |
| 401 | `missing_api_key` | 未传 `X-MCP-API-Key` |
| 401 | `key_invalid_or_expired` | Key 不存在 / `is_active=0` / `expires_at` 已过期 |
| 401 | `user_disabled` | Key 关联用户不存在或被禁用 |
| 404 | `device_code_not_found` | `device_code` + `user_code` 联合查询无匹配记录 |
| 409 | `device_code_already_used` | `cli_device_codes.status` 不为 `pending`（防重放） |
| 410 | `device_code_expired` | `cli_device_codes.expires_at` 已过期 |
| 500 | `internal_error` | 数据库写入等意外错误 |

#### 服务端执行逻辑（伪代码）

```
1. 校验请求参数
   读取 X-MCP-API-Key（Header 优先，其次 query param）
   → 为空：return 401 missing_api_key
   $deviceCode = $request->input('device_code')
   → 为空：return 400 missing_device_code
   $userCode = $request->input('user_code')
   → 为空：return 400 missing_user_code

2. 校验 API Key
   McpApiKeyOrm::findByKey($apiKey)
   → 未找到 / is_active=0 / expires_at < now()：return 401 key_invalid_or_expired
   → 得到 $keyRecord（含 user_id）

3. 校验用户状态
   $user = User::find($keyRecord->user_id)
   → 不存在 / status=0：return 401 user_disabled
   → 得到 $email

4. 校验设备码（device_code + user_code 联合匹配，防止单一字段泄露被滥用）
   $deviceRecord = CliDeviceCode::where('device_code', $deviceCode)
                                 ->where('user_code', $userCode)
                                 ->first()
   → 不存在：return 404 device_code_not_found
   → status != 'pending'：return 409 device_code_already_used
   → expires_at < now()：return 410 device_code_expired

5. 开启数据库事务：
   a. $sessionId = Str::uuid()
   b. $expiresAt = now()->addMinutes(env('CLI_JWT_TTL', 1440))
   c. INSERT shared_login_sessions:
      { session_id, email, agent_name（可空）, expires_at, is_valid=1 }
   d. UPDATE cli_device_codes SET
      { status='authorized', session_id, email, updated_at=now() }
      WHERE device_code = $deviceCode AND user_code = $userCode
   e. UPDATE mcp_api_keys SET last_used_at = now()
      WHERE id = $keyRecord->id
   提交事务

6. return 200:
   { status: "authorized", session_id, email, expires_at, agent_name（可空） }
```

### 4.2 路由注册（`routes/api.php`）

在 `/v1/mcp` 公开路由组中追加：

```php
// MCP API Key 校验接口（供 MCP Server 远程调用，公开接口）
Route::prefix('mcp')->group(function () {
    Route::get('verify-key', [McpApiKeyController::class, 'verifyKey']);
    Route::post('auth/login', [McpAuthController::class, 'login']);  // 新增
});
```

---

## 五、opscli 改动（Python）

### 5.1 新增 Tool：`auth_mcp_login`

**文件：** `opscli/mcp/tools/auth.py`

**函数签名：**

```python
async def auth_mcp_login(agent_name: str | None = None) -> dict:
    """MCP 模式专用一步登录，无需浏览器交互。

    利用当前 MCP 连接的 X-MCP-API-Key 直接完成身份绑定和 Session 创建，
    整个过程全自动，无需用户打开浏览器或输入验证码。

    Args:
        agent_name: 可选，当前 AI Agent 名称（如 "Claude Code"、"Cursor"）。
                    传入后写入服务端 session 记录，便于多 Agent 环境下的登录来源追溯。

    返回结构与 auth_login_poll 授权成功时完全一致（含 saved_locally=True）。
    """
```

**内部执行步骤：**

```
Step 1: 调用 DeviceFlow.request_device_code()
        → POST /v1/cli/device/code
        → 得到 device_code

Step 2: 调用 POST /v1/mcp/auth/login
        Headers: X-MCP-API-Key（来自 _get_mcp_request_headers()）
        Body: {
          "device_code": device_code,
          "user_code":   user_code,     ← Step1 同步返回，与 device_code 配对使用
          "agent_name":  agent_name     ← 可空
        }
        → 得到 { status, session_id, email, expires_at }

Step 3: 与 auth_login_poll 授权成功路径完全相同：
        store = _get_isolated_store()
        store.save_session(session_id, email, expires_at)
        invalidate_credential_cache(base_dir=_get_credential_dir())
        result["saved_locally"] = True

Step 4: 返回 _ok(result)
```

**错误处理：**
- Step1 失败（网络、后端报错）→ `_err(exc)`
- Step2 返回 4xx → 解析 `error` 字段，包装为 `_err`，附带 `feedback` 草案
- Step3 本地存储失败 → `_err(exc)`，并写 `docs/change-log-pending.md` 兜底

### 5.2 移除旧工具的 MCP 注册

`auth_login_start` 和 `auth_login_poll` 从 `_ALL_TOOLS` 列表中移除，**不再注册到 MCP 工具集**：

```python
# 修改前
_ALL_TOOLS = [
    auth_login_start,
    auth_login_poll,
    auth_mcp_login,      # 新增
    auth_get_token,
    ...
]

# 修改后
_ALL_TOOLS = [
    auth_mcp_login,      # 替代旧有两个登录工具
    auth_get_token,
    ...
]
```

> `auth_login_start` 和 `auth_login_poll` 函数本身**保留不删除**，供 CLI 模式（`opscli auth login`）继续使用。

### 5.3 模块级 docstring 更新

`auth.py` 顶部注释中的工具列表需同步更新：

```
- auth_mcp_login        — MCP 模式一步登录（替代 auth_login_start + auth_login_poll）
```

---

## 六、安全考虑

| 风险 | 应对措施 |
|------|---------|
| `device_code` 单独泄露被滥用 | 接口要求 `device_code` + `user_code` 联合匹配，两者同时持有才可绑定 |
| `device_code` 被重复使用 | 服务端校验 `status != 'pending'` → 返回 409，防止重放攻击 |
| `device_code` 过期后被利用 | 服务端校验 `expires_at < now()` → 返回 410 |
| API Key 泄露后冒名登录 | `mcp_api_keys` 支持 `is_active` 禁用和 `rotate` 轮换；Key 被吊销后最多 60 秒生效（`_VERIFY_CACHE_TTL_SECONDS`） |
| 多进程并发重复创建 Session | 数据库事务 + `device_code` 唯一索引保证原子性 |
| `agent_name` 注入 | 服务端限制 `varchar(128)`，仅记录不执行 |

---

## 七、变更清单

### 后端（auto-scheduler）

| # | 类型 | 文件 / 位置 | 描述 |
|---|------|-----------|------|
| 1 | 新建 | `app/Http/Controllers/Api/McpAuthController.php` | 新增 `login()` 方法 |
| 2 | 修改 | `routes/api.php` | 在 `/v1/mcp` 组追加 `POST auth/login` 路由 |
| 3 | 新建 | `database/migrations/2026_05_12_000001_add_agent_name_to_shared_login_sessions_table.php` | `shared_login_sessions` 新增 `agent_name varchar(128) NULL` 字段 |

### 前端（opscli）

| # | 类型 | 文件 | 描述 |
|---|------|------|------|
| 4 | 新增函数 | `opscli/mcp/tools/auth.py` | 新增 `auth_mcp_login(agent_name)` |
| 5 | 修改列表 | `opscli/mcp/tools/auth.py` | `_ALL_TOOLS` 移除 `auth_login_start`、`auth_login_poll`，加入 `auth_mcp_login` |
| 6 | 修改注释 | `opscli/mcp/tools/auth.py` | 更新模块 docstring 工具列表 |

---

## 八、验收标准

### 后端

- [ ] `POST /v1/mcp/auth/login` 返回格式与 `auth_login_poll` 授权成功时完全一致
- [ ] API Key 无效/过期/禁用时返回 401，错误字段清晰
- [ ] `device_code` + `user_code` 任一不匹配时返回 404
- [ ] `device_code` 已被使用时返回 409（重放防护有效）
- [ ] `agent_name` 传入后写入 `shared_login_sessions.agent_name`
- [ ] `agent_name` 不传时字段为 NULL，不报错
- [ ] 并发两次相同 `device_code` 请求只有一次成功

### opscli

- [ ] `auth_mcp_login()` 单次调用即可完成登录，返回 `saved_locally: true`
- [ ] `auth_mcp_login(agent_name="Claude Code")` 正常传参
- [ ] MCP 工具列表中不再出现 `auth_login_start`、`auth_login_poll`
- [ ] 登录后 `auth_get_token` 可正常获取 JWT（session 有效）
- [ ] stdio 模式下，`auth_login_start` / `auth_login_poll` 仍可通过 CLI 调用

---

## 九、后续扩展（暂不实现）

- `agent_name` 可在运营后台按 Agent 维度统计登录来源分布
- `shared_login_sessions` 可扩展 `login_method` 字段区分 `device_flow` / `mcp_api_key`
- MCP Server 启动时可主动调用 `auth_mcp_login` 做预热登录（当前设计已支持）
