# opscli CLI 与 MCP 模式授权流程深度分析报告

> 文档生成时间：2025-04-27
> 分析范围：opscli 项目 CLI 模式与 MCP 模式下的完整授权流程、业务逻辑及架构差异

---

## 一、总体架构差异

| 维度 | CLI 模式 | MCP 模式 |
|------|----------|----------|
| **运行形态** | 本地命令行工具，用户直接执行 | 服务器进程（stdio / sse / http / both） |
| **用户模型** | 单用户，用户即凭证所有者 | 可多用户共享，支持凭证目录隔离 |
| **状态设计** | **强状态**：凭证自动持久化到本地 | **无状态**：服务器不保存 OAuth 凭证，由调用方传入 |
| **交互方式** | 阻塞式命令执行 | 异步 Tool 调用，AI Agent 控制节奏 |
| **传输协议** | 本地进程 | stdio、SSE、Streamable HTTP |

---

## 二、CLI 模式授权流程详解

### 2.1 完整登录流程

```mermaid
flowchart TD
    A[用户执行<br/>opscli auth login] --> B[DeviceFlow.request_device_code]
    B -->|POST /v1/cli/device/code| C[后端返回<br/>device_code<br/>user_code<br/>verification_url<br/>expires_in]
    C --> D[自动打开浏览器]
    D --> E[用户输入 user_code<br/>点击授权]
    E --> F[DeviceFlow.poll<br/>阻塞轮询 300s]
    F -->|status == authorized| G[CredentialStore.save_session<br/>session_id email<br/>expires_at device_code]
    G --> H[自动同步系统列表<br/>POST /v1/cli/systems]
    H --> I[SystemRegistry.sync_from_ops]
    I --> J[输出<br/>授权成功]

    F -->|status == expired| K[DeviceFlowExpiredError]
    F -->|status == denied| L[DeviceFlowDeniedError]
```

### 2.2 核心组件职责

#### 2.2.1 DeviceFlow（`opscli/auth/core/device_flow.py`）
- **`request_device_code()`**：向后端申请设备码，返回验证信息
- **`poll()`**：**阻塞式轮询**，最长等待 300 秒，授权成功后自动调用 `store.save_session()`
- **`poll_once()`**：单次非阻塞查询，主要用于 MCP 场景
- **异常处理**：`DeviceFlowExpiredError`（超时）、`DeviceFlowDeniedError`（用户拒绝）

#### 2.2.2 TokenManager（`opscli/auth/core/token_manager.py`）
- **Token 三态判断**：
  - `valid`：剩余有效期 > 300 秒
  - `needs_refresh`：0 < 剩余 ≤ 300 秒
  - `expired`：已过期或无 token
- **双层并发锁**（防止多进程/多线程重复换取 JWT）：
  - **Layer 1**：`threading.Lock`（同进程多线程）
  - **Layer 2**：`fcntl.flock()`（跨 CLI 进程，Windows 自动跳过）
- **`get_token(alias)`**：带缓存的智能获取，自动判断三态并刷新
- **`get_token_by_session(session_id, alias)`**：无状态接口，不读本地存储

#### 2.2.3 CredentialStore（`opscli/auth/storage/credential_store.py`）
- **双层存储策略**：
  1. **系统 Keychain**（macOS 钥匙串 / Linux Secret Service）— 优先
  2. **AES-256-GCM 加密文件**（`credentials.bin`）— 兜底
- **密钥管理**：首次使用时自动生成 256-bit 密钥，存储在 `.key` 文件（权限 600）
- **存储结构**：
  ```json
  {
    "session_id": "...",
    "device_code": "...",
    "email": "...",
    "session_expires_at": "...",
    "tokens": {
      "ops": {"jwt": "...", "expires_at": "...", "saved_at": 123}
    }
  }
  ```
- **安全特性**：账号切换时自动清空旧 JWT，避免跨账号泄露

#### 2.2.4 AuthClient（`opscli/auth/__init__.py`）
- **SDK 入口**：供 Skill 和 Python 代码调用
- **`build_request_auth(alias)`**：统一构造认证参数
  - `Authorization: Bearer {jwt}`
  - `Cookie: polarisUserToken={session_id}`
  - `Cookie: opscliDeviceCode={device_code}`（如有）
- **`build_session_headers()`**：构造 `X-Session-Id` 请求头
- **`is_authenticated()`**：检查 session_id 存在且未过期

### 2.3 Token 刷新机制

```mermaid
flowchart TD
    A[用户调用<br/>get_token] --> B{检查本地缓存<br/>token 状态}
    B -->|valid| C[直接返回缓存 JWT]
    B -->|needs_refresh<br/>expired| D[获取 thread_lock<br/>同进程防并发]
    D --> E[双重检查<br/>其他线程可能已完成]
    E --> F[获取 fcntl 文件锁<br/>跨进程防并发]
    F --> G[再次双重检查]
    G --> H[POST token_endpoint<br/>json=session_id]
    H --> I[保存新 JWT 到<br/>CredentialStore]
    I --> J[释放文件锁<br/>释放线程锁]
    J --> K[返回新 JWT]
```

### 2.4 系统注册管理

```mermaid
flowchart LR
    subgraph 系统来源
        A[builtin<br/>ops polaris<br/>代码硬编码]
        B[local<br/>用户手动添加<br/>systems.json]
        C[ops_sync<br/>从后端同步<br/>systems.json]
    end

    D[SystemRegistry] -->|合并优先级<br/>local/ops_sync > builtin| E[list_all<br/>get]

    A --> D
    B --> D
    C --> D
```

- **内置系统**：ops、polaris（不可删除）
- **local 系统**：用户手动添加，持久化到 `systems.json`
- **ops_sync 系统**：从 ops 后端同步
- **合并优先级**：`local/ops_sync > builtin`（同名时用户配置覆盖内置）

---

## 三、MCP 模式授权流程详解

### 3.1 完整登录流程

```mermaid
sequenceDiagram
    participant AI as AI Agent
    participant Tool as MCP Tool<br/>auth_login_start
    participant DF as DeviceFlow<br/>store=None
    participant BE as 后端 OAuth
    participant CS as CredentialStore<br/>credentials.bin
    participant CC as McpCredentialCache<br/>内存缓存
    participant User as 用户

    AI->>Tool: 调用 auth_login_start()
    Tool->>DF: DeviceFlow(OPS_URL, store=None)
    DF->>BE: POST /v1/cli/device/code
    BE-->>DF: {device_code, user_code, verification_url}
    DF-->>Tool: 返回验证信息
    Tool-->>AI: {verification_url, user_code, device_code}

    AI->>User: 引导打开 URL 并输入 user_code
    User->>BE: 浏览器授权

    AI->>Tool: 调用 auth_login_poll(device_code)
    Tool->>DF: poll_once(device_code)
    DF->>BE: GET /v1/cli/device/poll
    BE-->>DF: {status: authorized, session_id, email}
    DF-->>Tool: 授权成功
    Tool->>CS: CredentialStore.save_session(session_id, email, expires_at)
    Tool->>CC: invalidate_credential_cache()
    Tool-->>AI: {session_id, email, saved_locally: true}

    Note over AI,CS: 后续 Tool 调用直接读内存缓存或 CredentialStore
```

### 3.2 核心组件职责

#### 3.2.1 MCP Server（`opscli/mcp/server.py`）
- **FastMCP 实例**：注册 auth / query / skills / chatgpt / amazon 工具集
- **传输模式**：
  - `stdio`：本地 AI 工具集成（默认）
  - `sse`：`GET /sse` + `POST /messages/`，兼容 Cursor / Claude Desktop
  - `http`：`POST /mcp`，Streamable HTTP，ChatGPT 推荐
  - `both`：同时暴露 /sse 和 /mcp
- **API Key 管理**：`_load_or_create_api_key()`，持久化到 `mcp_api_key` 文件

#### 3.2.2 API Key 鉴权中间件（`opscli/mcp/auth_middleware.py`）
- **作用**：SSE/HTTP 连接层的基础访问控制（与业务 OAuth 鉴权解耦）
- **校验方式**：
  1. `?api_key=xxx` Query Param（优先）
  2. `Authorization: Bearer <api_key>` Header
- **失败响应**：401 + `WWW-Authenticate: Bearer realm="opscli-mcp"`
- **特殊处理**：SSE 长连接关闭时补发终止帧，避免 uvicorn 报错

#### 3.2.3 MCP Auth Tools（`opscli/mcp/tools/auth.py`）
暴露 13 个工具：

| 工具名 | 功能 | 是否需 session |
|--------|------|---------------|
| `auth_login_start` | 发起 Device Flow | 否 |
| `auth_login_poll` | 单次轮询授权状态 | 否 |
| `auth_get_token` | 获取系统 JWT | 是 |
| `auth_check_token` | 本地检测 JWT 有效性 | 否（可传 jwt） |
| `auth_is_authenticated` | 检查 session 有效性 | 可选 |
| `auth_token_refresh` | 刷新 JWT | 是 |
| `auth_system_list` | 列出系统 | 否 |
| `auth_system_add/remove` | 管理自定义系统 | 否 |
| `auth_system_sync` | 从 ops 同步系统 | 是 |
| `auth_build_request_auth` | 构造请求头/Cookie | 可选 |
| `auth_logout` | 清除本地凭证 | 否 |
| `auth_doctor` | 诊断连通性 | 可选 |

#### 3.2.4 McpCredentialCache（`opscli/mcp/credential_cache.py`）
- **设计目的**：为高频 Tool 调用提供零开销凭证读取，避免每次请求都 AES-256-GCM 解密
- **工作方式**：
  - MCP Server 启动时（或首次访问）从 `CredentialStore` 加载凭证到内存
  - 后续 Tool 调用直接读内存，单次读取约 **0.45 微秒**
  - 凭证变更时调用 `invalidate_credential_cache()` 刷新
- **线程安全**：内部使用 `threading.Lock` 保护缓存数据
- **多用户隔离**：支持 `base_dir` 参数，按用户 `credential_dir` 分配独立缓存实例

#### 3.2.5 CredentialStore（共用存储层）
- **说明**：2025-04-27 重构后，MCP 不再使用独立的 `mcp_sessions.json`，
  而是与 CLI **共用** `opscli/auth/storage/credential_store.py`
- **存储位置**：`~/.config/opscli/credentials.bin`（AES-256-GCM 加密）
- **数据结构与 CLI 完全一致**：全局 `session_id` + 各系统 JWT 缓存
- **`mcp_sessions.json` 已废弃并删除**：原文件已移除，不再维护

#### 3.2.6 MCPUserStore（`opscli/mcp/user_store.py`）
- **用途**：团队共享 MCP Server 时的多用户隔离
- **存储**：`mcp_users.json`，只保存 API Key **哈希**（SHA256 + HMAC compare_digest）
- **安全**：原始 API Key 仅在创建/轮换时展示一次，服务端不保存明文
- **隔离**：每个用户有独立的 `credential_dir`（`users/<user_id>/`）
- **CLI 管理**：`opscli mcp user add/remove/rotate/list`

### 3.3 凭证获取优先级（Helpers）

```mermaid
flowchart TD
    A[_get_session_id] --> B{provided<br/>是否传入?}
    B -->|是| C[返回 provided]
    B -->|否| D[McpCredentialCache.get_session_id]
    D --> E{命中缓存?}
    E -->|是| F[返回 session_id]
    E -->|否| G[CredentialStore.load<br/>读取全局 session_id]

    H[_get_jwt] --> I{provided<br/>是否传入?}
    I -->|是| J[返回 provided]
    I -->|否| K[McpCredentialCache.get_jwt]
    K --> L{命中缓存且未过期?}
    L -->|是| M[返回 jwt]
    L -->|否| N[CredentialStore.load<br/>读取系统 token]
    N --> O{未过期?}
    O -->|否| P[CredentialStore.remove_token<br/>清除过期 token]

    Q[_get_auth_pair] --> R[返回<br/>session_id, jwt]
```

### 3.4 Token 管理差异

| 特性 | CLI TokenManager | MCP Auth Tools |
|------|------------------|----------------|
| **获取方式** | 读取本地存储 + 自动刷新 | `get_token_by_session(session_id)` 实时换取 |
| **自动刷新** | ✅ 300秒阈值自动触发 | ❌ 需显式调用 `auth_token_refresh` |
| **并发保护** | ✅ 双层锁 | ❌ 无状态实时请求 |
| **JWT 缓存** | CredentialStore（加密） | **CredentialStore（加密）+ McpCredentialCache（内存）** |
| **刷新范围** | 支持单系统 / 全部系统 | 支持单系统 / `__all__` |

---

## 四、核心差异深度对比

### 4.1 授权流程差异

```mermaid
flowchart LR
    subgraph CLI模式
        direction TB
        A1[login] --> B1[自动打开浏览器]
        B1 --> C1[阻塞轮询]
        C1 --> D1[自动保存凭证]
        D1 --> E1[自动同步系统]
        style A1 fill:#e1f5e1
        style E1 fill:#e1f5e1
    end

    subgraph MCP模式
        direction TB
        A2[login_start] --> B2[返回 URL+Code]
        B2 --> C2[AI引导用户授权]
        C2 --> D2[login_poll]
        D2 --> E2[保存到本地]
        E2 --> F2[需显式同步系统]
        style A2 fill:#fff3e0
        style F2 fill:#fff3e0
    end

    CLI模式 -->|用户只需一条命令| MCP模式
    MCP模式 -->|AI Agent控制节奏| CLI模式
```

### 4.2 凭证存储安全对比

```mermaid
flowchart TD
    subgraph CLI凭证存储
        A1[CredentialStore] --> B1{Keychain<br/>可用?}
        B1 -->|是| C1[macOS Keychain<br/>Linux Secret Service]
        B1 -->|否| D1[AES-256-GCM<br/>credentials.bin]
        D1 --> E1[256-bit 密钥<br/>.key 文件]
    end

    subgraph MCP凭证存储（重构后）
        A2[McpCredentialCache] --> B2[内存缓存<br/>0.45 µs/读]
        B2 --> C2[CredentialStore.load<br/>启动时加载]
        C2 --> D2[AES-256-GCM<br/>credentials.bin]
    end

    subgraph MCP多用户隔离
        E2[MCPUserStore] --> F2[mcp_users.json]
        F2 --> G2[API Key SHA256<br/>仅存哈希]
        G2 --> H2[独立 credential_dir<br/>users_user_id]
    end
```

| 层面 | CLI 模式 | MCP 模式（重构后） |
|------|----------|-------------------|
| **存储介质** | Keychain / AES-256-GCM 加密文件 | **AES-256-GCM 加密文件（与 CLI 共用）** |
| **密钥管理** | 自动生成 256-bit 密钥，权限 600 | 与 CLI 共用同一密钥 |
| **文件权限** | 600（所有者可读写） | 600 |
| **内存缓存** | 无（每次读取解密） | **McpCredentialCache（0.45 µs/读）** |
| **多用户隔离** | 不支持（单用户） | 支持（独立 credential_dir + 独立缓存实例） |
| **连接层鉴权** | 无（本地进程） | API Key（Bearer / Query） |

### 4.3 状态管理哲学

| | CLI | MCP |
|--|-----|-----|
| **设计原则** | 强状态、自动化 | 无状态、显式传递 |
| **session_id 位置** | 封装在 CredentialStore 内部 | 由调用方传入或从本地 JSON 加载 |
| **Token 生命周期** | 自动透明管理 | 调用方显式控制 |
| **适用场景** | 个人终端长期使用 | 远程共享服务 / AI Agent 调用 |

### 4.4 系统同步时机

- **CLI**：`login` 成功后**自动**同步系统列表（`opscli auth login` 第 82-92 行）
- **MCP**：`auth_login_poll` 后**不自动同步**，需显式调用 `auth_system_sync(session_id)`

### 4.5 异常处理差异

| 场景 | CLI | MCP |
|------|-----|-----|
| 未登录 | 抛出 `NotAuthenticatedError`，CLI 退出码 1 | 返回 `_err(ValueError("无 session_id..."))` |
| Token 过期 | 自动刷新，用户无感知 | 需 AI 调用 `auth_token_refresh` 或重新 `auth_get_token` |
| 设备码超时 | `DeviceFlowExpiredError`，CLI 退出码 1 | 返回 `_err(DeviceFlowExpiredError)` |
| 系统不存在 | `SystemNotFoundError`，CLI 退出码 1 | 返回 `_err(SystemNotFoundError)` |

---

## 五、数据流对比图

### 5.1 CLI 模式数据流

```mermaid
flowchart TD
    A[用户命令<br/>opscli auth login] --> B[Auth CLI<br/>cli.py]
    B --> C[DeviceFlow<br/>device_flow.py]
    C -->|POST /v1/cli/device/code| D[后端 OAuth<br/>Device Flow]
    D --> C
    C -->|save_session| E[CredentialStore<br/>credential_store.py]
    E -->|双层存储<br/>Keychain/AES| F[(本地凭证)]
    E --> G[TokenManager<br/>token_manager.py]
    G -->|双层并发锁<br/>自动刷新| H[AuthClient<br/>__init__.py]
    H --> I[业务模块调用<br/>Skill Query 脚本]

    style E fill:#e1f5e1
    style G fill:#e1f5e1
```

### 5.2 MCP 模式数据流

```mermaid
flowchart TD
    A[AI Agent<br/>调用 Tool] --> B[MCP Tools<br/>tools/auth.py]
    B --> C[DeviceFlow<br/>store=None]
    C -->|POST /v1/cli/device/code| D[后端 OAuth<br/>Device Flow]
    D --> C
    C -->|save_session| E[CredentialStore<br/>credential_store.py]
    E -->|AES-256-GCM| F[(credentials.bin)]
    E -->|invalidate| CC[McpCredentialCache<br/>credential_cache.py]
    CC -->|内存缓存| G[auth_get_token]
    CC -->|内存缓存| H[auth_check_token]
    CC -->|内存缓存| I[auth_build_request_auth]

    G --> J[AuthClient<br/>get_token_by_session]
    H --> J
    I --> J
    J --> K[Query/Skills<br/>业务数据查询]

    L[ApiKeyAuthMiddleware] -->|连接层鉴权| B
    M[MCPUserStore] -->|多用户隔离| E
    M -->|独立缓存| CC

    style E fill:#e1f5e1
    style CC fill:#e3f2fd
    style L fill:#e3f2fd
    style M fill:#e3f2fd
```

---

## 六、安全设计要点

### 6.1 CLI 安全

```mermaid
flowchart LR
    A[CLI安全] --> B[Keychain优先]
    A --> C[AES-256-GCM兜底]
    A --> D[账号切换保护]
    A --> E[文件权限600]
    A --> F[双层并发锁]

    B --> B1[操作系统级安全存储]
    C --> C1[密钥独立存储<br/>加密格式含nonce]
    D --> D1[session变化<br/>自动清空旧JWT]
    E --> E1[所有者可读写]
    F --> F1[防多进程竞争<br/>防重复请求]
```

1. **Keychain 优先**：利用操作系统级安全存储
2. **AES-256-GCM 兜底**：密钥独立存储，加密格式含 nonce
3. **账号切换保护**：`save_session()` 检测到 session 变化时自动清空旧 JWT
4. **文件权限 600**：密钥文件和加密文件均限制为所有者可读写
5. **双层并发锁**：防止多进程竞争导致凭证泄漏或重复请求

### 6.2 MCP 安全

```mermaid
flowchart LR
    A[MCP安全] --> B[连接层与业务层分离]
    A --> C[API Key哈希存储]
    A --> D[HMAC compare_digest]
    A --> E[多用户隔离]
    A --> F[无服务器状态]

    B --> B1[API Key仅控制访问<br/>OAuth鉴权由session_id完成]
    C --> C1[SHA256哈希<br/>明文仅展示一次]
    D --> D1[防时序攻击]
    E --> E1[独立credential_dir]
    F --> F1[OAuth凭证不留在<br/>服务器内存]
```

1. **连接层与业务层分离**：API Key 仅控制能否访问 MCP Server，OAuth 鉴权由 session_id/jwt 完成
2. **API Key 哈希存储**：`mcp_users.json` 只存 SHA256 哈希，明文 Key 仅展示一次
3. **HMAC compare_digest**：防时序攻击的哈希比较
4. **多用户隔离**：每个用户的 session/JWT 存储在独立目录
5. **无服务器状态**：OAuth 凭证不留在服务器内存，降低服务端泄露风险

### 6.3 安全 trade-off

```mermaid
flowchart TD
    A[安全设计权衡] --> B{运行形态}
    B -->|本地单用户长期持有| C[CLI模式]
    B -->|远程共享/AI集成| D[MCP模式]

    C --> C1[强加密存储<br/>Keychain + AES-256-GCM]
    C --> C2[自动刷新<br/>双层锁保护]

    D --> D1[CredentialStore加密存储<br/>与CLI共用]
    D --> D2[McpCredentialCache<br/>内存缓存0.45µs]
    D --> D3[API Key连接层保护]

    C1 --> E[适合终端长期使用]
    D1 --> F[适合远程服务<br/>安全且快速]

    style C1 fill:#e1f5e1
    style D1 fill:#e1f5e1
```

- **CLI** 使用强加密存储，适合单用户长期持有凭证
- **MCP** 重构后与 CLI **共用 AES-256-GCM 加密存储**，通过 **McpCredentialCache 内存缓存** 解决高频读取性能问题：
  - 凭证统一加密存储，安全水位与 CLI 一致
  - 内存缓存单次读取仅 **0.45 微秒**，性能是明文 JSON 的 **30 倍**
  - 远程场景下 API Key 仍提供连接层保护
  - 文件权限 600 提供基础 OS 级保护

---

## 七、典型使用场景

```mermaid
flowchart TD
    A[使用场景] --> B[个人终端日常]
    A --> C[AI工具集成]
    A --> D[团队共享服务]
    A --> E[Shell脚本自动化]

    B -->|推荐| B1[CLI模式]
    B1 --> B2[一次登录长期有效<br/>自动化管理]

    C -->|Cursor/Claude Desktop| C1[MCP stdio]
    C -->|ChatGPT/OpenAI Apps| C2[MCP http]
    C1 --> C3[AI Agent直接调用工具]

    D -->|推荐| D1[MCP http/sse<br/>+ user_store]
    D1 --> D2[多用户隔离<br/>API Key管理]

    E -->|推荐| E1[CLI模式]
    E1 --> E2[TOKEN=opscli auth token get]

    style B1 fill:#e1f5e1
    style C1 fill:#fff3e0
    style C2 fill:#fff3e0
    style D1 fill:#e3f2fd
    style E1 fill:#e1f5e1
```

| 场景 | 推荐模式 | 原因 |
|------|----------|------|
| 个人开发终端日常使用 | **CLI** | 自动化管理，一次登录长期有效 |
| Cursor / Claude Desktop 集成 | **MCP stdio** | AI Agent 可直接调用工具 |
| 团队共享远程服务 | **MCP http/sse + user_store** | 多用户隔离，API Key 管理 |
| ChatGPT / OpenAI Apps | **MCP http** | Streamable HTTP 协议兼容 |
| Shell 脚本自动化 | **CLI** | `TOKEN=$(opscli auth token get -s ops)` |

---

## 八、总结

```mermaid
flowchart TD
    A[opscli授权体系] --> B[同一套底层能力]
    B --> C[Device Flow]
    B --> D[Token换取]
    B --> E[系统注册]

    A --> F[两种运行形态适配]
    F --> G[CLI模式]
    F --> H[MCP模式]

    G --> G1[强状态<br/>自动化<br/>单用户]
    G --> G2[凭证加密存储<br/>Token自动刷新]
    G --> G3[适合终端长期使用]

    H --> H1[无状态<br/>显式传递<br/>可扩展多用户]
    H --> H2[服务器不持OAuth凭证<br/>CredentialStore加密+内存缓存]
    H --> H3[适合远程服务<br/>AI集成场景]

    G1 -.->|差异维度| I[凭证存储层]
    H1 -.->|差异维度| I
    I --> I1[共用 CredentialStore<br/>+ McpCredentialCache]

    G1 -.->|差异维度| J[并发策略]
    H1 -.->|差异维度| J
    J --> J1[双层锁<br/>vs<br/>无状态实时请求]

    G1 -.->|差异维度| K[交互模式]
    H1 -.->|差异维度| K
    K --> K1[阻塞自动化<br/>vs<br/>非阻塞Tool调用]

    style G fill:#e1f5e1
    style H fill:#e3f2fd
    style B fill:#e3f2fd
```

opscli 的两种授权模式是**同一套底层能力**（Device Flow、Token 换取、系统注册）在不同运行形态下的适配：

- **CLI 模式**采用**强状态、自动化、单用户**设计，凭证加密存储，Token 自动刷新，适合终端长期使用。
- **MCP 模式**采用**无状态、显式传递、可扩展多用户**设计，服务器不持有 OAuth 凭证，凭证统一存储在 `CredentialStore`（与 CLI 共用），高频读取通过 `McpCredentialCache` 内存缓存优化，适合远程服务和 AI 集成场景。

两者共享 `AuthClient`、`DeviceFlow`、`SystemRegistry`、`CredentialStore` 等核心模块，差异主要体现在**并发策略**（双层锁 vs 无状态实时请求）、**交互模式**（阻塞自动化 vs 非阻塞 Tool 调用）两个维度，**凭证存储层已完全统一**。

---

*文档结束*
