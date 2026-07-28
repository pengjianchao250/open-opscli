# Rufus 认证边界修复 PRD

日期：2026-06-09

## 目标

修复 Rufus CLI 与 MCP 在 OPS 认证、平台 Cookie API 和 Amazon 登录态之间的边界混淆：

1. `login-status` 和 `logout` 不再把平台 Cookie API 401 伪装成 Rufus/Amazon 登录态缺失。
2. `amazon_rufus_get` MCP 后端必须通过平台 Cookie API 获取当前 MCP 用户保存的 Amazon 登录态 content。
3. Skill 流程遇到 OPS/MCP 鉴权问题时停止 Amazon 登录恢复，避免无效循环。
4. 保持 MCP 参数面不暴露 cookie、headers、`storage_state`、payload 或 cURL。

## 非目标

1. 不新增 MCP cookie 管理工具。
2. 不新增 `cookie_content`、账号、域名、headers、payload、seed request 等 CLI/API 字段。
3. 不删除现有 `watch-login`、`platform-cookie save/get`、`get-backend` 等入口。
4. 不实现后端删除接口；`logout` 仍按现有空 content 覆盖策略清理远端状态。
5. 不运行真实生产接口作为单元测试依赖。

## 用户故事

### US-1：状态检查区分 OPS API 401 与 Amazon 未登录

作为 Rufus Skill 调用者，我希望 `login-status` 在平台 Cookie API 401 时给出明确错误，而不是让我去重新登录 Amazon。

验收标准：

- 平台 Cookie API HTTP 401 固定映射为 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
- 错误 message 明确说明这是 OPS 平台 Cookie API 未授权，不是 Amazon 登录态缺失。
- CLI 输出不包含 JWT、session、cookie、headers 或 content。
- Skill 遇到该错误时停止，不执行 `logout`、`watch-login` 或 `amazon_rufus_get` 重试。
- `/v1/rufus/upload` 和非 401 的远端 HTTP 错误不复用该错误码。

### US-2：登出失败不误删本机 profile

作为 Rufus CLI 用户，我希望 `logout` 在远端平台 Cookie API 未授权时不要继续清理本机浏览器 profile，避免远端旧状态仍在但本机状态被清理。

验收标准：

- `RufusManager.logout()` 先清理远端 Rufus 状态。
- 如果远端清理因 401 失败，命令返回独立错误，且不调用 `BrowserAttachService.clear_owned_profile()`。
- 如果远端清理成功，再按参数决定是否清理 opscli-owned Chrome profile。

### US-3：MCP 使用当前请求用户的 OPS 凭证

作为 MCP 用户，我希望 `amazon_rufus_get` 读取的是当前 MCP 会话用户保存的 Amazon 登录态，而不是 CLI 默认用户或 MCP Server 进程用户。

验收标准：

- MCP `amazon_rufus_get` 创建 RufusManager 时绑定当前请求的隔离 CredentialStore。
- HTTP/SSE 模式下通过 API Key + clientInfo.name 隔离凭证目录。
- stdio 模式保持与 CLI 共用默认凭证目录。
- 平台 Cookie API 请求仍带 `Authorization: Bearer <ops JWT>`、`polarisUserToken` cookie、`X-MCP-API-Key` 和 `X-Opscli-Version`。
- 单测验证 MCP 工具调用时 Rufus transport 使用隔离凭证目录。

### US-4：MCP secret 缺失时从平台 content 判断

作为 Agent，我希望 `RUFUS_SECRET_NOT_READY` 只表示平台 content 不存在或不可用，而不是 OPS/MCP 鉴权失败。

验收标准：

- 平台 Cookie API 鉴权成功但未命中业务码 404 时，`RufusBackendSecretProvider.load()` 仍返回 `RUFUS_SECRET_NOT_READY`。
- 平台 content 为空、国家不匹配或 JSON 无效时，仍返回可恢复的 Rufus 状态错误。
- 平台 Cookie API HTTP 401 不返回 `RUFUS_SECRET_NOT_READY`，而是返回 OPS 平台 Cookie API 鉴权错误。

### US-4 补充：错误码驱动恢复路径

作为 Skill 维护者，我希望错误码能直接驱动分支，不需要解析自然语言 message。

验收标准：

- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 只驱动 OPS/MCP 登录修复。
- `RUFUS_SECRET_NOT_READY` 只驱动 Amazon/Rufus 登录态恢复。
- `RUFUS_REMOTE_HTTP_ERROR` 保留为非平台 Cookie 401 或其它远端 HTTP 问题，Skill 不把它默认视为 Amazon 未登录。

### US-5：Skill 增加恢复限制

作为用户，我希望 Rufus Skill 不因为错误分类不清而反复打开 Amazon 登录窗口。

验收标准：

- 仅以下错误进入一次 `watch-login` 恢复：`RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`RUFUS_HEADLESS_REQUEST_ERROR`。
- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`、`RUFUS_REMOTE_HTTP_ERROR` 401、MCP OPS 未登录等错误不进入 Amazon 登录恢复。
- 若 MCP 未登录，先调用或提示 `auth_mcp_login`。
- 若 CLI OPS 登录失效，提示执行 `opscli auth login` 或 `opscli auth token refresh -s ops`。

## 成功指标

1. `login-status` 的 401 不再输出泛化 `RUFUS_REMOTE_HTTP_ERROR`。
2. `logout` 的 401 不清理 browser profile。
3. MCP Rufus transport 使用 MCP 隔离凭证目录。
4. `amazon_rufus_get` 能从平台 Cookie content 读取已保存的 Amazon 登录态。
5. Skill 模板与 `.agents` 副本同步新增限制。
6. 定向测试覆盖 transport、manager、CLI、MCP 工具和 Skill 文档。

## 安全边界

任何路径不得输出：

- OPS JWT
- session cookie
- Amazon Cookie header
- headers
- payload
- `storage_state`
- `curl_data`
- seed request
- 平台 Cookie `content` 原文，除显式 `platform-cookie get` CLI 内部消费场景外
