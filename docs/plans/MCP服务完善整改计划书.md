# opscli MCP 服务完善整改计划书

> 版本：v1.1
> 日期：2026-04-24
> 状态：已根据当前项目实现修订，待确认

---

## 一、背景与目标

### 1.1 背景

opscli 已完成初版 MCP Server 接入（`opscli/mcp/server.py`），基于 fastmcp 3.x 暴露了 9 个 Tools，可通过 stdio / SSE 两种传输方式供 AI Agent 调用。当前已通过 `fastmcp.Client(mcp).list_tools()` 验证实际 Tool 数量为 9。

然而，当前实现存在以下三类明显缺口：

1. **Tool 覆盖不完整**：auth 模块 13 条 CLI 命令只映射了 3 个 Tool，登录、系统管理、Token 刷新等核心操作无法通过 MCP 完成
2. **无多用户隔离**：MCP Server 所有请求共享同一份本地凭证，无法部署为团队共享服务
3. **Skills 缺少 MCP 版本**：现有 `ops-auth`、`ops-dataset-query` Skill 的使用指南均基于 CLI subprocess 模式，AI Agent 通过 MCP 接入时无适配的 Skill 可用

### 1.2 整改目标

| 目标 | 验收标准 |
|------|---------|
| 补全 MCP Tools，覆盖全部核心 CLI 功能 | MCP Tools 数量从 9 个扩展至 21 个，覆盖 auth/query/skills 全模块 |
| 支持多用户认证与凭证隔离 | 不同 API Key 读写各自独立的凭证目录，互不影响 |
| 提供 MCP 版 Skills | 新增 2 份 SKILL_MCP.md 及 ops-mcp Skill，AI Agent 可通过 MCP 完整执行工作流 |

### 1.3 本期范围边界

本期只覆盖 `auth` / `query` / `skills` 三个已接入 MCP 的核心模块，不把 `amazon` 模块纳入本次 Tool 覆盖目标。当前仓库已经存在 `opscli/amazon` 与 `ops-amazon` Skill，如后续需要面向 Amazon 监控或抓取能力开放 MCP，应单独立项，避免把认证、多用户隔离与业务采集能力混在同一轮整改中。

MCP 用户管理能力本期通过 `opscli mcp user ...` CLI 提供，不作为普通 MCP Tool 暴露。这样可以避免 AI Agent 在共享服务中误删、轮换或枚举用户凭证，同时保持最终 Tool 数量为 21。

---

## 二、现状差距分析

### 2.1 Tools 覆盖缺口

**当前已实现（9 个）：**

```
query_metadata / query_build / query_run / query_build_and_run
auth_get_token / auth_check_token / auth_is_authenticated
skills_list / skills_status
```

**缺失 Tools（12 个）：**

| Tool 名称 | 对应 CLI 命令 | 优先级 |
|----------|-------------|--------|
| `auth_login_start` | `opscli auth login`（第一步：获取设备码） | P0 |
| `auth_login_poll` | `opscli auth login`（第二步：轮询授权状态） | P0 |
| `auth_logout` | `opscli auth logout` | P0 |
| `auth_token_refresh` | `opscli auth token refresh` | P0 |
| `auth_system_list` | `opscli auth system list` | P1 |
| `auth_system_add` | `opscli auth system add` | P1 |
| `auth_system_remove` | `opscli auth system remove` | P1 |
| `auth_system_sync` | `opscli auth system sync` | P1 |
| `auth_build_request_auth` | `AuthClient.build_request_auth()` SDK | P1 |
| `auth_doctor` | `opscli auth doctor` | P2 |
| `skills_install` | `opscli skills install` | P1 |
| `skills_upgrade` | `opscli skills upgrade` | P1 |

**特殊说明 — `auth_login` 两步拆分设计：**

原始 Device Flow 的 `poll()` 方法会同步阻塞最长 300 秒，MCP Tool 不能阻塞。当前 `opscli/auth/core/device_flow.py` 中的 `poll()` 会先 `time.sleep(interval)` 再循环请求，因此不能直接复用到 MCP Tool。
解决方案：将登录拆为两个独立 Tool，由 AI Agent 驱动轮询：

```
auth_login_start()
  → 向后端请求设备码
  → 返回 { verification_url, user_code, device_code, expires_in }
  → AI Agent 将 URL 展示给用户，提示在浏览器完成授权

auth_login_poll(device_code, timeout=10)
  → 单次请求授权状态（HTTP timeout 最多 timeout 秒，不额外 sleep）
  → 返回 { status: "pending" | "authorized" | "expired" | "denied" }
  → AI Agent 循环调用，直到 status = "authorized"
```

实施时需要在 `DeviceFlow` 底层新增 `poll_once(device_code, timeout=10)` 或等价私有方法：

- `pending`：直接返回状态，不写入凭证
- `authorized`：保存 `session_id` / `email` / `expires_at` / `device_code` 到当前 `CredentialStore`
- `expired` / `denied`：返回结构化状态或抛出已有业务异常，由 Tool 统一映射
- HTTP 请求失败：通过 `_err()` 统一返回，不让 Tool 长时间阻塞

### 2.2 多用户认证缺口

**当前凭证存储的设计局限：**

```
CredentialStore
├── 凭证路径：~/.config/opscli/credentials.bin（硬编码单一路径）
├── Keychain 账户名：固定为 "credentials"（只能存一份）
└── 用户标识：无，session_id / tokens 合并在单个 JSON 中
```

**问题：**

- MCP Server 以服务模式运行时，用户 A 和用户 B 的请求都读写同一份凭证
- 用户 A 登录后，用户 B 也能获取到用户 A 的 JWT
- 用户 A 登出后，用户 B 的 session 也会被清除

**根本原因：** `CredentialStore` 在设计时仅考虑了单机单用户的 CLI 使用场景，没有多用户隔离机制。

### 2.3 Skills 形态缺口

| Skill | 现有 SKILL.md | 缺少 SKILL_MCP.md | 影响 |
|-------|-------------|-------------------|------|
| ops-auth | ✅ CLI 版完整 | ❌ 无 MCP 版 | AI Agent 无法通过 MCP 自主完成登录工作流 |
| ops-dataset-query | ✅ CLI 版完整 | ❌ 无 MCP 版 | AI Agent 无法通过 MCP Tool 执行数据查询工作流 |
| ops-mcp | ❌ 不存在 | ❌ 不存在 | 无法通过 Skill 管理 MCP Server 用户和配置 |

---

## 三、整改方案

### 阶段一：补全 MCP Tools

#### 3.1.1 变更文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `opscli/mcp/server.py` | 修改 | 新增 12 个 Tool 定义 |
| `opscli/auth/core/device_flow.py` | 修改 | 新增非阻塞单次轮询能力，供 `auth_login_poll` 复用 |
| `README_MCP.md` | 修改 | 补充新 Tools 的参数说明 |
| `tests/mcp/test_tools.py` | 新增 | 覆盖 Tool 列表、核心 Tool schema 与无真实网络的 mock 测试 |

#### 3.1.2 新增 Tools 详细设计

**`auth_login_start`**

```python
@mcp.tool()
def auth_login_start() -> dict:
    """
    发起 Device Flow 登录的第一步，向后端请求设备码。

    Returns:
        {
          "verification_url": "https://ops.aukeys.com/device",
          "user_code": "ABCD-1234",
          "device_code": "xxx",   # 传给 auth_login_poll 使用
          "expires_in": 300       # 设备码有效期（秒）
        }

    使用方式：
        1. 调用本 Tool，将 verification_url 和 user_code 展示给用户
        2. 用户在浏览器打开 verification_url，输入 user_code 完成授权
        3. 循环调用 auth_login_poll(device_code) 直到返回 authorized
    """
```

**`auth_login_poll`**

```python
@mcp.tool()
def auth_login_poll(device_code: str, timeout: int = 10) -> dict:
    """
    轮询一次授权状态（单次，不阻塞超过 timeout 秒）。

    Args:
        device_code: 由 auth_login_start 返回的设备码
        timeout: 单次 HTTP 请求超时（秒），默认 10，最大 30；
                 Tool 内不主动 sleep，由 Agent 按 interval 再次调用

    Returns:
        {
          "status": "pending" | "authorized" | "expired" | "denied",
          "email": "user@aukeys.com"  # 仅 authorized 时有值
        }

    使用方式：按照 auth_login_start 返回的 interval（默认 3 秒）再次调用，
    直到 status != "pending"
    """
```

**`auth_token_refresh`**

```python
@mcp.tool()
def auth_token_refresh(system: str = "__all__") -> dict:
    """
    刷新指定系统的 JWT，或刷新全部系统。

    Args:
        system: 系统别名（如 "ops"、"polaris"），传 "__all__" 刷新所有系统

    Returns:
        单系统: { "success": true, "data": "<新 JWT>", "error": null }
        全部:   { "success": true, "data": {"ops": "ok", "polaris": "ok"}, "error": null }
    """
```

**`auth_system_list`**

```python
@mcp.tool()
def auth_system_list() -> dict:
    """
    列出所有已注册系统（内置 + ops_sync + 用户自定义）。

    Returns:
        {
          "success": true,
          "data": [
            {"alias": "ops", "url": "...", "source": "builtin"},
            {"alias": "polaris", "url": "...", "source": "builtin"}
          ],
          "error": null
        }
    """
```

**`auth_build_request_auth`**

```python
@mcp.tool()
def auth_build_request_auth(system: str = "ops") -> dict:
    """
    构造统一请求认证参数（JWT Bearer + Session Cookie）。
    用于在其他 HTTP 请求中携带认证信息。

    Returns:
        {
          "headers": {"Authorization": "Bearer <JWT>"},
          "cookies": {"polarisUserToken": "<session_id>"}
        }
    """
```

#### 3.1.3 验收标准

- `opscli-mcp` 启动后，`list_tools()` 返回 21 个 Tool
- `auth_login_start` → `auth_login_poll` 完整登录流程可在 Inspector 中验证
- `auth_login_poll` 单次调用不使用 300 秒阻塞式 `DeviceFlow.poll()`，单元测试中可验证 pending 立即返回
- `auth_token_refresh(system="__all__")` 正常返回所有系统刷新结果
- 所有新 Tool 均有完整 docstring，Inspector 中可见参数说明
- 所有涉及后端 HTTP 的测试必须使用 `respx` mock，不访问真实网络

---

### 阶段二：多用户认证与凭证隔离

#### 3.2.1 设计原则

```
一个 API Key = 一个用户身份 = 一个独立凭证目录
```

- API Key 由 `opscli mcp user add` 命令生成，服务端只存 SHA256 哈希
- SSE / HTTP 模式下，每次 MCP 请求携带 Bearer Token，Server 验证后注入对应用户的 `credential_dir`
- stdio 模式下，通过环境变量 `OPSCLI_MCP_API_KEY` 绑定当前 MCP 进程的默认用户
- Tool 函数通过 fastmcp Context 或服务端 session state 获取 `credential_dir`，实例化隔离的 `CredentialStore`

#### 3.2.1.1 运行模式矩阵

| 模式 | 启动参数 | 凭证目录 | 鉴权要求 | 适用场景 |
|------|----------|----------|----------|----------|
| 单用户兼容模式 | `opscli-mcp` | `~/.config/opscli/` | 不需要 API Key | 本机个人使用，兼容现有 9 个 Tool |
| stdio 多用户模式 | `OPSCLI_MCP_API_KEY=... opscli-mcp --multi-user` | `~/.config/opscli/users/{user_id}/` | 进程启动时校验 env API Key | Claude Desktop / Codex 本地每用户独立配置 |
| SSE 多用户模式 | `opscli-mcp --transport sse --multi-user --require-auth` | `~/.config/opscli/users/{user_id}/` | 每请求 `Authorization: Bearer <api_key>` | 团队共享 MCP Server |

兼容策略：不传 `--multi-user` 时永远保持当前单用户行为，不因 `mcp_users.json` 存在而隐式改变运行模式。传入 `--multi-user` 但未提供有效 API Key 时，stdio 模式启动失败，SSE / HTTP 模式返回 401 / 403。

#### 3.2.2 目录结构变更

```
~/.config/opscli/                        # 现有结构不变
├── config.ini
├── credentials.bin                      # 单机用户凭证（兼容现有）
├── .key
├── systems.json
├── mcp_users.json                       # 【新增】MCP 用户注册表
└── users/                               # 【新增】多用户凭证隔离目录
    ├── {user_id_1}/
    │   ├── credentials.bin
    │   ├── .key
    │   └── systems.json
    └── {user_id_2}/
        ├── credentials.bin
        ├── .key
        └── systems.json
```

权限要求：

- `~/.config/opscli/users/` 与每个 `{user_id}/` 目录权限设为 `700`
- 每个用户目录下的 `.key` 与 `credentials.bin` 权限设为 `600`
- `systems.json` 也建议设为 `600`，避免泄露内部系统 URL 与 token endpoint
- `mcp_users.json` 权限设为 `600`，并使用原子写入避免并发写损坏

**`mcp_users.json` 格式：**

```json
[
  {
    "user_id": "u_a1b2c3d4",
    "api_key_hash": "sha256:xxxxxxxxxxxxxxxx",
    "description": "张三的工作站",
    "created_at": "2026-04-24T00:00:00Z"
  }
]
```

> **安全约束**：`api_key_hash` 只存 SHA256 哈希值，原始 API Key 仅在创建时展示一次，服务端不保存明文。

> **权限控制**：本阶段只做凭证隔离，所有用户均可调用全部 Tools，不做 Tool 级权限分组。未来如需细粒度控制，可在 `mcp_users.json` 中扩展 `permissions` 字段。

#### 3.2.3 新增文件清单

| 文件 | 职责 |
|------|------|
| `opscli/mcp/user_store.py` | MCP 用户注册表的 CRUD：增/删/查/轮换 API Key |
| `opscli/mcp/auth_middleware.py` | Bearer Token / stdio env API Key 验证：哈希比对 + credential_dir 注入（无 Tool 级权限检查） |
| `opscli/mcp/context.py` | fastmcp Context 辅助：从请求上下文提取 credential_dir |
| `opscli/mcp/cli.py` | `opscli mcp user` 子命令（list / add / remove / rotate） |

实施约束：

- `user_store.py` 写入 `mcp_users.json` 时必须采用临时文件 + `replace()` 原子替换
- API Key 比对使用 `hmac.compare_digest()`，避免普通字符串比较
- 原始 API Key 只在 `add` / `rotate` 命令输出一次，不写日志、不写注册表
- `remove` 默认删除用户注册信息和对应凭证目录；如需保留凭证，应显式提供 `--keep-credentials`
- FastMCP 3.2.4 已确认存在 `Context`、`auth`、`middleware` 初始化参数；阶段二编码前仍需用最小样例验证“请求头读取与 Context 注入”的具体 API

#### 3.2.5 `server.py` 改造方式

所有需要凭证的 Tool 增加 `Context` 参数。FastMCP 的 `Context` 参数不应暴露为客户端可填写参数，因此对外 Tool schema 应保持业务参数不变：

```python
from fastmcp import Context
from opscli.mcp.context import get_credential_dir

@mcp.tool()
async def auth_get_token(system: str, ctx: Context) -> dict:
    credential_dir = get_credential_dir(ctx)          # 从上下文取凭证目录
    client = AuthClient(base_dir=credential_dir)      # 使用隔离凭证
    try:
        return _ok(client.get_token(system))
    except Exception as exc:
        return _err(exc)
```

**兼容模式：** 未启用 `--multi-user` 时，`get_credential_dir` 返回 `None`，Tool 行为与现在完全相同，不破坏现有单机使用。

#### 3.2.6 新增 CLI 命令：`opscli mcp user`

```
opscli mcp
    user
        list                               # 列出所有 MCP 用户
        add --desc "张三的工作站"            # 创建用户，输出 API Key（仅显示一次）
        remove --id <user_id>              # 删除用户及其凭证目录
        rotate --id <user_id>             # 重新生成 API Key
```

**`opscli mcp user add` 输出示例：**

```
✓ 用户创建成功

  User ID:    u_a1b2c3d4
  描述：      张三的工作站
  API Key:    opscli-mcp-AbCdEfGhIjKlMnOpQrSt...

  ⚠️ 请立即保存此 API Key，它只显示一次，服务端不保存明文。
  所有 Tools 均可调用，凭证与其他用户完全隔离。

Claude Desktop 接入配置：
{
  "mcpServers": {
    "opscli": {
      "command": "opscli-mcp",
      "args": ["--multi-user"],
      "env": { "OPSCLI_MCP_API_KEY": "opscli-mcp-AbCdEfGhIjKlMnOpQrSt..." }
    }
  }
}
```

SSE / HTTP 接入时应在客户端配置中传入请求头：

```http
Authorization: Bearer opscli-mcp-AbCdEfGhIjKlMnOpQrSt...
```

#### 3.2.7 验收标准

- 创建两个不同 API Key，分别登录不同账号，验证 `auth_is_authenticated` 返回各自独立的状态
- 用户 A 执行 `auth_logout` 后，用户 B 的登录状态不受影响
- `--multi-user --require-auth` 下，无 API Key 的请求返回 401，有无效 API Key 的请求返回 403
- 不启用 `--multi-user` 时，即使存在 `mcp_users.json`，Server 仍退化为单用户模式，现有功能不受影响
- stdio 模式下，`OPSCLI_MCP_API_KEY` 指向不同用户时，`auth_get_token` 使用不同凭证目录
- `mcp_users.json` 并发 add / rotate 不产生 JSON 损坏

---

### 阶段三：MCP 版 Skills

#### 3.3.1 文件新增清单

```
opscli/skills/templates/
├── ops-auth/
│   ├── SKILL.md           # 现有 CLI 版，不改动
│   └── SKILL_MCP.md       # 【新增】MCP 版
├── ops-dataset-query/
│   ├── SKILL.md           # 现有 CLI 版，不改动
│   └── SKILL_MCP.md       # 【新增】MCP 版
└── ops-mcp/               # 【新增】MCP 管理 Skill
    ├── data/
    │   └── VERSION.json
    └── SKILL.md
```

#### 3.3.1.1 多 Runtime 安装支持

`SKILL_MCP.md` 需要同时安装到系统检测到的所有 AI 工具运行时，与现有 CLI Skill 保持一致。

opscli 当前支持的四个 runtime 及其 Skills 目录：

| Runtime | Skills 目录（macOS/Linux） | 检测条件 |
|---------|--------------------------|---------|
| `claude` | `~/.claude/skills/` | `~/.claude/` 目录存在 或 `which claude` |
| `openclaw` | `~/.openclaw/skills/` | `~/.openclaw/` 目录存在 或 `which openclaw` |
| `codex` | `~/.codex/skills/` | `~/.codex/` 目录存在 或 `which codex` |
| `opencode` | `~/.config/opencode/skills/` | `~/.config/opencode/` 目录存在 或 `which opencode` |

**安装行为规范：**

- `opscli skills install ops-auth`（无 `--runtime` 参数）→ 自动检测已安装的 AI 工具，全量安装到所有检测到的 runtime
- `opscli skills install ops-auth --runtime claude` → 仅安装到 claude
- `opscli skills install ops-auth --runtime all` → 强制安装到全部四个 runtime（无论是否检测到）

**需要补充现有实现：** 当前 `SkillDetector.detect_install_targets(runtime=["all"])` 会回退到“当前项目已检测到的可用目标”，不等价于强制四个 runtime 全量安装。因此若保留 `--runtime all` 的语义，需要同步修改 `SkillDetector` 与对应测试。

**`SKILL_MCP.md` 的安装方式与 `SKILL.md` 完全相同**，安装时 `shutil.copytree` 会整体复制模板目录。需要注意：`SkillDetector.discover()` 的发现单位是 Skill 目录（依据 `data/VERSION.json`），不会把 `SKILL_MCP.md` 当作独立 Skill 发现。

> **实施说明**：`SKILL_MCP.md` 与 `SKILL.md` 同属同一 Skill 模板目录。验收应检查安装后的 Skill 目录中存在 `SKILL_MCP.md`，而不是期待 `opscli skills list` 额外列出该文件。

#### 3.3.2 `ops-auth/SKILL_MCP.md` 核心内容提纲

```markdown
# ops-auth（MCP 版）

## 调用方式
通过 opscli MCP Server 的 auth_* Tools 调用，无需 subprocess。

## 登录工作流（两步）
1. auth_login_start()         → 获取 URL + user_code，展示给用户
2. auth_login_poll(device_code) → 每 3 秒轮询一次，直到 authorized

## Token 管理
- auth_get_token(system)          → 获取 JWT（自动刷新）
- auth_check_token(system)        → 检查有效期
- auth_token_refresh(system)      → 强制刷新

## 系统管理
- auth_system_list()              → 查看所有系统
- auth_system_add(alias, url)     → 添加自定义系统

## 与 CLI 版的核心差异
| 操作 | CLI 版 | MCP 版 |
|------|--------|--------|
| 登录 | opscli auth login（同步阻塞） | start + poll 两步（异步） |
| 获取 JWT | opscli auth token get -s ops | auth_get_token("ops") |
| 错误处理 | 检查退出码 | 检查 data["success"] |
```

#### 3.3.3 `ops-dataset-query/SKILL_MCP.md` 核心内容提纲

```markdown
# ops-dataset-query（MCP 版）

## 前置要求
先调用 auth_is_authenticated() 检查登录状态；
未登录时调用 auth_login_start() + auth_login_poll() 完成授权。

## 标准查询工作流
1. query_metadata(dataset="xxx")           → 查看字段定义
2. query_build_and_run(                    → 构造并执行查询
     dataset="xxx",
     dimensions=["date_id"],
     metrics=["sales:SUM"],
     limit=50
   )

## 高级查询（需手写 payload）
使用 query_build(dry_run=True) 生成 payload 后，
修改 payload 文件，再用 query_run(payload_path) 执行。

## 与 CLI 版的核心差异
- 无需 subprocess，直接获取 Python dict 返回值
- 无需 --output 文件中转，build 结果直接可用
- 错误通过 data["error"]["code"] 判断，无需解析 stderr
```

#### 3.3.4 `ops-mcp` Skill 核心内容提纲

```markdown
# ops-mcp

负责 opscli MCP Server 的启动、用户管理和接入配置。

## 启动服务
opscli-mcp                                      # stdio 模式
opscli-mcp --transport sse --port 8765          # SSE 模式

## 多用户管理
opscli mcp user list                            # 查看所有用户
opscli mcp user add --desc "描述"               # 创建用户，获取 API Key
opscli mcp user remove --id <user_id>          # 删除用户
opscli mcp user rotate --id <user_id>          # 轮换 API Key

## Claude Desktop 接入配置模板
（含 stdio / SSE 两种接入方式的完整配置示例）

## 故障排查
- 检查服务端口：lsof -i :8765
- 查看日志：tail -f /tmp/opscli-mcp-sse.log
- 验证 API Key：curl -H "Authorization: Bearer <key>" http://localhost:8765/sse
```

#### 3.3.5 验收标准

- `ops-auth` 与 `ops-dataset-query` 安装后，目标目录中均包含 `SKILL.md` 和 `SKILL_MCP.md`
- 新增 `ops-mcp` Skill 可通过 `opscli skills install ops-mcp` 安装，并可被 `opscli skills list` 发现
- `SKILL_MCP.md` 中的所有 Tool 调用示例可在当前 MCP Server 上实际运行
- `ops-mcp` Skill 的用户管理命令与阶段二实现保持一致
- `--runtime all` 如作为强制四 runtime 安装能力交付，必须有 detector 单测覆盖

---

## 四、变更影响评估

### 4.1 现有功能兼容性

| 模块 | 影响 | 说明 |
|------|------|------|
| 现有 CLI（opscli auth/query/skills） | ✅ 无影响 | MCP 模块完全独立，不修改 CLI 逻辑 |
| 现有 `SKILL.md` | ✅ 无影响 | 新增 `SKILL_MCP.md` 并存，不改动原文件 |
| 现有单机单用户模式 | ✅ 兼容 | 不启用 `--multi-user` 时保持当前行为 |
| 现有 9 个 MCP Tool | ✅ 兼容 | 阶段一只新增；阶段二加入 `Context` 后客户端可见业务签名不变 |
| 凭证存储（CredentialStore） | ⚠️ 谨慎 | 多用户模式通过 `base_dir` 隔离，不修改存储逻辑本身 |
| amazon 模块 | ✅ 无影响 | 本期不纳入 MCP Tool 覆盖范围，后续单独规划 |

### 4.2 铁律合规检查

| 铁律 | 遵守情况 |
|------|---------|
| 铁律1：新增模块接入规范 | `opscli/mcp/cli.py` 通过标准方式在 `opscli/cli.py` 注册 |
| 铁律2：禁止破坏导入链 | `opscli/mcp/` 仅向上依赖 Service 层，不引入循环导入 |
| 铁律5：Keychain 服务名不变 | 多用户模式不走 Keychain（`base_dir` 非 None 时自动跳过） |
| 铁律6：并发锁不删减 | Tool 调用 Service 层，并发锁由 Service 层维护，MCP 层无需关心 |
| 铁律8：测试不依赖真实 Keychain | 新增测试均使用 `tmp_path` fixture |
| 铁律10：Skill 脚本禁止直连后端 | `SKILL_MCP.md` 中所有操作均通过 MCP Tool 调用，不直接 HTTP |
| 铁律11：Skill 命名 `ops-` 前缀 | 新增 `ops-mcp` Skill 符合命名规范 |
| 铁律13：依赖不加上限 | pyproject.toml 中 `fastmcp>=2.0` 无上限 |
| 铁律14：文档中文命名 | 计划书文件名使用中文 |
| 铁律15：代码中文注释 | 所有新增代码均需中文注释 |

---

## 五、文件变更总览

### 新增文件（13 个）

```
opscli/mcp/user_store.py                              # 阶段二
opscli/mcp/auth_middleware.py                         # 阶段二
opscli/mcp/context.py                                 # 阶段二
opscli/mcp/cli.py                                     # 阶段二
opscli/skills/templates/ops-auth/SKILL_MCP.md         # 阶段三
opscli/skills/templates/ops-dataset-query/SKILL_MCP.md # 阶段三
opscli/skills/templates/ops-mcp/data/VERSION.json     # 阶段三
opscli/skills/templates/ops-mcp/SKILL.md              # 阶段三
tests/mcp/test_tools.py                               # 阶段一
tests/mcp/test_user_store.py                          # 阶段二
tests/mcp/test_auth_middleware.py                     # 阶段二
tests/mcp/test_cli.py                                 # 阶段二
tests/mcp/test_multi_user_isolation.py                # 阶段二
```

### 修改文件（7 个）

```
opscli/mcp/server.py        # 阶段一：新增 12 个 Tool；阶段二：注入 Context
opscli/auth/core/device_flow.py # 阶段一：新增非阻塞 poll_once
opscli/cli.py               # 阶段二：注册 mcp 子模块
opscli/skills/discovery/detector.py # 阶段三：修正 --runtime all 语义（如交付该能力）
README_MCP.md               # 阶段一/二/三：同步更新文档
pyproject.toml              # 版本号更新（0.0.9 → 0.1.0，标志 MCP 完整支持）
docs/plans/MCP服务完善整改计划书.md # 本文件：方案修订与范围校准
```

---

## 六、实施时间计划

```
阶段一：补全 MCP Tools           预计 2 天
  Day 1 上午  补充 DeviceFlow.poll_once；补充 auth_login_start / auth_login_poll
  Day 1 下午  补充 auth_logout / auth_token_refresh
  Day 1 下午  补充 auth_system_* / auth_build_request_auth / auth_doctor
  Day 2 上午  补充 skills_install / skills_upgrade；编写测试；更新 README_MCP.md

阶段二：多用户认证               预计 3.5 天
  Day 1      user_store.py + 原子写 + 权限控制 + CLI 用户管理
  Day 2      FastMCP auth/middleware 最小验证；auth_middleware.py + context.py
  Day 3      server.py 改造（所有凭证相关 Tool 注入 Context）
  Day 3.5    stdio / SSE 多用户隔离端到端测试

阶段三：MCP 版 Skills            预计 1.5 天
  Day 1      ops-auth/SKILL_MCP.md + ops-dataset-query/SKILL_MCP.md + ops-mcp/ Skill
  Day 1.5    修正/验证 --runtime all 语义；补齐安装与发现测试
```

---

## 七、风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| fastmcp Context 注入 API 与预期不符 | 中 | 中 | 阶段二开始前先验证 fastmcp 3.x Context 传递方式，必要时查阅官方文档 |
| FastMCP 鉴权 API 在 stdio / SSE 行为不同 | 中 | 高 | 先做最小样例验证，再实现正式 auth_middleware；stdio 使用 env API Key 兜底 |
| `auth_login_poll` 被 AI Agent 频繁调用触发后端限流 | 中 | 中 | 返回并文档化后端 interval；Skill_MCP 明确 3 秒以上轮询，必要时后续在服务端做按用户限频 |
| 多用户模式引入的凭证目录权限问题 | 低 | 高 | 凭证目录权限设为 `700`，.key 文件权限设为 `600`，复用现有 CredentialStore 的权限逻辑 |
| 版本升级破坏现有单机用户的凭证 | 极低 | 高 | 多用户路径在 `users/` 子目录下，不覆盖现有 `credentials.bin` 和 `.key` |
| API Key 泄露 | 低 | 高 | 服务端只存哈希；提供 `rotate` 命令快速轮换；文档中明确提示 Key 不重复展示 |
| `SKILL_MCP.md` 被误认为独立 Skill | 中 | 低 | 验收改为检查安装目录文件存在；`opscli skills list` 只发现 Skill 目录 |

---

## 八、附录

### A. 整改后完整 Tool 列表（21 个）

```
# 数据查询（4 个，现有）
query_metadata
query_build
query_run
query_build_and_run

# 认证授权（13 个，10 个新增）
auth_login_start          ← 新增
auth_login_poll           ← 新增
auth_logout               ← 新增
auth_token_refresh        ← 新增
auth_get_token
auth_check_token
auth_is_authenticated
auth_system_list          ← 新增
auth_system_add           ← 新增
auth_system_remove        ← 新增
auth_system_sync          ← 新增
auth_build_request_auth   ← 新增
auth_doctor               ← 新增

# Skill 管理（4 个，2 个新增）
skills_list
skills_status
skills_install            ← 新增
skills_upgrade            ← 新增
```

> MCP 用户管理通过 `opscli mcp user list/add/remove/rotate` CLI 提供，不进入普通 MCP Tool 列表。

### B. API Key 格式规范

```
格式：opscli-mcp-{32位随机字符}
示例：opscli-mcp-AbCdEfGhIjKlMnOpQrStUvWxYz123456
前缀：opscli-mcp-（固定，便于识别和过滤）
长度：总长度 43 字符
存储：SHA256(api_key) → hex string，存入 mcp_users.json
```

生成建议：使用 `secrets` 生成不低于 128 bit 熵的随机值；若使用 URL-safe base64，需要测试最终长度并保持文档示例一致。

### C. MCP Server 启动参数完整列表（整改后）

```bash
opscli-mcp                                     # stdio，单用户模式
opscli-mcp --transport sse --port 8765         # SSE，单用户模式
OPSCLI_MCP_API_KEY=opscli-mcp-xxx opscli-mcp \
  --multi-user                                  # stdio，多用户模式，绑定 env API Key
opscli-mcp --transport sse --port 8765 \
  --multi-user --require-auth                   # SSE，强制要求 API Key（无 Key 返回 401）
```

### D. 修订后实施前检查清单

- Tool 总数目标确认：最终为 21，不包含 MCP 用户管理 Tool
- 本期范围确认：不覆盖 `opscli/amazon`
- 登录轮询确认：先实现非阻塞 `poll_once`，再写 MCP Tool
- 多用户确认：默认单用户兼容，只有 `--multi-user` 才启用隔离
- Skill 验收确认：`SKILL_MCP.md` 是同一 Skill 目录内的附加指南，不是独立 Skill
- 测试确认：所有网络请求使用 `respx` mock，所有凭证路径使用 `tmp_path`

---

*本计划书经审阅确认后，按阶段逐步实施。*
