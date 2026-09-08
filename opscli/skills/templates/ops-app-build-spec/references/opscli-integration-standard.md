# 后端调用 opscli 规范

本文规定 ops-app 后端在进程内导入 `opscli` SDK 或通过 HTTP 调用 opscli 服务端时必须遵守的规则。完整方法签名与端点参考见 `docs/开发指南/OPSCLI_SDK使用文档.md` 与 `OPSCLI_API使用文档.md`；调用约束全文见 `OPSCLI_SDK调用规范.md` 与 `OPSCLI_API调用规范.md`。两者冲突时以全文为准。

## 依赖与导入

- `pyproject.toml` 声明 `aukeys-opscli>=0.0.129`，注释写明用途。
- 只导入包根 `__init__.py` 明确 re-export 的符号，如 `from opscli import AuthClient`、`from opscli.query import QueryManager`。禁止导入 `_` 前缀私有成员、`opscli.*.transport.*` 传输细节以及已废弃的 `opscli.mcp.session_store`。
- 内部类需要完整路径导入时，在调用方注释中注明"内部类，升级可能变动"。
- 禁止直接实例化 `CredentialStore` 或 `TokenManager`，禁止读取 `~/.config/opscli/credentials.bin` 或 Keychain 服务 `opscli-auth`。

## 授权显式调用

后端服务运行在容器中，没有本机登录态，一律使用 SDK 规范的方式 B：由请求解析出当前用户的 `session_id` 与可选 `jwt`，显式传入 Client / Manager 构造函数。

- 每个请求构造独立实例：`QueryManager(session_id=user.session_id, jwt=user.jwt)`。禁止把 Manager 存为模块级单例或应用状态，禁止跨请求复用。
- 禁止使用方式 C 的 `set_explicit_credentials()`：进程级上下文在多用户服务中会串号。
- 禁止缓存 `ExplicitCredentials` 或把它存到模块级变量。
- 传入的 `session_id` 会作为 `polarisUserToken` cookie 随请求发送，session 与 JWT 必须同源同环境。
- 所有取 token 或构造认证头的调用必须显式指定系统别名 `"ops"` 或 `"polaris"`。
- 需要长耗时查询时显式传 `timeout`，不依赖默认值。

## 鉴权依赖约定

`app/core/auth.py` 的 `get_current_user` 是后端唯一的对外鉴权依赖，默认按以下方式解析 opscli 会话：

1. 依次读取 cookie `polarisUserToken` 与请求头 `X-Session-Id`，取到即为 `session_id`；读取 `Authorization: Bearer <jwt>` 作为可选 `jwt`。两者都缺失时抛 401。
2. 调用 `AuthClient().get_me(session_id=session_id, jwt=jwt)` 解析用户信息；`AuthError` 家族一律映射为 401，不区分具体子类，避免泄漏 session 是否有效。
3. 结果按 `sha256(session_id)` 作键做 60 秒内存缓存，缓存值不含 session 或 JWT 原文。
4. 返回 `CurrentUser(email, session_id, jwt)`，供业务层构造 Manager。

通过 AppHub 同域网关访问时浏览器会自动携带 cookie；跨域调用方必须显式传 `X-Session-Id`。`auth_enabled` 开关只允许在 `app_env=local` 时关闭，关闭时返回固定的本地开发用户。内部接口用 `verify_internal` 依赖比对 `X-Internal-Key`，必须 `secrets.compare_digest`。

## 异常映射

在 `main.py` 的统一异常处理器中按模块基类映射：

| 异常 | HTTP 状态 | 处理 |
| --- | --- | --- |
| `opscli.auth.exceptions.NotAuthenticatedError` / `SessionExpiredError` / `TokenFetchError` | 401 | 提示重新登录或传入有效会话；禁止在代码里自动重试登录 |
| `opscli.auth.exceptions.SystemNotFoundError` | 500 | 系统别名配置错误，记录日志并告警 |
| `opscli.query.domain.exceptions.InvalidPayloadError` | 400 | 保留 `exc.code` 与消息 |
| `opscli.query.domain.exceptions.DatasetNotFoundError` | 404 | 保留 `exc.code` |
| `opscli.query.domain.exceptions.QueryMetadataNotReadyError` | 503 | 附 `Retry-After` |
| 其他 `QueryError` | 502 | 保留 `exc.code`，消息只透出业务错误 |
| `RemoteHttpError` | 502 | 保留 `status_code`；`RemoteBusinessError` 保留 `business_code` |

- 禁止裸 `except Exception` 吞掉 opscli 异常；捕获后必须记录日志或向上转译。
- 异常文本与日志禁止包含完整 JWT、session_id、cookie；需要定位时用前 6 位摘要。
- 服务端地址必须与传入 JWT 的签发环境一致，否则后端返回 407。默认 QA 环境，可通过 `~/.config/opscli/config.ini` 的 `ops_system_url` 或环境变量 `OPSCLI_OPS_SYSTEM_URL` 覆盖；该值进入 `Settings` 并三处同步，SDK 不自动纠正。

## 数据查询

- 查询 payload 由 `QueryManager.build_simple()` 或 `opscli query build` 生成；禁止手写 `userEmail`、`query.from.table`、`query.from.permission`、`query.from.database`。
- 销售额等带币种指标必须把币种作为查询条件传入服务端，禁止先查默认币种再在后端换算。
- 读取结果时检查 `truncated` / `total_count`，需要全量时按 `offset` / `limit` 翻页；禁止反复全量拉取后本地过滤。

## 通过 HTTP 调用 opscli 服务端

只在无法进程内导入 SDK 时使用：

- 每个请求携带 `Authorization: Bearer <api_key>`；API Key 只来自 `Settings`，禁止进代码库、前端产物、日志。禁止用 `?api_key=` 传递。
- 必须检查响应信封的 `success` 字段，不得只看 HTTP 状态码。程序分支只依据 `error.code` 与状态码，禁止解析 `message` 文本。
- 重试纪律：401 永不重试；503 按 `Retry-After` 退避；502 可带幂等语义重试；400、404、422 修改请求后才重试。
- 客户端 HTTP 超时设为服务端 `timeout` 上限加余量（服务端上限 300 秒，客户端用 310 秒）。
- 请求体禁止携带 `session_id`、`jwt`、`userEmail` 等身份字段，服务端 `extra="forbid"` 会直接拒绝。

## 测试

- 测试禁止默认构造 `AuthClient()` 读写真实 Keychain 与 `~/.config/opscli/`；必须 `AuthClient(base_dir=tmp_path)` 或用 `app.dependency_overrides` 注入假的 `CurrentUser` 与 Manager。
- 网络用 `respx` mock，禁止真实 HTTP。
