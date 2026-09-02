# SDK 调用规范

> 版本：v1.0（2026-09-01）
> 适用范围：所有在 Python 代码中导入并调用 `opscli` 包（`aukeys-opscli`）的业务模块、Skill 脚本、外部项目与服务端集成。
> 配套文档：[SDK使用文档](../guide/SDK使用文档.md)（面向使用者的 API 参考手册）。

---

## 1. 总则

`opscli` 既是 CLI 工具，也是以 Python 包形式分发的 SDK。本规范约束**所有 SDK 形态的调用**（`import opscli` 及其子模块），与 CLAUDE.md 中【铁律3】【铁律8】【铁律9】【铁律11】保持一致并细化。

### 1.1 核心原则：授权使用显式调用

SDK 的授权必须**显式发起、显式传入、显式检查**，禁止任何形式的隐式授权：

| 编号 | 原则 | 含义 |
| ---- | ---- | ---- |
| E-1 | **显式发起** | 交互式登录（Device Flow）只能通过 `opscli auth login` CLI 或 MCP 侧 `auth_login_start` / `auth_login_poll` 显式发起。`AuthClient` 的任何方法都**不会**拉起浏览器或等待用户授权，SDK 调用永远不会"顺带"触发登录 |
| E-2 | **显式传入** | SDK 拿不到授权态时直接抛出 `NotAuthenticatedError`，绝不静默降级为匿名请求或自动登录。需要外部凭证的场景，调用方必须把 `session_id` / `jwt` **作为参数显式传入** Client / Manager 构造函数 |
| E-3 | **显式检查** | 调用业务方法前，调用方应显式调用 `is_authenticated()` 或 `check_token(alias)` 确认授权态，而不是依赖异常兜底 |
| E-4 | **显式生命周期** | 显式凭证（`ExplicitCredentials` / 构造参数中的 jwt、session_id）只存活在调用方指定的作用域内：进程上下文凭证**绝不落盘**，构造参数凭证**绝不写入** `CredentialStore`。凭证的保管责任在调用方 |
| E-5 | **显式系统别名** | 所有取 token / 构造认证头的方法必须显式指定系统别名 `"ops"` 或 `"polaris"`，禁止依赖隐式默认系统 |

### 1.2 三种合法授权方式（三选一）

| 方式 | 机制 | 适用场景 | 落盘 |
| ---- | ---- | -------- | ---- |
| A. 本地登录态 | 先执行 `opscli auth login` 建立持久登录态，SDK 经 `CredentialStore` 读取（Keychain 优先 / AES-256-GCM 兜底） | 本机脚本、定时任务、开发者环境 | 是（加密） |
| B. 无状态显式凭证 | 向 Client / Manager 构造函数显式传 `session_id`（必配 `jwt` 可选，缺失时用 session 向后端实时换取、不落盘） | 服务端、MCP 共享环境、多用户隔离 | 否 |
| C. 进程级显式凭证上下文 | `ExplicitCredentials` + `set_explicit_credentials()` 注入 `contextvars`，或 CLI 任意子命令尾部追加 `--session-id` / `--ops-jwt-token` / `--polaris-jwt-token` | CLI 中间件、需要整条调用链统一换身份的场景 | 否 |

三种方式可以叠加，**优先级**为：C（显式上下文）> B（构造参数）> A（本地登录态）。叠加时高位凭证完全遮蔽低位，不会混合使用。

### 1.3 授权方式选型决策

```
是否是本机交互环境且已有 opscli 登录态？
├─ 是 → 方式 A（AuthClient() 默认构造即可，调用前 is_authenticated() 显式检查）
└─ 否（服务端 / 多用户 / 容器）
   ├─ 每个请求/租户有独立 session_id？
   │  ├─ 是 → 方式 B（Client(session_id=..., jwt=...)）
   │  └─ 否 → 方式 C（进程启动时 set_explicit_credentials(...)，全链路生效）
```

禁止的授权方式：自拼 `Authorization` 头、直接读取 `credentials.bin` / Keychain、硬编码 token、用环境变量偷传 JWT（SIF 等第三方平台自有 token 除外，见 §6.4）。

---

## 2. 导入规范

【铁律3】两种导入方式必须同时可用，调用方优先使用第二种（显式子模块路径，依赖更清晰）：

```python
from opscli import AuthClient          # 合法：顶层 re-export
from opscli.auth import AuthClient     # 推荐：子模块直连
```

其余模块的导入规则：

1. **只导入包根 `__init__.py` 明确 re-export 的符号**。例如 `from opscli.shopify import ShopifyManager`、`from opscli.feedback import FeedbackClient`。
2. 包根未导出的类（如 `opscli.seller_sprite.services.api_manager.SellerSpriteApiManager`、`opscli.xiyou.services.api_manager.XiyouApiManager`）属于**内部实现**，导入需写完整路径，并在调用方注释中注明"内部类，升级可能变动"。
3. **禁止**导入 `_` 前缀私有成员、`opscli.*.transport.*` 的传输细节函数，以及 `opscli.mcp.session_store`（已废弃，见【铁律9】）。
4. `opscli.config` 只能被用来读 `CONFIG_DIR` 与 `__version__`，禁止反向导入任何子模块（【铁律2】依赖方向）。

---

## 3. 授权调用规范（核心）

### 3.1 方式 A：本地登录态（显式前置检查）

```python
from opscli.auth import AuthClient
from opscli.auth.exceptions import NotAuthenticatedError

client = AuthClient()          # 可选 base_dir=Path 指定凭证目录（测试必传，见 §8）

# E-3：调用前显式检查，而不是吞 NotAuthenticatedError
if not client.is_authenticated():
    raise RuntimeError("未登录，请先执行: opscli auth login")

headers, cookies = client.build_request_auth("ops")   # E-5：显式系统别名
```

要点：

- 登录动作本身必须由用户在终端显式执行 `opscli auth login`（Device Flow，300 秒超时），SDK 代码中**不得**调用 `opscli/auth/core/device_flow.py`。
- `get_token(alias)` 内部会自动刷新临期 JWT（距过期 < `REFRESH_THRESHOLD`），这是**刷新**不是**登录**，不违反 E-1。
- `base_dir` 仅允许在测试中传入 `tmp_path`；生产代码必须使用默认路径（见 §8）。

### 3.2 方式 B：无状态显式凭证（推荐服务端使用）

所有标准业务 Client / Manager 遵循统一构造范式：

```python
ClientName(
    auth_client: AuthClient | None = None,  # 缺省时内部创建 AuthClient()
    jwt: str | None = None,                 # 显式传入的 JWT
    session_id: str | None = None,          # 显式传入的会话 ID
)
```

鉴权解析顺序（各模块 `_get_auth` 统一语义）：

1. `session_id` 非空 → **无状态模式**：有 `jwt` 用 `jwt`，没有则用 `session_id` 向后端实时换取（`AuthClient.get_token_by_session`），全程**不读、不写**本地 `CredentialStore`；
2. 否则 `jwt` 非空 → 仅用该 JWT 构造 `Authorization` 头；
3. 否则 → 回退本地登录态（`build_request_auth(alias)`，此时方式 C 的显式上下文仍会生效）。

```python
from opscli.query import QueryManager

# 会话 + JWT 全显式：请求与本地登录用户完全隔离
qm = QueryManager(session_id=external_session_id, jwt=external_jwt)
result = qm.run_payload(payload_dict)
```

要点：

- 传了 `session_id` 就**必须接受**它会作为 `polarisUserToken` cookie 随请求发送的事实——session 与 JWT 必须同源同环境（见 §7 的 407 说明）。
- 无状态模式不落盘是双向承诺：SDK 不写，调用方也不要期望 SDK 帮它持久化。
- 长驻服务应自行处理 JWT 过期：捕获 `TokenFetchError` 后重新换取，或定期调用 `refresh_token` / 重新传入新 jwt。

### 3.3 方式 C：进程级显式凭证上下文

```python
from opscli.auth.context import ExplicitCredentials, set_explicit_credentials, get_explicit_credentials

creds = ExplicitCredentials(
    session_id="abc123",          # 必填
    ops_jwt="eyJ...",             # 可选，缺失时用 session_id 换取
    polaris_jwt="eyJ...",         # 可选
)
set_explicit_credentials(creds)   # 注入当前上下文；传 None 表示清除
```

约束：

1. 存储介质是 `contextvars.ContextVar`：**请求级、进程内**，协程/线程安全，绝不落盘（E-4）。
2. 注入后，`AuthClient.get_token / get_session / is_authenticated` 在当前上下文内自动优先消费显式凭证——业务代码**不需要也不应该**自行读取 `get_explicit_credentials()`（单点注入设计，业务模块直接享受）。
3. 只在"整条调用链统一换身份"时使用（如 CLI 中间件、任务 worker）；同一进程内并发处理多用户时必须用方式 B 按请求隔离。
4. CLI 等价形式：任意子命令尾部追加 `--session-id <id>`（提供了任一 JWT 时必填，缺失时退出码 2）、`--ops-jwt-token`、`--polaris-jwt-token`。

### 3.4 MCP 场景补充

MCP Tool 的授权遵循"**每工具显式传参**"：业务工具一律携带 `session_id`（必填）与 `jwt`（可选）参数，Tool 实现内部把它转成方式 B 构造 Client。Tool 实现本身禁止从进程全局状态猜测用户身份（按 API Key 隔离的凭证目录除外，见 `README_MCP.md`）。HTTP/SSE 传输层的 API Key 鉴权是**连接鉴权**，不能替代工具级 `session_id`。

---

## 4. 统一鉴权调用规范

### 4.1 唯一取凭证入口

业务代码获取请求认证参数，**只能**通过以下三个方法（与《开发规范》9.5 一致）：

| 方法 | 返回 | 用途 |
| ---- | ---- | ---- |
| `AuthClient.build_request_auth(alias)` | `(headers, cookies)`：`Authorization: Bearer <jwt>`、`X-Opscli-Version`、`polarisUserToken` cookie、`opscliDeviceCode` cookie（若有） | 调用 ops / polaris 业务 API 的默认方式 |
| `AuthClient.build_session_headers(alias=None)` | `{"X-Session-Id": ..., "X-Opscli-Version": ...}` | 只需要会话标识的接口（如 AppHub） |
| `AuthClient.get_token_by_session(session_id, alias)` | JWT 字符串 | 无状态换取（方式 B 内部机制，业务代码一般不直接调） |

### 4.2 禁止行为

| 禁止 | 正确做法 |
| ---- | -------- |
| 手拼 `headers = {"Authorization": f"Bearer {token}"}`（token 来源任意） | `headers, cookies = client.build_request_auth("ops")` |
| 直接实例化 `CredentialStore()` / `TokenManager()` 读凭证或 token | 统一经 `AuthClient`；确需底层能力时先在架构评审中立项 |
| 读取 `~/.config/opscli/credentials.bin` 或 Keychain 服务 `opscli-auth` | 同上 |
| 在显式凭证路径上把 session/jwt 写文件、写日志、写异常文本 | 凭证只经内存传递；日志只允许脱敏摘要（如 session 前 6 位） |
| 缓存 `ExplicitCredentials` 或把它存到模块级变量 | 每请求构造，或走方式 B 传参 |
| Skill 脚本绕过 opscli 直连后端 HTTP | 【铁律11】：Skill 只能 `subprocess` 调 `opscli` 子命令 |

### 4.3 新增模块的鉴权接入范式

新增模块的 Client 必须复制标准范式（参考 `opscli/shopify/transport/client.py`）：

```python
class XxxClient:
    def __init__(self, auth_client=None, jwt=None, session_id=None):
        self.auth_client = auth_client or AuthClient()
        self.jwt = jwt
        self.session_id = session_id

    def _get_auth(self, alias: str = "ops") -> tuple[dict, dict]:
        # 1) 显式 session 优先（无状态，不落盘）  2) 显式 jwt  3) 本地登录态/显式上下文
        if self.session_id:
            jwt = self.jwt or self.auth_client.get_token_by_session(self.session_id, alias)
            return {"Authorization": f"Bearer {jwt}"}, {"polarisUserToken": self.session_id}
        return self.auth_client.build_request_auth(alias)
```

---

## 5. Client / Manager 分层与构造规范

1. **分层职责**：`transport/`（或 `api/`）放 HTTP Client，`services/` 放业务 Manager，`domain/` 放模型与异常，`commands/`（或 `cli.py`）放 Typer 命令。业务调用方应优先使用 **Manager**（含编排），仅在做薄封装时使用 Client。
2. **依赖注入优先**：能传 `auth_client` 就不要让它隐式创建；测试中必须注入 mock 或 `AuthClient(base_dir=tmp_path)`。
3. **不共享有状态实例**：Client 不是线程安全的单例候选，多线程环境按需创建或自行加锁。
4. **timeout 显式化**：支持 `timeout` 参数的 Client（如 `QueryClient`，默认 120 秒仅作用于查询执行接口）在长耗时场景应显式传值，不依赖默认值。

---

## 6. 例外与特例

### 6.1 不走 AuthClient 的模块

以下模块的**平台侧**认证与内部授权体系无关，SDK 调用时按其自身凭证机制显式提供，禁止与 `session_id`/JWT 体系混用：

| 模块 | 平台凭证 | 显式提供方式 |
| ---- | -------- | ------------ |
| keepa（API 直连） | Keepa API Key | `KeepaApiClient(api_key=...)` 或 `KeepaApiManager(api_key_provider=...)` |
| seller_sprite | 卖家精灵账号 Cookie | `SellerSpriteApiManager(account_provider=...)`（内部账号仍经 `IntegrationAccountClient` 用 ops 授权拉取） |
| google_trends / scrape_do | SerpApi / ScrapeDo key | 凭据池 `api_credentials`，或显式 `api_key` |
| xiyou / sif | 西柚 / SIF 自有 token | `XiyouCredential` / `OPSCLI_SIF_TOKEN` 环境变量 |
| notify | 企业微信 webhook | `send_wecom_markdown(webhook=..., content=...)` 参数显式传入 |

注意区分：这些模块中"**账号从哪里来**"（多数仍经 `IntegrationAccountClient`，走 ops 授权）与"**平台怎么认证**"（key/cookie）是两回事，后者才是例外。

### 6.2 `app` 模块运行时 SDK

`opscli/app/sdk/ops_client.py` 的 `OpsClient` 面向应用运行时，token 来自请求头 `x-ops-token`，**不走 AuthClient**——这是宿主容器内的受信通道，不得在其他场景复用。

### 6.3 amazon_listing_intelligence

该模块源码经 Cython 编译剥离，当前工作树**不可导入**，禁止在新代码中引用；如需能力请从已发布 wheel 或 git 历史确认。

### 6.4 反馈开放接口豁免

`ops-feedback-query` 是唯一允许直连后端 API 的 Skill，约束见【铁律11】，其他代码不得参照。

---

## 7. 异常处理规范

### 7.1 异常基类

- auth：`opscli.auth.exceptions.AuthError`（子类：`NotAuthenticatedError`、`SessionExpiredError`、`TokenFetchError`、`SystemNotFoundError`、`DeviceFlowError` 及其 `Expired/Denied` 变体）。
- 其他模块：模块前缀基类，如 `opscli.query.domain.exceptions.QueryError`（子类 `InvalidPayloadError`、`DatasetNotFoundError`、`RemoteHttpError`、`RemoteBusinessError` 等）。新增模块按【代码规范】定义 `XxxError` 基类。

### 7.2 捕获规则

1. 按模块基类捕获，**禁止裸 `except Exception` 吞异常**；捕获后必须 log 或向上转译。
2. `NotAuthenticatedError` 的正确响应是**提示用户显式登录**（`opscli auth login`）或显式传入凭证，而不是代码里自动重试登录。
3. `RemoteHttpError` 携带 `status_code`；`RemoteBusinessError` 携带 `business_code`。转译对外错误时保留 code，不得只透出 message。
4. 异常文本与日志中**禁止**包含完整 JWT、session_id、cookie；需要定位时用前 6~8 位摘要。

### 7.3 环境一致性（407 高频错误）

显式传入的 JWT 由其 `iss` 决定属于哪个环境（QA/生产）。调用方必须保证服务地址与签发环境一致：默认 QA，可通过 `~/.config/opscli/config.ini` 的 `ops_system_url` 或环境变量 `OPSCLI_OPS_SYSTEM_URL` 覆盖。**生产 JWT + QA 地址（或反之）会被后端拒绝（HTTP 407）**。SDK 侧不自动纠正，这是显式授权的一部分：用谁的凭证、连哪个环境，由调用方显式决定。

---

## 8. 测试规范

1. 一律传 `base_dir=tmp_path`（或注入 fake `AuthClient`），禁止默认构造 `AuthClient()` / `CredentialStore()` 读写真实 Keychain 与 `~/.config/opscli/`（【铁律8】）。
2. 网络用 `respx` mock，禁止真实 HTTP。
3. 测显式凭证上下文时用 `set_explicit_credentials(...)` 注入、用例结束 `set_explicit_credentials(None)` 清理，避免污染同进程其他用例（`contextvars` 在 pytest 同线程内共享）。
4. 验证【铁律3】：改动 `opscli/__init__.py` 或 `opscli/auth/__init__.py` 后，两种导入路径都必须有断言覆盖。

---

## 9. 合规自查清单

提交涉及 SDK 调用的代码前逐项自查：

- [ ] 授权方式属于 A/B/C 三种之一，且在调用处可见（显式传参或显式检查），无隐式登录路径
- [ ] 所有 `build_request_auth` / `get_token` 调用显式给出系统别名（`"ops"` / `"polaris"`）
- [ ] 未手拼 Authorization 头、未直读凭证存储、未绕过 `AuthClient`
- [ ] 显式凭证没有落盘、没有进日志与异常文本
- [ ] 捕获的是模块异常基类，`NotAuthenticatedError` 会引导用户显式登录
- [ ] 测试使用 `tmp_path` + mock，无真实网络/Keychain 依赖
- [ ] 两种顶层导入方式仍可用（若改动了 `__init__.py`）

---

## 附：各模块鉴权方式速查

| 模块 | SDK 入口（包根可导） | 系统别名 | 无状态模式 | 备注 |
| ---- | -------------------- | -------- | ---------- | ---- |
| auth | `AuthClient` | ops/polaris | `get_token_by_session` | 唯一凭证源 |
| query | `QueryClient` / `QueryManager` | ops | 构造参数 `jwt`/`session_id` | 查询超时默认 120s |
| shopify | `ShopifyClient` / `ShopifyManager` | polaris | 同上 | CLI 未在顶层注册 |
| feedtask | `FeedTaskClient` / `FeedTaskManager` | polaris | 同上 | 工单底座，被 shopify 复用 |
| feedback | `FeedbackClient` / `FeedbackManager` | ops | 同上 | |
| calculator | `CalculatorClient` | polaris | 同上 | |
| baiyi | `BaiyiProductInfoManager` | ops | 同上 | |
| amazon | `AmazonOpsClient` / `AmazonManager` | ops | 仅 `auth_client` 注入 | |
| amazon_rufus | `RufusManager`（完整路径） | ops | 同上 | 平台侧走浏览器 state |
| app | `AppHubClient` / `PublishManager`（完整路径） | session headers | 同上 | 运行时 `OpsClient` 走 `x-ops-token` |
| keepa / seller_sprite / google_trends / xiyou / sif / scrape_do | 见 §6.1 | 间接 ops | 账号拉取走 ops | 平台凭证独立 |
| notify | `send_wecom_markdown` | 无 | — | webhook 显式传参 |
