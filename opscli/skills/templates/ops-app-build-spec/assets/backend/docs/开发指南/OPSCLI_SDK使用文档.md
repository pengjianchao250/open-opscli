# opscli SDK 使用文档

> 版本：v1.0（2026-09-01）｜适用包版本：`aukeys-opscli >= 0.0.129`｜Python >= 3.10
> 本文面向**在 Python 代码中直接导入 opscli** 的使用者。CLI 用法见 opscli 仓库 `docs/guide/认证模块使用指南.md`。
> 调用约束（授权、安全、测试）见 [SDK调用规范](OPSCLI_SDK调用规范.md)，本文只讲"怎么用"。

---

## 1. opscli 是什么

`opscli` 是 Aukeys 内部运营工具集，既提供 `opscli` 命令行，也是可导入的 Python SDK：

- **统一授权**：一次登录（或显式传入凭证），访问 ops（运营系统）与 polaris（刊登系统）两个内置系统；
- **统一取数**：`QueryManager` 封装数据集元数据、payload 构造与查询执行；
- **业务 SDK**：Shopify 刊登、工单、反馈、新品计算器、Keepa、卖家精灵、Google Trends 等 20+ 模块。

安装：

```bash
pip install aukeys-opscli
```

---

## 2. 快速开始

```python
import httpx
from opscli import AuthClient

client = AuthClient()

# 1) 显式检查登录态（SDK 不会自动登录）
if not client.is_authenticated():
    raise SystemExit("未登录，请先在终端执行: opscli auth login")

# 2) 显式指定系统别名，取得统一认证参数
headers, cookies = client.build_request_auth("ops")

# 3) 调用业务 API
resp = httpx.get(
    "https://ops.api.qa.aukeyit.com/api/v1/operation-reminder/list",
    headers=headers, cookies=cookies, timeout=10,
)
print(resp.json())
```

首次使用先在终端完成一次登录（OAuth2 Device Flow，会自动打开浏览器）：

```bash
opscli auth login
opscli auth token status   # 确认 ops / polaris 两个系统的 token 状态
```

---

## 3. 授权：三种显式调用方式

**核心原则：SDK 永不隐式登录。** 授权必须显式建立，三选一（可叠加，优先级 C > B > A）：

### 方式 A：本地登录态（推荐本机脚本使用）

一次性 `opscli auth login` 后，SDK 直接读取本机加密凭证（macOS Keychain 优先，否则 AES-256-GCM 文件兜底）：

```python
from opscli.auth import AuthClient

client = AuthClient()
token = client.get_token("ops")     # 自动复用缓存 JWT，临期（<5 分钟）自动刷新
```

### 方式 B：无状态显式凭证（推荐服务端 / 多用户环境使用）

把 `session_id`（必配）与 `jwt`（可选）**显式传入** Client / Manager 构造函数。不传 jwt 时 SDK 用 session_id 向后端实时换取，全程不读写本机凭证：

```python
from opscli.query import QueryManager

qm = QueryManager(session_id="860b0636485b5188a2b9b4ed5210e736", jwt="eyJ...")
result = qm.run_payload(payload)
```

适用于 `QueryManager`、`QueryClient`、`ShopifyManager`、`FeedbackClient`、`CalculatorClient`、`FeedTaskManager` 等标准构造范式 `(auth_client=None, jwt=None, session_id=None)` 的类。

### 方式 C：进程级显式凭证上下文（CLI 中间件 / 整链换身份）

```python
from opscli.auth.context import ExplicitCredentials, set_explicit_credentials

set_explicit_credentials(ExplicitCredentials(
    session_id="abc123",        # 必填
    ops_jwt="eyJ...",           # 可选，缺省时用 session_id 换取
    polaris_jwt="eyJ...",       # 可选
))
# 注入后，当前上下文内所有 AuthClient 调用自动优先使用这组凭证，绝不落盘
set_explicit_credentials(None)  # 用完清除，回退本地登录态
```

CLI 等价形式——任意子命令尾部追加全局参数：

```bash
opscli query simple --table-id 35 --run --session-id=abc123 --ops-jwt-token=eyJ...
```

> ⚠️ **环境一致性**：JWT 由哪个环境签发（`iss`），就必须连哪个环境的服务地址（默认 QA；用 `config.ini` 的 `ops_system_url` 或环境变量 `OPSCLI_OPS_SYSTEM_URL` 覆盖）。生产 JWT 连 QA 地址会被后端拒绝（HTTP 407）。

---

## 4. AuthClient API 参考

导入：`from opscli import AuthClient` 或 `from opscli.auth import AuthClient`（两者等价，必须同时可用）。

### 构造

```python
AuthClient(base_dir: Path | None = None)
```

| 参数 | 说明 |
| ---- | ---- |
| `base_dir` | 凭证目录。**仅测试时传 `tmp_path`**；生产代码使用默认 `~/.config/opscli/` |

### 方法一览

| 方法 | 返回 | 说明 |
| ---- | ---- | ---- |
| `is_authenticated()` | `bool` | 是否已登录（session 存在且未过期；显式凭证上下文有 session_id 即为 True） |
| `get_token(alias)` | `str` | 获取指定系统有效 JWT，临期自动刷新。优先级：显式凭证上下文 > 本地登录态 |
| `get_session(alias=None)` | `str` | 获取当前登录态 session_id（全局登录态，`alias` 仅保持语义一致） |
| `get_device_code()` | `str \| None` | 本机设备码（随请求以 `opscliDeviceCode` cookie 发送） |
| `build_request_auth(alias)` | `(headers, cookies)` | 统一请求认证参数，见下方示例 |
| `build_session_headers(alias=None)` | `dict` | `{"X-Session-Id": ..., "X-Opscli-Version": ...}`，用于只需会话标识的接口 |
| `check_token(alias)` | `dict` | `{"valid": bool, "expires_in": int}`，本地解析 JWT，不发网络 |
| `refresh_token(alias)` | `str` | 强制刷新，返回新 JWT |
| `get_me(session_id=None, jwt=None)` | `dict` | 当前授权用户信息（`GET /api/v1/auth/me`）；传 `session_id` 时为无状态模式 |
| `get_token_by_session(session_id, alias)` | `str` | 用外部 session_id 无状态换取 JWT，不读写本地存储 |
| `build_request_auth_with_session(session_id, jwt=None, alias="ops")` | `(headers, cookies)` | 无状态版 `build_request_auth` |

### `build_request_auth` 返回结构

```python
headers, cookies = client.build_request_auth("ops")
# headers = {"Authorization": "Bearer <jwt>", "X-Opscli-Version": "<版本>"}
# cookies = {"polarisUserToken": "<session_id>", "opscliDeviceCode": "<device_code>"}
```

### 典型用法

```python
# 检查 + 手动刷新（定时任务场景）
status = client.check_token("polaris")
if not status["valid"]:
    client.refresh_token("polaris")

# 只需要会话标识的接口
headers = client.build_session_headers("ops")   # X-Session-Id

# 异常处理
from opscli.auth.exceptions import (
    AuthError, NotAuthenticatedError, SessionExpiredError,
    TokenFetchError, SystemNotFoundError,
)
try:
    token = client.get_token("ops")
except NotAuthenticatedError:
    print("未登录，请先执行: opscli auth login")
except TokenFetchError as e:
    print(f"换取 JWT 失败: {e}")
except SystemNotFoundError:
    print("系统别名不存在，执行 opscli auth system list 查看")
```

---

## 5. 显式凭证上下文 API

模块：`opscli.auth.context`

| 符号 | 签名 | 说明 |
| ---- | ---- | ---- |
| `ExplicitCredentials` | `ExplicitCredentials(session_id: str, ops_jwt: str \| None = None, polaris_jwt: str \| None = None)` | 不可变 dataclass；`jwt_for(alias)` 按别名取对应 JWT |
| `set_explicit_credentials(creds)` | `creds: ExplicitCredentials \| None` | 注入 / 清除（传 None 清除）当前上下文凭证 |
| `get_explicit_credentials()` | `ExplicitCredentials \| None` | 读取；业务代码一般不需要调用（单点注入设计） |

机制说明：底层是 `contextvars.ContextVar`，请求级、进程内、协程安全，**绝不落盘**。注入后 `AuthClient.get_token / get_session / is_authenticated` 自动优先消费，业务模块无需改动。

---

## 6. 业务模块 SDK 总览

> "包根可导"= `from opscli.<模块> import X`；未标注的需写完整路径（内部类，升级可能变动）。

### 6.1 走 AuthClient 的模块（支持 session_id/jwt 显式传参）

| 模块 | SDK 类 | 系统 | 说明 |
| ---- | ------ | ---- | ---- |
| query | `QueryClient`、`QueryManager`（包根可导） | ops | 数据集查询（见 §7） |
| shopify | `ShopifyClient`、`ShopifyManager`、`Shop`、`ShopifyProduct`、`ShopifyVariant`（包根可导） | polaris | 店铺/商品查询、价格/库存/上下架工单 |
| feedtask | `FeedTaskClient`、`FeedTaskManager`、`TaskResult`、`TaskStatus`（包根可导） | polaris | 通用工单底座 |
| feedback | `FeedbackClient`、`FeedbackManager`（包根可导） | ops | 执行反馈提交/查询/AI 洞察 |
| calculator | `CalculatorClient`（包根可导） | polaris | 新品计算器（试算草稿/提交） |
| baiyi | `BaiyiProductInfoManager`（包根可导） | ops | 百衣商品信息 |
| amazon | `AmazonManager`、`AmazonOpsClient`（包根可导） | ops | Amazon 页面抓取与提交 |
| amazon_rufus | `RufusManager`（`opscli.amazon_rufus.services.manager`） | ops | Rufus 问答/Listing 诊断 |
| app | `AppManager`（包根可导）、`AppHubClient`（`opscli.app.transport.client`） | session | 应用创建、Git 初始化与源码推送；运行时另有 `OpsClient`（走 `x-ops-token`，勿混用） |

### 6.2 平台自有凭证的模块（不走 AuthClient）

| 模块 | SDK 类 | 平台凭证 |
| ---- | ------ | -------- |
| keepa | `KeepaApiManager`（包根可导）、`KeepaApiClient`（`opscli.keepa.api.client`，需 `api_key`） | Keepa API Key |
| seller_sprite | `SellerSpriteApiManager`（`opscli.seller_sprite.services.api_manager`） | 卖家精灵账号 Cookie（账号经 ops 授权拉取） |
| google_trends | `GoogleTrendsApiManager`（包根可导） | SerpApi key 池 |
| xiyou | `XiyouApiManager`（`opscli.xiyou.services.api_manager`） | 西柚 authorization JWT |
| sif | `SifServiceManager`（`opscli.sif.services.manager`） | `OPSCLI_SIF_TOKEN` 等环境变量 |
| scrape_do | `ScrapeDoApiManager`（`opscli.scrape_do.services.api_manager`） | ScrapeDo key（凭据池） |
| notify | `send_wecom_markdown(webhook, content)`（包根可导） | 企业微信 webhook 显式传参 |
| api_credentials | `ApiCredentialPool`（包根可导） | MySQL 凭据池底座 |

### 6.3 异步示例（seller_sprite）

```python
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.seller_sprite.services import SellerSpriteApiManager

request = SellerSpriteScenarioRequest(
    scenario="keyword-reverse", site="US", period="30d",
    params={"asin": "B0XXXXXXX", "includeHighFrequency": True},
)
result = await SellerSpriteApiManager(jwt=jwt, session_id=session_id).run(request)
```

> 注意：`shopify` 的 CLI 未在顶层注册，但 SDK 完全可用；`amazon_listing_intelligence` 当前不可导入（Cython 源码保护）；`canopy` 仅有远端 MCP 适配器 `CanopyRemoteAdapter`，无本地 SDK。

---

## 7. 数据查询 SDK（QueryManager）

```python
from opscli.query import QueryManager, QueryClient

qm = QueryManager()                      # 或 QueryManager(session_id=..., jwt=..., timeout=180)

qm.list_datasets()                       # 列出可用数据集
qm.list_fields(dataset_alias="ds_xxx")   # 列出字段
payload = qm.build_simple(               # 构造简单查询 payload
    dataset="ds_xxx",
    dimensions=["site_name"],
    metrics=[{"field": "sales", "aggregation": "sum"}],
    where=[...], limit=100,
)
result = qm.run_payload(payload)         # 执行查询（默认超时 120 秒）
result = qm.build_simple_and_run(...)    # 构造 + 执行一步到位
```

要点：

- `userEmail`、`query.from.table/permission/database` 等敏感/复杂字段由 SDK 自动填充，**不要**手写（【铁律12】）。
- 异常基类 `opscli.query.domain.exceptions.QueryError`；`RemoteHttpError` 带 `status_code`，`RemoteBusinessError` 带 `business_code`。
- REST API 形态：自 0.0.129 起 query 全量指令也可经 `opscli-mcp` 的 HTTP 面调用（FastAPI 规范结构，见 `opscli/api/`）。

---

## 8. 典型场景

### 8.1 Shell 脚本取 token

```bash
TOKEN=$(opscli auth token get -s ops)
curl -H "Authorization: Bearer $TOKEN" https://ops.api.qa.aukeyit.com/api/xxx
```

### 8.2 定时任务（cron / APScheduler）

```python
from opscli.auth import AuthClient
from opscli.auth.exceptions import AuthError

def fetch_with_retry(alias: str = "ops", retries: int = 2):
    client = AuthClient()
    for _ in range(retries + 1):
        try:
            headers, cookies = client.build_request_auth(alias)
            return do_request(headers, cookies)     # 你的业务请求
        except AuthError:
            client.refresh_token(alias)             # 失效则显式刷新后重试
    raise RuntimeError(f"获取 {alias} 凭证失败，请检查 opscli auth token status")
```

### 8.3 Web 服务多租户隔离

每个请求用调用方传入的 session_id 构造独立 Manager，禁止共享实例、禁止落盘：

```python
def handle_request(session_id: str, jwt: str | None):
    manager = ShopifyManager(session_id=session_id, jwt=jwt)
    return manager.list_shops()
```

---

## 9. 异常参考

### auth 模块（基类 `AuthError`）

| 异常 | 触发场景 | 处理建议 |
| ---- | -------- | -------- |
| `NotAuthenticatedError` | 未登录 | 提示用户 `opscli auth login`，或改用显式凭证传参 |
| `SessionExpiredError` | session 过期（30 天） | 重新登录 |
| `TokenFetchError` | session 换 JWT 失败 | 检查 session 有效性、环境一致性 |
| `SystemNotFoundError` | 系统别名不存在 | `opscli auth system list` 查看；只支持 ops/polaris |
| `DeviceFlowError` / `DeviceFlowExpiredError` / `DeviceFlowDeniedError` | 登录流程失败/超时/被拒 | 仅 CLI 登录时出现，重新 `opscli auth login` |

### 业务模块

各模块有独立异常基类（如 `QueryError`、`NotifyError`），统一风格：携带 `code` 属性，HTTP/业务错误分别有 `status_code` / `business_code`。按模块基类捕获，不要裸捕 `Exception`。

---

## 10. Token 生命周期与凭证存储

| 项目 | 值 | 说明 |
| ---- | -- | ---- |
| session 有效期 | 30 天 | 自动续期；过期需重新登录 |
| JWT 默认有效期 | 7200 秒（2 小时） | 后端 `expires_in` 决定 |
| JWT 有效期上限 | 86400 秒（24 小时） | `MAX_JWT_TTL`，防后端异常超长值 |
| 自动刷新阈值 | 300 秒（5 分钟） | `REFRESH_THRESHOLD`，`get_token` 时距过期不足则自动刷新 |
| 环境变量覆盖 | `OPSCLI_REFRESH_THRESHOLD` / `OPSCLI_MAX_JWT_TTL` | 运维调优用 |

存储位置 `~/.config/opscli/`：`credentials.bin`（AES-256-GCM 加密凭证；macOS Keychain 可用时优先存 Keychain，服务名 `opscli-auth`）、`.key`（加密密钥，权限 600）、`systems.json`（系统列表）、`config.ini`（可选服务地址覆盖）。MCP 模式按 API Key 哈希隔离到 `credentials_by_key/<hash>/`。

并发安全：Token 刷新采用线程锁 + 跨进程文件锁双层设计，多进程同时 `get_token` 不会重复刷新，SDK 调用方无需自行加锁。

---

## 11. 常见问题

**Q：SDK 会自动弹登录吗？**
不会。授权只能显式发起：CLI `opscli auth login` 或 MCP `auth_login_start/poll`。SDK 拿不到凭证时抛 `NotAuthenticatedError`。

**Q：报 HTTP 407？**
凭证与环境的 `iss` 不一致。显式传入的 JWT 必须配合对应环境的服务地址（`config.ini` 或 `OPSCLI_OPS_SYSTEM_URL`）。

**Q：`get_token` 和 `refresh_token` 的区别？**
`get_token` 返回有效 token（缓存命中直接返回，临期自动刷新）；`refresh_token` 无条件向后端换取新 token。

**Q：服务端部署没有 Keychain / 交互终端怎么办？**
不依赖本机登录态：每个请求显式传 `session_id`（+`jwt`）构造 Client（方式 B），凭证由你的服务统一保管。

**Q：能直接 `from opscli.auth.storage.credential_store import CredentialStore` 读凭证吗？**
禁止。统一经 `AuthClient`；底层直调属于规范违规，见《SDK调用规范》§4.2。

**Q：Windows 下注意事项？**
终端输出已做 GBK 兼容兜底；文件锁在 Windows 自动跳过；凭证存储仅 AES-256-GCM 文件模式（无 Keychain）。
