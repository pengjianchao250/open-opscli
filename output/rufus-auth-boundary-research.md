# Rufus 认证边界修复调研

日期：2026-06-09

## 问题摘要

本次用户反馈包含两类故障：

1. `.venv` 内 `opscli auth token status` 显示 OPS 登录和 Token 有效，但 `opscli amazon-rufus login-status US --pretty` 与 `opscli amazon-rufus logout US --pretty` 返回 `RUFUS_REMOTE_HTTP_ERROR` 401。
2. `amazon_rufus_get` MCP 返回 `RUFUS_SECRET_NOT_READY: 未找到可用 Rufus 后端凭证`，但预期应通过平台 Cookie 接口读取已保存的 Amazon 登录态。

核心边界：OPS 认证用于访问 OPS 平台接口；Rufus/Amazon 认证是保存在平台 Cookie content 中的 Amazon 登录态和 Rufus streaming seed。两者不能互相替代，也不能把 OPS 接口 401 当成 Amazon 未登录。

## 本地代码观察

### 远端接口调用

`opscli/amazon_rufus/transport/client.py` 目前调用 `/v1/platform-cookies`：

- `save_platform_cookie()`：POST，只发送 `platform/country/content`。
- `get_platform_cookie()`：GET，只发送 `platform` query。
- 两者都通过 `AuthClient().build_request_auth("ops")` 构造 `Authorization: Bearer <JWT>` 和 `polarisUserToken` cookie。
- MCP 模式仅额外通过 `get_mcp_request_headers()` 透传 `X-MCP-API-Key`，但 `AuthClient()` 默认仍读取默认 CredentialStore。

### 状态存储

`RufusBrowserStateStore` 默认可通过注入 `platform_cookie_client` 读写远端 content：

- `save()` 将完整 Rufus record 序列化为 `content`。
- `load()` 从远端 content 还原 record。
- `delete()` 在远端模式用空 record 覆盖 content。

当前风险：

- `login-status` 通过 `browser_state_store.load()` 读取远端 content。若平台 Cookie API 返回 HTTP 401，命令直接失败为 `RUFUS_REMOTE_HTTP_ERROR`，没有区分 OPS API 鉴权失败和 Amazon 登录态缺失。
- `logout` 通过 `browser_state_store.delete()` 覆盖远端 content。若平台 Cookie API 返回 HTTP 401，命令直接失败为 `RUFUS_REMOTE_HTTP_ERROR`，用户容易误以为 Rufus/Amazon 登录态错误。

### MCP 凭证隔离

现有 MCP auth/query 工具通过 `opscli/mcp/tools/helpers.py` 的 `_get_credential_dir()` 和 `McpCredentialCache` 按 API Key + Agent 名称隔离凭证。

`opscli/mcp/tools/amazon_rufus.py` 当前直接 `RufusManager()`，而 `RufusManager` 默认 `RufusTransportClient()`，最终使用默认 `AuthClient()`。这会带来两个问题：

1. HTTP/SSE 多用户 MCP 模式下没有显式使用当前请求的隔离 CredentialStore。
2. CLI `.venv` 的 OPS 登录状态和 MCP 请求上下文的 OPS 登录状态可能不是同一个凭证域。

因此 MCP Rufus 读取平台 Cookie content 时，必须绑定当前 MCP 请求的 OPS 凭证，而不是隐式读取默认本地凭证。

## OAS 契约核对

通过项目 OAS 读取 `/v1/platform-cookies`，下载时间为 `2026-06-08T09:34:30.657Z`。

结论：

- `POST /v1/platform-cookies`：保存或覆盖当前用户指定平台 Cookie，security 为 `bearerAuth`。
- `GET /v1/platform-cookies?platform=<PLATFORM>`：读取当前用户在指定平台保存的 Cookie，security 为 `bearerAuth`。
- 未命中是业务码 `code=404`，不是 HTTP 401。
- HTTP 401 的语义是 JWT 缺失或失效。
- `PlatformCookieStoreRequest` 中 `platform` 必填，`country` 可选但受 2 位国家代码约束，`content` 为可选 TEXT，最大 65535。

本需求仍坚持 Rufus CLI 只发送 `platform/country/content` 三字段，不把 `cookie_content`、账号、域名、headers、payload 或 seed request 拆成独立 API 字段。

## 外部参考

- Playwright 官方认证文档说明 `storage_state` 可承载 cookies 与 localStorage，适合作为登录态快照的技术载体：<https://playwright.dev/python/docs/auth>
- RFC 6750 定义 Bearer Token 通过 HTTP Authorization header 使用，平台 Cookie API 的 bearerAuth 与 Amazon 登录 cookie 是两层不同凭据：<https://www.rfc-editor.org/rfc/rfc6750>
- Amazon Rufus 是 Amazon 面向购物场景的生成式 AI 助手，本模块的 Rufus 获取依赖用户 Amazon 会话上下文：<https://www.aboutamazon.com/news/retail/amazon-rufus>

## 根因假设

### 假设 1：OPS 平台 Cookie API 鉴权失败被误报为 Rufus 登录态失败

现象：`login-status/logout` 返回 `RUFUS_REMOTE_HTTP_ERROR` 401。

判断：HTTP 401 来自平台 Cookie API，表示 OPS JWT/session 对该接口不可用。它不是 Amazon 登录态缺失，也不是 Rufus secret 缺失。Skill 不应在该错误后执行 `logout -> watch-login` 恢复，否则会让用户重复登录 Amazon 但无法解决 OPS API 401。

结论：需要独立错误码 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。泛化的 `RUFUS_REMOTE_HTTP_ERROR` 只携带 HTTP 失败事实，不携带“失败发生在平台 Cookie API 鉴权边界”这个业务上下文，无法稳定驱动 Skill 的恢复分支。

### 假设 2：MCP Rufus 没有使用当前 MCP 用户的 OPS 凭证读取平台 Cookie content

现象：`amazon_rufus_get` 返回 `RUFUS_SECRET_NOT_READY`。

判断：MCP 侧 `RufusManager()` 没有显式绑定 `_get_credential_dir()`。在 HTTP/SSE 模式下，可能读取默认本地凭证或无凭证，从而没有拿到当前 MCP 用户保存的 `platform=amazon` content。应在 MCP 工具层创建绑定当前请求凭证目录的 Rufus transport/manager。

### 假设 3：平台 content 缺失或国家不匹配应保持 `RUFUS_SECRET_NOT_READY`

如果平台 Cookie API 鉴权成功，但 `content` 为空、不是 JSON、国家不匹配，或 JSON 内没有可用 `storage_state/curl_data`，这才属于 Rufus 后端凭证未准备好。此时可以进入一次 Amazon 登录态采集恢复。

## 修复方向

1. 为平台 Cookie API 401 增加独立错误语义，避免继续暴露泛化的 `RUFUS_REMOTE_HTTP_ERROR`。
2. `login-status` 与 `logout` 遇到平台 API 401 时，明确返回 OPS 平台 Cookie API 鉴权失败，不触发 Amazon 登录恢复。
3. MCP `amazon_rufus_get` 创建 RufusManager 时，显式绑定当前 MCP 请求的隔离 CredentialStore 或 session/JWT。
4. Skill 文档增加限制：`login-status/logout/amazon_rufus_get` 返回 OPS 平台 Cookie API 鉴权失败时，先处理 OPS/MCP 登录，不执行 `watch-login`。
5. 平台 Cookie API 成功但 content 缺失时，才走 `watch-login -> amazon_rufus_get` 的一次恢复。

## 待验证问题

1. 当前用户触发 401 的 OPS base URL 是否与 `auth token status` 检查使用的系统一致。
2. MCP `auth_mcp_login` 后，Rufus MCP 是否能读取同一用户的 platform cookie content。
3. 平台 Cookie 后端是否只按 user + platform 保存一条记录。如果是，多国家站点需要继续依赖 content 内 `country` 做匹配，避免跨国家误用。
