# Rufus Skill MCP 全链路改造调研

日期：2026-06-09

## 需求变更

用户明确取消上一版“Skill 使用 MCP 获取，但恢复和 Amazon 登录态采集仍走 opscli CLI”的方案。新的目标是：

1. Agent 使用 `ops-amazon-rufus` Skill 后，运行期不再调用 `opscli amazon-rufus *`。
2. OPS/MCP 鉴权、远程授权偏好、登录态检查、Amazon 登录采集、登出恢复和 Rufus 获取全部通过 MCP Tool 编排。
3. CLI 命令可以继续保留给直接 CLI 用户和兼容场景，但不能再作为 Skill 的 fallback 或主流程节点。

## 当前代码观察

### 已有 MCP 能力

`opscli/mcp/tools/amazon_rufus.py` 当前只注册了：

- `amazon_rufus_get`

该工具会调用 `RufusManager.get_backend()`，并通过 `_rufus_manager_for_current_request()` 为 HTTP/SSE MCP 请求绑定当前 API Key + Agent 名称隔离的 CredentialStore。stdio 模式继续复用默认本地凭证目录。

这部分已经满足“Rufus 获取使用当前 MCP 用户 OPS 凭证”的基础要求。

### 仍缺失的 MCP 能力

Skill 当前还依赖 CLI 完成以下节点：

- `opscli amazon-rufus remote-consent status`
- `opscli amazon-rufus remote-consent set`
- `opscli amazon-rufus login-status`
- `opscli amazon-rufus watch-login`
- `opscli amazon-rufus logout`
- `opscli amazon-rufus get-backend`
- `opscli amazon-rufus platform-cookie save/get`
- `opscli auth token refresh -s ops`
- `opscli auth login`

其中 `get-backend` 已被 `amazon_rufus_get` 覆盖；`platform-cookie save/get` 不应作为 Agent 常规工具暴露完整 content，因为 content 是敏感 Rufus 状态。其它节点需要 MCP Tool 补齐。

### CLI 与业务实现关系

`opscli/amazon_rufus/commands/cli.py` 主要是 Typer 包装层，核心业务逻辑已经在：

- `opscli/amazon_rufus/services/manager.py`
- `opscli/amazon_rufus/services/remote_consent.py`
- `opscli/amazon_rufus/transport/client.py`

因此 MCP-only 改造不需要复制 CLI 逻辑。正确做法是在 `opscli/mcp/tools/amazon_rufus.py` 新增薄 MCP wrapper，复用同一个 `RufusManager` 和 `RemoteConsentStore`。

## 关键边界

### OPS/MCP 鉴权

Skill 开始时必须先走 MCP auth 工具：

1. `auth_is_authenticated()`
2. 未登录时调用 `auth_mcp_login()`
3. 需要校验 ops JWT 时调用 `auth_check_token(system="ops")`
4. Token 失效时调用 `auth_token_refresh(system="ops")`

不得在 Skill 主流程中提示或执行 `opscli auth login`、`opscli auth token refresh -s ops`。

### 远程授权偏好

远程授权偏好不是 Amazon 登录态，不含 cookie、localStorage、`storage_state`、headers、payload 或 seed request。

MCP-only 后需要新增：

- `amazon_rufus_remote_consent_status(country)`
- `amazon_rufus_remote_consent_set(country, allowed)`

HTTP/SSE MCP 模式下，授权偏好也需要按当前 MCP 请求隔离目录存储，避免多用户共享 `~/.config/opscli/amazon-rufus/remote-consent.json`。

### Amazon 登录态采集

当前 `RufusManager.watch_login()` 已经能通过 Chrome CDP 打开或连接浏览器，等待用户登录并捕获 `/rufus/cl/streaming` 请求种子。

MCP-only 后需要新增：

- `amazon_rufus_watch_login(asin, country, timeout_seconds, chrome_path, close_browser)`

该工具可以打开本机 Chrome 供用户登录，但返回值必须是脱敏摘要。不得返回 cookie、localStorage、`storage_state`、headers、payload、seed request 或平台 Cookie content。

### 登录态检查与登出恢复

需要新增：

- `amazon_rufus_login_status(country)`
- `amazon_rufus_logout(country, include_browser_profile)`

`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 和 `RUFUS_REMOTE_HTTP_ERROR status_code=401` 仍然表示 OPS/MCP 平台接口鉴权失败，不是 Amazon 登录态缺失。遇到这些错误时只走 MCP auth 恢复，不执行 `amazon_rufus_watch_login`。

### 拒绝远程授权后的处理

上一版方案在用户拒绝远程授权时 fallback 到 `opscli amazon-rufus get-backend`。新需求禁止 Skill 使用 CLI，因此拒绝远程授权后不能继续获取 Rufus。

新的处理规则：

- `allowed`：继续 MCP 登录态检查和 `amazon_rufus_get`。
- `denied`：停止本次 Skill 获取，说明 MCP-only 流程需要用户允许当前账号的 Amazon 登录态被本机 MCP/headless 链路复用。
- `unknown/invalid`：先询问用户“允许”或“拒绝”，再调用 `amazon_rufus_remote_consent_set` 保存偏好。

## 需要改造的位置

1. `opscli/mcp/tools/amazon_rufus.py`
   - 增加 remote-consent、login-status、watch-login、logout MCP 工具。
   - 给所有工具复用当前 MCP 请求凭证目录。
   - 输出严格 allowlist，避免敏感字段进入 MCP 响应。

2. `opscli/amazon_rufus/services/remote_consent.py`
   - 现有类可复用。
   - MCP wrapper 调用时传入隔离目录；无需改业务模型。

3. `opscli/skills/templates/ops-amazon-rufus/`
   - `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md` 去掉运行期 CLI 命令。
   - 删除 “MCP 不可见或拒绝远程授权时改用 CLI” 的分支。
   - 明确 MCP 工具缺失时停止并要求启用/升级 MCP Tool，不 fallback CLI。

4. `.agents/skills/ops-amazon-rufus/`
   - 同步模板副本，保证 Codex 当前可用 Skill 与内置模板一致。

5. `opscli/skills/commands/cli.py`
   - 安装 `ops-amazon-rufus` 后的 `next_steps` 仍在提示旧 CLI 命令，需要改成 MCP 工具链。

6. 测试
   - `tests/mcp/test_amazon_rufus_tools.py`：新增工具暴露、schema、脱敏响应、manager 调用和凭证隔离测试。
   - `tests/skills/test_ops_amazon_rufus_updater.py`：文档断言改成 MCP-only，并禁止出现 Skill 运行期 CLI fallback。
   - `tests/skills/test_cli.py`：安装后引导改成 MCP 工具名称。

## 结论

本需求不是删除 CLI 模块，而是重划 Skill 执行边界：

- CLI 保留：直接 CLI 用户仍可使用。
- MCP 补齐：Skill 运行所需能力都通过 MCP Tool 暴露。
- Skill 改写：Agent 只编排 MCP 工具，不执行 `opscli` 命令。
- 安全保持：敏感 Rufus 状态继续只存在于 OPS 平台 Cookie content 和内部 manager 链路，不进入 MCP 参数或响应。
