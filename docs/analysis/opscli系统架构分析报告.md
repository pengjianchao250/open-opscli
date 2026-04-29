# opscli 系统架构深度分析报告

> 生成日期：2026-04-28

## 一、系统概览

| 指标 | 数据 |
|------|------|
| 包名 | `aukeys-opscli` v0.0.23 |
| Python 要求 | >= 3.10 |
| 源码文件 | 112 个 `.py` 文件 |
| 源码总行数 | ~16,293 行 |
| 测试文件 | 32 个 |
| 模块数 | 5 个核心模块（auth / mcp / query / skills / amazon） |
| 依赖项 | typer, httpx, cryptography, rich, keyring, fastmcp, playwright |

---

## 二、架构总览

### 2.1 分层架构

```
┌─────────────────────────────────────────────────┐
│                  CLI 入口层                       │
│  opscli/cli.py → 注册 auth/amazon/query/skills/mcp│
├─────────────────────────────────────────────────┤
│              命令层 (commands/cli)                  │
│  每个模块: commands/cli.py → Typer 子命令注册      │
├─────────────────────────────────────────────────┤
│              服务层 (services/manager)             │
│  每个模块: manager.py → 业务编排逻辑               │
├─────────────────────────────────────────────────┤
│              传输层 (transport/client)             │
│  HTTP 客户端封装，与远端服务交互                     │
├─────────────────────────────────────────────────┤
│              领域层 (domain/models+exceptions)     │
│  数据模型 + 异常定义，所有异常支持 to_dict()         │
├─────────────────────────────────────────────────┤
│              基础设施层                            │
│  config (全局配置) / auth (认证SDK) / storage (凭证)│
└─────────────────────────────────────────────────┘
```

每个模块遵循一致的分层: `commands/cli` → `services/manager` → `domain/{models,exceptions}` → `transport/client`，包根通过重导出 shim 保持 API 稳定。

### 2.2 模块依赖图

```
                ┌──────────┐
                │  cli.py   │ (顶层入口，注册5个子模块)
                └─────┬─────┘
       ┌──────┬───────┼───────┬──────────┐
       ▼      ▼       ▼       ▼          ▼
   ┌───────┐┌──────┐┌─────┐┌──────┐┌────────┐
   │ auth  ││amazon││query││skills ││  mcp   │
   └───┬───┘└──┬───┘└──┬──┘└──┬───┘└───┬────┘
       │       │       │      │        │
       ▼       ▼       ▼      ▼        ▼
   ┌─────────────────────────────────────────┐
   │           共享基础设施层                    │
   │  config.py → auth(AuthClient/SDK) →     │
   │  storage(CredentialStore/Crypto)        │
   └─────────────────────────────────────────┘
```

**交叉依赖关系：**

- `mcp/tools/*` → `auth.AuthClient` + `credential_cache` + `query.services.QueryManager` + `skills.services.SkillsManager` + `amazon.services.AmazonManager`
- `query/services/manager.py` → `auth.AuthClient` + `skills.discovery.SkillDetector`
- `skills/sync/updater.py` → `auth.AuthClient`
- `amazon/transport/client.py` → `auth.AuthClient` + `auth.config`

**依赖方向铁律遵守情况：** `config.py` 是纯叶子节点（仅依赖标准库），**无循环依赖问题**。

### 2.3 内部模块依赖详情

| 模块文件 | 内部依赖数 | 依赖目标 |
|----------|-----------|---------|
| `mcp/tools/helpers.py` | 5 | auth, credential_cache, system_registry, query.manager |
| `mcp/tools/auth.py` | 5 | auth, device_flow, credential_store, credential_cache, helpers |
| `auth/cli.py` | 5 | auth, device_flow, system_registry, exceptions, credential_store |
| `skills/services/manager.py` | 5 | config, detector, exceptions, models, updater |
| `query/services/manager.py` | 5 | auth, exceptions, models, client, detector |
| `amazon/transport/client.py` | 4 | auth, config, exceptions, models |
| `amazon/services/manager.py` | 4 | config, models, scraper, client |

---

## 三、五大核心模块详解

### 3.1 auth 模块（认证授权）

| 组件 | 文件 | 行数 | 职责 |
|------|------|------|------|
| `AuthClient` | `auth/__init__.py` | 99 | SDK 入口，多系统认证封装 |
| `TokenManager` | `auth/core/token_manager.py` | 198 | JWT 生命周期管理，双锁并发控制 |
| `DeviceFlow` | `auth/core/device_flow.py` | 104 | OAuth2 Device Flow (RFC 8628) |
| `SystemRegistry` | `auth/core/system_registry.py` | 93 | 系统注册表 (builtin/local/ops_sync) |
| `CredentialStore` | `auth/storage/credential_store.py` | 183 | Keychain 优先 / AES-256-GCM 兜底 |
| `Crypto` | `auth/storage/crypto.py` | 67 | AES-256-GCM 加密 |
| CLI | `auth/cli.py` | 255 | login/logout/token/system/doctor |

**核心设计：**

- **双存储策略**：macOS Keychain 优先 → AES-256-GCM 本地文件兜底
- **双锁并发控制**：`threading.Lock`（线程级）+ `fcntl.flock()`（进程级），防止 JWT 惊群刷新
- **三态 Token**：`valid / needs_refresh / expired`，过期前 5 分钟自动刷新
- **Session 30 天有效期**，每次浏览器授权自动续期

### 3.2 mcp 模块（AI Agent 工具服务）

| 组件 | 文件 | 行数 | 职责 |
|------|------|------|------|
| `FastMCP` | `mcp/server.py` | 288 | MCP 服务入口，支持 stdio/sse/http/both |
| `ApiKeyAuthMiddleware` | `mcp/auth_middleware.py` | 140 | API Key 鉴权中间件 |
| `McpCredentialCache` | `mcp/credential_cache.py` | 139 | 线程安全内存凭证缓存 |
| `MCPUserStore` | `mcp/user_store.py` | 233 | 多用户 API Key 注册表，SHA256 哈希 |
| auth tools | `mcp/tools/auth.py` | 434 | 12 个认证工具 |
| query tools | `mcp/tools/query.py` | 244 | 5 个查询工具 |
| skills tools | `mcp/tools/skills.py` | 116 | 4 个技能工具 |
| amazon tools | `mcp/tools/amazon.py` | 258 | 5 个 Amazon 工具 |
| chatgpt tools | `mcp/tools/chatgpt.py` | 329 | 2 个 OpenAI 兼容工具 |
| helpers | `mcp/tools/helpers.py` | 213 | 共享辅助函数 |

**暴露 28+ 个 MCP Tools**，AI Agent 可通过 API Key 鉴权调用全部 CLI 能力。

### 3.3 query 模块（数据查询）

| 组件 | 行数 | 职责 |
|------|------|------|
| `QueryManager` | 687 | 元数据加载、payload 构造、chart 查询、build_and_run |
| `QueryClient` | 100 | HTTP 转发远端查询服务 |
| CLI | — | metadata/build/run/chart 子命令 |

**亮点**：支持"维度+指标+筛选"的简化 DSL 自动构造 payload，自动填充 `userEmail`、`table`、`permission` 等安全字段。

### 3.4 skills 模块（Skill 生命周期管理）

| 组件 | 行数 | 职责 |
|------|------|------|
| `SkillsManager` | 408 | install/list/status/upgrade |
| `SkillDetector` | 250 | 多运行时扫描（claude/openclaw/codex/opencode） |
| `SkillsUpdater` | 331 | 远端数据拉取，原子替换升级 |
| 内置模板 | — | ops-auth / ops-dataset-query / ops-amazon / ops-cross-border-product-selector / ops-skills |

### 3.5 amazon 模块（Amazon 数据采集）

| 组件 | 行数 | 职责 |
|------|------|------|
| `AmazonScraper` | 410 | Playwright 异步爬虫，隐身模式、验证码绕过、邮编模拟 |
| `AmazonManager` | 105 | 爬取+提交编排 |
| `AmazonOpsClient` | 77 | ops API 快照提交 |
| CLI | 200 | scrape/payload/search/schema/history 子命令 |

---

## 四、潜在问题分析

### 4.1 🔴 高优先级问题

#### 问题1：HTTP 响应解析逻辑重复

`query/transport/client.py` 和 `amazon/transport/client.py` 各自实现了几乎相同的 HTTP 响应解析逻辑（JSON 解码 → 状态码检查 → 业务码检查 → 错误提取），代码重复约 80%。

**影响**：未来维护需同步修改两处，易遗漏导致行为不一致。

**建议**：提取为 `opscli/shared/http_client.py` 共享基础响应解析器。

#### 问题2：AuthClient 实例化紧耦合

`mcp/tools/helpers.py`、`skills/sync/updater.py`、`amazon/transport/client.py` 等多处直接 `AuthClient()` 创建实例，无法注入替代实现：

```python
# mcp/tools/helpers.py 内部
def _auth_client() -> AuthClient:
    return AuthClient()  # 硬编码，无法在测试中替换
```

**影响**：单元测试困难，必须依赖真实 Keychain 或复杂的 mock。

**建议**：引入依赖注入模式，通过构造函数或函数参数传入 `AuthClient` 实例。

#### 问题3：静默异常吞噬

至少 3 处关键路径存在 `except Exception: pass`：

| 位置 | 影响 |
|------|------|
| `auth/cli.py` login 后系统同步 | 网络故障或鉴权失败被静默忽略 |
| `skills/services/manager.py` 注册表写入 | 安装失败无反馈 |
| `credential_store.py` 解密失败 | 直接删除损坏文件而非备份恢复 |

**建议**：至少改为 `logging.warning()` 记录异常，关键路径提示用户。

#### 问题4：异常体系不统一

`QueryError` 和 `AmazonError` 各自独立实现 `to_dict()`、`code`/`message` 字段和 HTTP 状态码处理逻辑，结构几乎相同但无共享基类。

**建议**：创建 `opscli/shared/exceptions.py`，定义 `RemoteError` 基类，所有远端交互异常继承它。

### 4.2 🟡 中优先级问题

#### 问题5：线程锁池无限增长

`token_manager.py` 的 `_thread_locks: dict[str, threading.Lock]` 是模块级字典，每新增一个 `system_key` 就创建一个 Lock，永不回收：

```python
_thread_locks: dict[str, threading.Lock] = {}

def _get_lock(key: str) -> threading.Lock:
    if key not in _thread_locks:
        _thread_locks[key] = threading.Lock()
    return _thread_locks[key]
```

**影响**：理论上可能内存泄漏（实际风险低，因为系统数量有限）。

**建议**：改用 `functools.lru_cache` 或加清理机制。

#### 问题6：API Key 生成逻辑重复

`mcp/server.py` 的 `_generate_api_key()` 和 `mcp/user_store.py` 的 `_new_api_key()` 各自实现了 `opscli-mcp-` 前缀 + 32 位随机字符的生成逻辑。

**建议**：提取到共享工具函数。

#### 问题7：配置硬编码

以下关键配置无法通过 `config.ini` 或环境变量修改：

| 配置 | 位置 | 值 |
|------|------|----|
| `REFRESH_THRESHOLD` | `token_manager.py` | 300s |
| `MAX_JWT_TTL` | `token_manager.py` | 86400s |
| MCP 默认端口 | `server.py` | 8765 |
| MCP 默认主机 | `server.py` | 0.0.0.0 |
| 默认服务地址 | `auth/config.py` | qa 环境 |

**建议**：将可调常量移至 `config.ini` 或环境变量。

#### 问题8：`mcp/context.py` 全是空壳

该文件仅包含 3 个 no-op 函数（`configure_multi_user`、`is_multi_user_enabled`、`get_credential_dir`），纯向后兼容层，增加理解成本。

**建议**：加 `DeprecationWarning` 或直接移除。

#### 问题9：Playwright 强依赖

`amazon` 模块的 `playwright` 作为主依赖写在 `pyproject.toml`，但对于不使用 Amazon 功能的用户，这是约 50MB+ 的安装开销。

**建议**：将 `playwright` 移到 `[amazon]` 可选依赖组。

### 4.3 🟢 低优先级问题

#### 问题10：缺乏结构化日志

多处使用 `print()` 到 `sys.stderr`（如 `mcp/server.py`），而非 Python `logging` 模块。运维排障困难。

#### 问题11：`version.py` 回退版本与 pyproject.toml 不一致

`version.py` 回退值为 `0.0.11-dev`，但 `pyproject.toml` 版本已是 `0.0.23`，README 仍写 `0.0.4`。三处版本号需统一。

#### 问题12：MCP Tool 函数返回类型标注不完整

`mcp/tools/helpers.py` 多个函数返回 `Any` 或缺少类型标注，影响 IDE 补全和文档生成。

#### 问题13：测试覆盖缺口

以下关键模块缺少对应测试：

- `mcp/auth_middleware.py` — 安全关键路径，无单测
- `amazon/scraping/scraper.py` — Playwright 集成，理解上难以单测但应有集成测试
- `query/services/manager.py` — 687 行核心业务逻辑，测试覆盖偏薄

---

## 五、优化建议总结

| 优先级 | 优化项 | 预估工作量 | 收益 |
|--------|--------|-----------|------|
| 🔴 P0 | 提取共享 HTTP 响应解析器 | 2-3 天 | 消除 ~80% 代码重复 |
| 🔴 P0 | AuthClient 依赖注入改造 | 3-5 天 | 大幅提升可测试性 |
| 🔴 P0 | 关键路径异常日志化 | 1 天 | 避免静默失败 |
| 🔴 P0 | 统一异常基类 | 1-2 天 | 统一错误处理模式 |
| 🟡 P1 | 可配置化常量 | 1 天 | 运维灵活性 |
| 🟡 P1 | 移除 context.py 空壳 | 0.5 天 | 降低理解成本 |
| 🟡 P1 | 合并 API Key 生成 | 0.5 天 | 消除重复 |
| 🟡 P1 | Playwright 移至可选依赖 | 1 天 | 减轻非 amazon 用户的安装负担 |
| 🟢 P2 | 结构化 logging 替换 print | 2 天 | 生产运维可观测性 |
| 🟢 P2 | 版本号三处统一 | 0.5 天 | 一致性 |
| 🟢 P2 | 补充 MCP 鉴权中间件单测 | 2 天 | 安全保障 |
| 🟢 P2 | MCP Tool 类型标注完善 | 1 天 | 文档和 IDE 体验 |

---

## 六、架构优势总结

1. **分层清晰**：每模块严格遵循 `commands → services → domain → transport` 四层，重导出 shim 保持 API 稳定
2. **双认证存储设计可靠**：Keychain 优先 + AES-256-GCM 兜底，跨平台安全
3. **并发安全度设计成熟**：线程锁 + 文件锁双层防护，避免 JWT 惊群刷新
4. **MCP 无状态架构**：凭证不存储在 MCP 服务端，安全风险低
5. **异常体系可序列化**：所有异常支持 `to_dict()`，便于 JSON API 输出
6. **Skill 多运行时适配**：同时支持 Claude Code / OpenClaw / Codex / OpenCode 四种运行时
7. **CLAUDE.md 开发铁律体系完善**：17 条铁律 + 文档规范，保障团队开发一致性