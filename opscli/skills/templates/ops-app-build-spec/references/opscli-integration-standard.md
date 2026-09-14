# 后端调用 opscli 规范

本文规定 AppHub 模板项目在进程内调用 `opscli` SDK 或通过正式 HTTP API 取数时必须遵守的规则。项目中的 `backend/core/auth.py`、`backend/clients/ops_query_client.py`、`docs/apphub-contract.md`、实际路由和生成的 OpenAPI 是运行时事实源；完整方法签名与端点参考 `docs/开发指南/OPSCLI_SDK使用文档.md`、`OPSCLI_API使用文档.md` 及其调用规范。

## 依赖与导入

- 沿用目标项目现有依赖清单，并保持 `aukeys-opscli>=0.0.129` 可导入。
- 只导入包根 `__init__.py` 明确 re-export 的符号，如 `from opscli import AuthClient`、`from opscli.query import QueryManager`。
- 禁止导入 `_` 前缀私有成员、`opscli.*.transport.*` 传输细节或已废弃的 `opscli.mcp.session_store`。
- 禁止直接实例化 `CredentialStore` 或 `TokenManager`，禁止读取 `~/.config/opscli/credentials.bin` 或 Keychain 服务 `opscli-auth`。

## 三模式鉴权

标准模板固定支持 viewer、session、local 三种模式，优先级为 `viewer > session > local > 401`：

| 模式 | 触发条件 | 模板网关 | 运行边界 |
| --- | --- | --- | --- |
| `viewer` | `X-Ops-Token` 和可信 `X-User-Email/Id/Name` | `ViewerQueryGateway` | AppHub 线上正式运行；通过 opscli-mcp REST Query API 发送允许的 viewer Header |
| `session` | `X-Session-Id` 和可选 `Authorization: Bearer <ops-jwt>` | `OpsQueryGateway` | 显式无状态调用；JWT 缺失时由网关按 session 换取 |
| `local` | 无上述 Header 且 `LOCAL_AUTH_FALLBACK_ENABLED=true` | `LocalQueryGateway` | 仅本地开发，使用本机 opscli 登录态 |

- `get_query_credentials()` 只按上述优先级构造请求级 `QueryCredentials`，凭证只存活于当前请求。
- 身份字段缺失或不合法时返回 401，不在三种模式间回退。
- `get_query_gateway()` 每个请求构造独立 Gateway；禁止模块级网关单例、禁止跨请求缓存凭证或 `ExplicitCredentials`。
- `get_current_user()` 通过当前 Gateway 的权威身份来源解析用户；业务代码不得相信请求体中的用户 ID、邮箱或其他自报身份。
- 生产必须关闭 local 回退；测试和本地开发只有显式开启 `LOCAL_AUTH_FALLBACK_ENABLED=true` 时才能使用本机登录态。

## OPS 查询

OPS 业务路由必须通过 FastAPI `Depends(get_query_gateway)` 获取模板 `QueryGateway`，service 通过参数接收 Gateway，并使用 `list_datasets`、`get_dataset_metadata`、`build_simple` 或 `build_simple_and_run`。

- viewer 模式固定读取纯 origin 环境变量 `OPSCLI_MCP_REST_API_BASE_URL`，查询调用 `POST /api/v1/query/simple`，元数据调用 `GET /api/v1/query/metadata`。
- `OPSCLI_MCP_REST_API_BASE_URL` 上的 `/api/v1/*` 是 AppHub REST 合同，不得拼接 `/mcp`、`/sse`，不得使用 MCP API Key。
- viewer 请求只从 `QueryCredentials` 重建 `X-Ops-Token`、`X-User-Email` 和可选 `X-User-Id`、`X-User-Name`，禁止转发 Cookie 或浏览器 Authorization。
- 禁止生成或调用 `/v1/data-metrics/viewer/query-metadata`、`/v1/data-metrics/viewer/cli-query/simple`；原始 OPS `/v1/data-metrics/cli-query/simple` 是 opscli-mcp 内部转发实现，不是站点合同。
- 业务模块不得自行解析 `X-Ops-Token`、`X-Session-Id` 或 Bearer JWT，也不得自行创建第二套 Viewer Client。
- 不生成或引用 `opscli.app.sdk.OpsClient`，不为 OPS 查询创建第二套鉴权适配器。
- 同步 SDK 调用必须通过模板网关的 `asyncio.to_thread` 卸载，禁止阻塞 FastAPI 事件循环。
- 每个正式 OPS 数据集都必须进入 `app.yaml.opscli.datasets` 白名单。
- 查询 payload 由 Gateway/`QueryManager.build_simple()` 构造；禁止手写 `userEmail`、`query.from.table`、`query.from.permission` 或 `query.from.database`。
- 销售额等带币种指标必须把币种作为查询条件传入服务端，禁止先查默认币种再在后端换算。
- 读取结果时检查 `truncated`、`total_count` 与分页合同；需要全量时按确定性顺序翻页，不反复全量拉取后本地过滤。

## 其他 SDK 与第三方调用

- 非 OPS 查询功能确需直接使用 SDK 时，每个请求构造独立 Client/Manager，并显式提供当前请求的 session/JWT；禁止模块级实例和跨请求凭证复用。
- Keepa、SellerSprite 的请求级 `ThirdPartyApiClient` 复用 `QueryCredentials`，并与 OPS viewer 共用 `OPSCLI_MCP_REST_API_BASE_URL`；具体 Header 映射和用户私有存储遵循 `data-access-standard.md`。
- 第三方 local 模式仅允许 Client 通过 `AuthClient.build_session_headers("ops")` 与 `AuthClient.build_request_auth("ops")` 提取标准 Session/JWT Header；禁止发送 Cookie、local 标识或其他本机凭证。
- 通过正式 HTTP API 调用时必须检查 HTTP 状态和响应 `success`，程序只依据状态码与 `error.code` 分支，不解析 message 文本。
- 凭证不得进入 URL、请求体、前端、日志、SQLite、源码或异常文本。

## 异常映射

项目统一异常处理器按模板现有 `AppError` 层映射，不让业务 service 抛 `HTTPException`：

| 上游情况 | 站点处理 |
| --- | --- |
| 认证失效或 HTTP 401 | 返回稳定 401；提示重新登录或刷新页面，禁止自动重试登录 |
| 权限不足或 HTTP 403 | 返回稳定 403；不切换用户或鉴权模式 |
| 数据集不存在 | 返回稳定 404，并保留安全的业务 code |
| 请求合同错误或 HTTP 422 | 返回稳定参数错误，不原样重试 |
| 上游 HTTP 502 | 仅幂等调用允许有限重试 |
| 上游 HTTP 503 | 遵循 `Retry-After` 退避 |
| 超时或网络不可达 | 返回稳定上游不可用错误，保留可观测记录 |

- 禁止裸 `except Exception` 吞掉 opscli 异常；捕获后必须记录安全日志或向上转译。
- 日志不得包含完整 JWT、session_id、Cookie、viewer ticket 或完整 Header；需要定位时只使用不可逆摘要。
- OPS 和第三方服务地址必须与凭证签发环境一致；地址只通过项目 Settings 和部署环境配置，不自动纠正或按鉴权模式推断。

## 测试

- OPS 测试使用 FakeGateway 和 `app.dependency_overrides` 覆盖 `get_query_gateway`、`get_current_user`，不访问真实网络或本机凭证。
- 第三方 Client 测试分别构造 viewer、session、local 和未认证 `QueryCredentials`，断言只发送允许的 Header 且不跨模式回退。
- 网络统一使用 mock transport 或 `respx`；禁止访问真实账号、Keychain、用户数据库或远端服务。
- 测试不得默认构造读取真实本机状态的 `AuthClient()`；local 分支通过 fake factory 验证标准方法调用。
