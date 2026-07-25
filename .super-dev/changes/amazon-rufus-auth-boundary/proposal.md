# amazon-rufus-auth-boundary Proposal

## 背景

Rufus 默认状态读写已经收敛到 OPS 平台 Cookie API：`/v1/platform-cookies` 保存和读取 `platform=amazon` 的 Rufus/Amazon 登录态 content。

当前故障暴露了两层认证边界混淆：

1. `opscli amazon-rufus login-status US --pretty` 和 `logout US --pretty` 遇到平台 Cookie API HTTP 401 时，只返回泛化 `RUFUS_REMOTE_HTTP_ERROR`。
2. `amazon_rufus_get` MCP 默认创建 `RufusManager()`，可能读取 CLI 默认凭证域，而不是当前 MCP 请求隔离凭证域，导致误报 `RUFUS_SECRET_NOT_READY`。

OPS 认证只用于访问 OPS 平台接口；Amazon/Rufus 登录态只来自平台 Cookie content。平台 Cookie API 401 必须先修复 OPS/MCP 认证，不能触发 Amazon `watch-login`。

## 目标

1. 为平台 Cookie API HTTP 401 增加稳定错误码 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
2. 仅在平台 Cookie GET/POST 的 401 上映射该错误；`/v1/rufus/upload` 和其它 HTTP 错误保持原有语义。
3. `login-status` 遇到平台 API 401 时失败退出并返回可区分错误码，不伪装成 Rufus 登录态缺失。
4. `logout` 远端清理遇到平台 API 401 时不继续清理本机 opscli-owned Chrome profile。
5. MCP `amazon_rufus_get` 使用当前请求上下文的隔离 CredentialStore，避免隐式复用默认 CLI 凭证。
6. Skill 模板与 `.agents` 副本同步错误分支限制，遇到 OPS/MCP 鉴权错误不得进入 Amazon 登录恢复。

## 非目标

1. 不新增 MCP cookie 管理工具或 MCP 参数。
2. 不新增 `cookie_content`、账号、域名、headers、payload、seed request 等 CLI/API 字段。
3. 不实现后端删除接口；`logout` 继续使用空 content 覆盖策略。
4. 不改平台 Cookie API path、请求字段和三字段保存契约。
5. 不把平台 API 404 或 content 缺失归类为 OPS 鉴权失败。
6. 不依赖真实生产接口做单元测试。

## 方案

新增 Rufus 业务异常：

```text
RufusPlatformCookieAuthError
  code = RUFUS_PLATFORM_COOKIE_AUTH_ERROR
  status_code = 401
```

Transport 映射边界：

```text
RufusTransportClient.save_platform_cookie()
RufusTransportClient.get_platform_cookie()
  -> parse_remote_response()
  -> RufusRemoteHttpError(status_code=401)
  -> RufusPlatformCookieAuthError
```

Manager 分支：

```text
login_status()
  platform API 401 -> RUFUS_PLATFORM_COOKIE_AUTH_ERROR
  platform API 404/missing -> status=missing
  content invalid -> status=invalid
  content ready -> status=ready

logout()
  delete remote content first
  remote 401 -> fail and keep local profile
  remote success -> optionally clear local profile
```

MCP 凭证绑定：

```text
amazon_rufus_get
  -> _rufus_manager_for_current_request()
  -> _get_credential_dir()
  -> AuthClient(base_dir=cred_dir) when HTTP/SSE mode
  -> RufusTransportClient(auth_client=auth_client)
  -> RufusManager(transport_client=transport)
```

Skill 恢复限制：

```text
RUFUS_PLATFORM_COOKIE_AUTH_ERROR
  -> CLI: refresh/login ops auth
  -> MCP: auth_mcp_login
  -> no watch-login

RUFUS_SECRET_NOT_READY
  -> platform API reachable, content unavailable
  -> one watch-login recovery allowed
```

## 验收

1. 平台 Cookie GET/POST HTTP 401 固定返回 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`，并保留 `status_code=401`。
2. `/v1/rufus/upload` HTTP 401 不复用 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
3. `login_status()` 遇到平台 API 401 抛出新错误；平台 API 404 仍返回 missing。
4. `logout()` 遇到平台 API 401 不调用 `clear_owned_profile()`。
5. MCP `amazon_rufus_get` 使用 `_get_credential_dir()` 对应的 `AuthClient(base_dir=...)`。
6. MCP 隔离凭证缺失时不误报 `RUFUS_SECRET_NOT_READY`。
7. Skill 模板、README、reference 与 `.agents` 副本都包含 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 禁止恢复规则。
8. 输出和反馈不包含 JWT、session、Cookie、headers、payload、`storage_state`、`curl_data` 或平台 Cookie content 原文。
