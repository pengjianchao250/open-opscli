# Rufus Skill MCP 全链路改造 PRD

日期：2026-06-09

## 目标

将 `ops-amazon-rufus` Skill 的运行期流程改造成 MCP-only：

1. Skill 开始后只调用 MCP Tool，不再执行 `opscli amazon-rufus *` 或 `opscli auth *`。
2. Rufus 前置检查、远程授权偏好、Amazon 登录采集、登录态恢复和 Rufus 获取全部由 MCP Tool 提供。
3. MCP 鉴权失败时通过 MCP auth 工具处理，不再要求用户切换到 opscli CLI。
4. 用户拒绝远程授权时停止流程，不再 fallback 到 CLI `get-backend`。
5. 保持敏感数据不进入 MCP 参数、MCP 响应、报告、日志或 feedback。

## 非目标

1. 不删除已有 `opscli amazon-rufus` CLI 命令。
2. 不把 cookie、headers、payload、`storage_state`、`curl_data`、seed request 或平台 Cookie `content` 作为 MCP 入参。
3. 不新增让 Agent 直接读取完整平台 Cookie content 的 MCP 工具。
4. 不实现远端账号池、共享账号、批量任务队列或异步 job/polling。
5. 不把用户拒绝远程授权的场景改造成无授权绕过。

## 用户故事

### US-1：Skill 起始使用 MCP 鉴权

作为 Agent，我希望进入 Rufus Skill 后先通过 MCP 工具确认当前会话是否已登录 OPS，而不是要求用户执行 CLI。

验收标准：

- Skill 文档第一步要求调用 `auth_is_authenticated()`。
- 未登录时调用 `auth_mcp_login()`。
- Token 失效时调用 `auth_token_refresh(system="ops")`。
- Skill 文档不再出现 `opscli auth login` 或 `opscli auth token refresh -s ops` 作为运行期步骤。

### US-2：授权偏好通过 MCP 保存

作为用户，我希望“是否允许 MCP/headless 复用 Amazon 登录态”的偏好能通过 MCP 保存，并与当前 MCP 用户隔离。

验收标准：

- 新增 `amazon_rufus_remote_consent_status(country)`。
- 新增 `amazon_rufus_remote_consent_set(country, allowed)`。
- `allowed=true` 继续 MCP Rufus 获取。
- `allowed=false` 停止本次获取，不 fallback CLI。
- HTTP/SSE MCP 模式下授权偏好按当前 API Key + Agent 名称隔离存储。

### US-3：登录态检查通过 MCP 执行

作为 Agent，我希望通过 MCP 获取脱敏登录态摘要，判断是否需要采集 Amazon 登录态。

验收标准：

- 新增 `amazon_rufus_login_status(country)`。
- 成功时只返回 `country`、`status`、`has_login_state`、`can_get_backend`、`session_cookie_count`、`has_streaming_request`。
- 不返回平台 Cookie content、cookie、localStorage、headers、payload 或 seed request。
- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 不触发 Amazon 登录采集。

### US-4：Amazon 登录采集通过 MCP 执行

作为用户，我希望缺少 Amazon 登录态时由 MCP 工具打开本机 Chrome，等待我登录并自动保存 Rufus 请求种子。

验收标准：

- 新增 `amazon_rufus_watch_login(asin, country, timeout_seconds, chrome_path, close_browser)`。
- 工具复用 `RufusManager.watch_login()`。
- 默认采集完成后关闭本次由工具启动的调试浏览器。
- 返回脱敏摘要，不返回任何敏感登录态材料。
- Chrome 自动发现失败时，Skill 询问用户 Chrome 可执行文件路径，再把路径传给 `chrome_path`。

### US-5：恢复流程通过 MCP 闭环

作为 Agent，我希望 Rufus 获取失败后的恢复也完全通过 MCP 完成，并且最多恢复一次。

验收标准：

- 仅以下错误进入一次登录态恢复：
  - `RUFUS_SECRET_NOT_READY`
  - `RUFUS_HEADLESS_CAPTURE_ERROR`
  - `RUFUS_HEADLESS_REQUEST_ERROR`
- 恢复步骤为 `amazon_rufus_logout -> amazon_rufus_watch_login -> amazon_rufus_get`。
- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 `RUFUS_REMOTE_HTTP_ERROR status_code=401` 只进入 MCP auth 修复，不进入 `watch_login`。
- 本次 Skill 调用内已有 `login_recovery_attempted=true` 时，不再打开第二次登录窗口。

### US-6：MCP 工具缺失时停止

作为维护者，我希望 MCP-only 方案在工具不可见时直接提示启用或升级 MCP，而不是偷偷调用 CLI 兼容入口。

验收标准：

- Skill 文档明确：当前宿主未暴露必需 MCP Tool 时停止。
- 文档不再建议 `opscli amazon-rufus get-backend` 作为 fallback。
- 安装后引导只列 MCP 工具链。

## 成功指标

1. Skill 模板和 `.agents` 副本不再包含运行期 `opscli amazon-rufus` fallback。
2. MCP `list_tools` 能看到 Rufus 所需工具集合。
3. `amazon_rufus_get` 仍保持敏感字段过滤和报告路径新鲜度约束。
4. `remote-consent`、`login-status`、`watch-login`、`logout` 都有 MCP 单测覆盖。
5. 安装 `ops-amazon-rufus` 的 CLI 输出不再指导用户执行 Rufus CLI 命令。

## 安全边界

禁止出现在 MCP 入参、响应、报告和最终回复中的字段：

- OPS JWT
- session ID
- Amazon Cookie header
- 平台 Cookie `content`
- `cookie_content`
- headers
- payload
- `storage_state`
- `curl_data`
- seed request
- upload payload

允许返回的脱敏字段：

- `country`
- `asin`
- `status`
- `allowed`
- `has_login_state`
- `can_get_backend`
- `session_cookie_count`
- `has_streaming_request`
- `login_detected`
- `streaming_request_saved`
- `report_path`
- 错误码和脱敏 message
