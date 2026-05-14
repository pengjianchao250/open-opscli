---
name: ops-auth
description: 管理 Aukeys 内部系统的 OAuth2 登录授权与 JWT Token
version: v1.0.0
---

# ops-auth

管理 Aukeys 内部系统的 OAuth2 登录授权与 JWT Token，所有操作通过 `opscli auth` 子命令执行。

> **知识来源**：本文档综合了代码库架构分析（codebase_analysis，高置信度）和官方命令参考文档（documentation，高置信度），两个来源一致，无冲突。

---

## 何时使用本 Skill

以下场景应使用 `ops-auth` Skill：

- **首次登录**：需要通过 Device Flow 完成 OAuth2 授权
- **Token 管理**：获取、校验、刷新各系统的 JWT
- **认证排查**：遇到 401、未登录、Token 过期等认证报错时
- **系统管理**：查看、添加、同步、移除已注册系统
- **脚本集成**：在 shell 脚本中获取 JWT 传递给其他命令
- **Python SDK 集成**：通过 `AuthClient` 在代码中直接获取认证信息
- **多环境切换**：添加自定义系统实例（如 staging 环境）

---

## 关键概念

### Token 三态

| 状态 | 条件 | 行为 |
|------|------|------|
| `valid` | 距过期 > 300s | 直接返回 |
| `expiring_soon` | 距过期 ≤ 300s | 自动触发刷新 |
| `expired` | 已过期 | 需重新获取（可能需要重新登录） |

### 双层并发锁

Token 管理内置双层并发保护，无需调用方额外处理并发：
- **Layer 1**：`threading.Lock`（防同进程多线程并发）
- **Layer 2**：`fcntl.flock()`（防多 CLI 进程并发，Windows 自动跳过）

### 凭证存储优先级

1. **macOS Keychain**（优先，服务名：`opscli-auth`）
2. **AES-256-GCM 加密文件**（兜底，路径：`~/.config/opscli/credentials.bin`）

### CLI 与 MCP 登录态互通

2025-04-27 重构后，CLI 模式和 MCP 模式**共用同一套加密凭证存储**（CredentialStore）：

- CLI 执行 `opscli auth login` 后，MCP 的 `auth_get_token` 可直接使用，无需重复登录
- MCP 的 `auth_login_poll` 成功后，CLI 的 `opscli auth token get` 可直接使用
- 所有凭证统一存储在 `~/.config/opscli/credentials.bin`（AES-256-GCM 加密）
- `~/.config/opscli/mcp_sessions.json` 已废弃并删除

### 系统类型

| 类型 | 来源 | 是否可删除 |
|------|------|----------|
| `builtin` | 内置（ops） | 否 |
| `local` | 用户手动添加 | 是 |
| `ops_sync` | 从 ops 后端同步 | 自动更新 |

---

## 内置系统

| 别名 | System Key | URL | 用途 |
|------|-----------|-----|------|
| `ops` | ops | https://ops.api.xenkee.com | 运营系统，数据查询、Skill 升级等 |

---

## 快速参考

### 登录与状态检查

```bash
# 首次登录（Device Flow，自动打开浏览器）
opscli auth login

# 查看登录状态与所有系统 Token
opscli auth token status

# 环境检查 + 连通性诊断
opscli auth doctor
```

### Token 操作

```bash
# 获取 JWT（纯文本，适合脚本）
opscli auth token get -s ops

# 赋值给变量（常用模式）
TOKEN=$(opscli auth token get -s ops)

# 检查 Token 是否有效（不刷新）
opscli auth token check -s ops
# 输出: ✓ 有效  剩余 3500 秒

# 主动刷新单个系统
opscli auth token refresh -s ops

# 刷新所有系统
opscli auth token refresh --all
```

### 系统管理

```bash
# 列出所有系统
opscli auth system list

# 从 ops 同步系统列表（需已登录）
opscli auth system sync

# 添加自定义系统（如 staging 环境）
opscli auth system add --alias my-ops --url https://ops-staging.aukeys.com
opscli auth system add --alias test-env --url https://test.aukeys.com --key test_env

# 移除自定义系统
opscli auth system remove --alias my-ops
```

### Python SDK

```python
from opscli import AuthClient
# 或等价写法
from opscli.auth import AuthClient

client = AuthClient()

# 获取 JWT（自动刷新）
token = client.get_token("ops")

# 检查登录状态
if client.is_authenticated():
    print("已登录")

# 构建请求认证参数（同时返回 headers 和 cookies）
headers, cookies = client.build_request_auth("ops")

# 构建 session headers
headers = client.build_session_headers("ops")

# 强制刷新 Token
client.refresh_token("ops")

# 检查 Token 有效性
result = client.check_token("ops")
# result: {"valid": True, "expires_in": 3500}
```

---

## 完整命令参考

### `opscli auth login`

发起 Device Flow 授权（RFC 8628），自动打开浏览器完成登录。登录成功后凭证写入本地，并自动执行系统同步。

**登录流程**：
1. 工具获取设备码并自动打开浏览器
2. 用户在浏览器确认授权（300 秒内完成）
3. 工具轮询获取 Token，写入本地存储
4. 自动执行 `system sync`

**输出示例**：
```
请在浏览器打开： https://https://ops.api.qa.aukeyit.com/device
输入验证码：   ABCD-1234
等待授权中...（300 秒内完成）
✓ 授权成功！账号：user@aukeys.com
```

```bash
opscli auth login
```

---

### `opscli auth logout`

清除本地所有凭证（Keychain + 加密文件），需要重新登录。

**输出示例**：
```
✓ 已退出，本地凭证已清除
```

```bash
opscli auth logout
```

---

### `opscli auth doctor`

检查登录状态与各系统连通性，输出诊断报告，适合排查认证问题。

**输出示例**：
```
opscli auth 环境检查

✓ 已登录
✓ ops 可访问
```

```bash
opscli auth doctor
```

---

### `opscli auth token status`

查看当前登录状态与所有系统的 Token 情况（是否有效、过期时间等）。

**输出示例**：
```
已登录  user@aukeys.com
Session 过期：2025-04-23T10:00:00

别名   系统   Token 状态   剩余时间(s)
ops    ops    有效         3542
```

```bash
opscli auth token status
```

---

### `opscli auth token get`

获取指定系统的 JWT（纯文本输出），适合赋值给变量或传递给其他命令。

**参数**：
- `-s, --system TEXT`：系统别名（必填，如 ops）

**错误场景**：
- 未登录时输出错误并退出码 1
- 系统别名不存在时输出错误并退出码 1

```bash
# 获取 ops 系统 Token
opscli auth token get -s ops

# 赋值给变量（推荐脚本用法）
TOKEN=$(opscli auth token get -s ops)
```

---

### `opscli auth token check`

检测指定系统的 JWT 是否有效（不刷新，仅校验本地 Token）。

**参数**：
- `-s, --system TEXT`：系统别名（必填）

```bash
opscli auth token check -s ops
# 输出: ✓ 有效  剩余 3500 秒
# 若无效: ✗ 已过期或未获取（退出码 1）
```

---

### `opscli auth token refresh`

刷新 JWT，支持单个系统或全部系统。

**参数**：
- `-s, --system TEXT`：指定单个系统别名
- `--all`：刷新所有已登录系统的 Token

```bash
# 刷新单个系统
opscli auth token refresh -s ops

# 刷新所有系统
opscli auth token refresh --all
```

---

### `opscli auth system list`

列出所有已注册系统（内置 + ops 同步 + 手动添加）。

**输出示例**：
```
别名      System Key    URL                              来源
ops       ops           https://ops.api.xenkee.com       builtin
my-ops    my_ops        https://ops-staging.aukeys.com   local
```

```bash
opscli auth system list
```

---

### `opscli auth system sync`

从 ops 后端同步多实例系统列表（需已登录 ops）。登录时自动执行，一般无需手动调用。

```bash
opscli auth system sync
# 输出: ✓ 同步完成，共 3 个系统
```

---

### `opscli auth system add`

手动添加自定义系统实例。

**参数**：
- `--alias TEXT`：系统别名（必填，用于 -s 参数）
- `--url TEXT`：系统 base URL（必填）
- `--key TEXT`：存储键，默认由 alias 生成（可选）

```bash
# 添加 staging 环境
opscli auth system add --alias my-ops --url https://ops-staging.aukeys.com

# 指定自定义存储键
opscli auth system add --alias test-env --url https://test.aukeys.com --key test_env
```

---

### `opscli auth system remove`

移除手动添加的系统（内置系统 ops 不可移除）。

**参数**：
- `--alias TEXT`：系统别名（必填）

**注意**：尝试移除内置系统（ops）会报错并退出。

```bash
opscli auth system remove --alias my-ops
```

---

## 典型工作流

### 入门：首次登录与验证

```bash
# 1. 发起 Device Flow 登录
opscli auth login

# 2. 确认登录状态
opscli auth token status

# 3. 验证连通性
opscli auth doctor
```

### 进阶：脚本集成

```bash
# 获取 Token 并传递给 curl
TOKEN=$(opscli auth token get -s ops)
curl -H "Authorization: Bearer $TOKEN" https://https://ops.api.qa.aukeyit.com/api/v1/data

# 先检查再使用（避免过期）
opscli auth token check -s ops && TOKEN=$(opscli auth token get -s ops)

# Token 刷新后再使用
opscli auth token refresh -s ops
TOKEN=$(opscli auth token get -s ops)
```

### 高级：Python SDK

```python
from opscli import AuthClient

client = AuthClient()

# 构建请求认证参数
ops_headers, ops_cookies = client.build_request_auth("ops")

# 检查 Token 状态
result = client.check_token("ops")
if not result["valid"]:
    client.refresh_token("ops")

token = client.get_token("ops")
```

---

## 常见错误排查

| 错误现象 | 解决方案 |
|---------|---------|
| 401 / 未登录 | `opscli auth login` |
| Token 过期 | `opscli auth token refresh -s <alias>` |
| 系统不可达 | `opscli auth doctor` 确认连通性 |
| 系统别名不存在 | `opscli auth system list` 查看可用别名 |
| Device Flow 超时（> 300s）| 重新执行 `opscli auth login` |
| 授权被拒绝 | 确认在浏览器页面点击了"允许"，重新执行 `opscli auth login` |
| Keychain 不可用 | 自动降级到 AES-256-GCM 加密文件存储，无需干预 |

---

## Token 生命周期常量

| 常量 | 值 | 说明 |
|------|----|------|
| `REFRESH_THRESHOLD` | 300s | 距过期 5 分钟内自动刷新 |
| `MAX_JWT_TTL` | 86400s | 最大 JWT 有效期（24小时） |

---

## 本地配置文件

```
~/.config/opscli/
├── config.ini         # 可选，覆盖服务地址（ops_url 等）
├── credentials.bin    # AES-256-GCM 加密凭证（CLI 与 MCP 共用）
├── .key               # 256-bit 加密密钥，权限 600
├── systems.json       # 用户自定义 + ops_sync 系统列表
├── .lock_<key>        # 跨进程文件锁（运行时临时文件）
└── mcp_sessions.json  # ⚠️ 已废弃（v0.0.5+），数据已迁移到 credentials.bin
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

## 异常类型参考

| 异常类 | 含义 | 常见触发场景 |
|--------|------|------------|
| `AuthError` | 基类 | — |
| `NotAuthenticatedError` | 未登录 | 未执行 login 就调用 get_token |
| `SystemNotFoundError` | 系统别名不存在 | `-s` 参数传了未注册的别名 |
| `DeviceFlowExpiredError` | 授权码超时 | 300s 内未在浏览器完成授权 |
| `DeviceFlowDeniedError` | 用户拒绝授权 | 浏览器点击"拒绝" |
| `TokenRefreshError` | 刷新失败 | 网络异常或 session 失效 |
| `StorageError` | 凭证存储异常 | Keychain 和文件存储均失败 |
| `NetworkError` | 网络连接异常 | 无法访问后端服务 |
