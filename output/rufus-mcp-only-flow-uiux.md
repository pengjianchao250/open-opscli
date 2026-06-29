# Rufus Skill MCP 全链路交互规范

日期：2026-06-09

## 适用范围

本需求没有图形界面。这里的 UIUX 指 Agent 编排文案、MCP 工具返回结构、错误提示和用户确认交互。

不新增前端页面，不冻结图标库、字体系统、design token 或组件生态。

## 用户心智

用户只需要理解三件事：

1. MCP/OPS 登录：用于访问 OPS 平台接口。
2. Amazon 登录态：用户在本机 Chrome 中登录 Amazon 后，由工具保存到 OPS 平台 Cookie content。
3. 远程授权偏好：用户是否允许当前 MCP/headless 链路复用该 Amazon 登录态。

Skill 不再要求用户执行 CLI 命令。所有动作都由 Agent 调用 MCP Tool。

## 标准提示文案

### MCP 未登录

```text
当前 MCP 会话没有可用 OPS 登录态，无法读取 Rufus 登录态。我将先通过 MCP 登录工具完成 OPS 授权。
```

后续动作：

```text
auth_is_authenticated()
auth_mcp_login()
auth_check_token(system="ops")
```

### 首次询问远程授权

```text
本次 Rufus 获取需要 Amazon 登录态。是否允许当前 MCP/headless 链路保存并复用该站点的 Amazon 登录状态？

说明：
- 保存的登录态仅供当前 MCP 用户和当前 Agent 隔离凭证使用，不会写入报告或对话回复。
- 登录态相当于已登录会话，请使用独立、干净的 Amazon 账号。
- 不建议在该 Amazon 账号中绑定信用卡或其他支付方式。
- 如果拒绝，本次 MCP-only Rufus 获取将停止，不会改用 opscli CLI。

请明确回复“允许”或“拒绝”。
```

### 用户拒绝授权

```text
已记录拒绝授权。由于当前 Skill 已切换为 MCP-only 流程，不再使用 opscli CLI fallback，本次 Rufus 获取停止。
```

### Amazon 登录态缺失

```text
当前国家站点没有可用 Amazon/Rufus 登录态。我将通过 MCP 登录采集工具打开本机 Chrome，请在打开的 Amazon 页面完成登录；工具会自动捕获 Rufus 请求种子并保存脱敏状态。
```

后续动作：

```text
amazon_rufus_watch_login(asin="<ASIN>", country="<COUNTRY>", close_browser=true)
amazon_rufus_login_status(country="<COUNTRY>")
amazon_rufus_get(...)
```

### OPS 平台 Cookie API 鉴权失败

```text
Rufus MCP 无法访问 OPS 平台 Cookie 接口，错误为 RUFUS_PLATFORM_COOKIE_AUTH_ERROR。这不是 Amazon 登录态缺失，本次不会打开 Amazon 登录窗口。我将先通过 MCP auth 工具修复 OPS/MCP 鉴权。
```

禁止提示：

- “请重新登录 Amazon”
- “请运行 watch-login”
- “Rufus 登录态失效”

### 一次恢复失败

```text
本次已通过 MCP 完成一次 Amazon 登录态刷新并重试 Rufus 获取，仍未成功。为避免重复登录循环，不再打开第二次登录窗口。错误：<ERROR_CODE>: <message>
```

## MCP 返回结构要求

### `amazon_rufus_remote_consent_status`

允许返回：

```json
{
  "country": "US",
  "status": "allowed",
  "use_remote_authorization": true,
  "updated_at": "2026-06-09T00:00:00Z",
  "source": "mcp"
}
```

### `amazon_rufus_login_status`

允许返回：

```json
{
  "country": "US",
  "status": "ready",
  "has_login_state": true,
  "can_get_backend": true,
  "session_cookie_count": 3,
  "has_streaming_request": true
}
```

### `amazon_rufus_watch_login`

允许返回：

```json
{
  "country": "US",
  "asin": "B0TEST1234",
  "saved": true,
  "login_detected": true,
  "cookie_count": 5,
  "origin_count": 1,
  "streaming_request_saved": true,
  "has_payload_template": true
}
```

### `amazon_rufus_get`

允许返回：

```json
{
  "report_path": "output/amazon-rufus/B0TEST1234-20260609-153000.md",
  "asin": "B0TEST1234",
  "country": "US",
  "question_count": 2,
  "answer_count": 2,
  "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。"
}
```

## 禁止输出

以下内容不得出现在 MCP 响应、最终回复、报告或 feedback 中：

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
- 完整原始 JSON 状态

## Skill 文案禁用项

MCP-only 后，Skill 文档不得再出现以下运行期引导：

- `opscli amazon-rufus get-backend`
- `opscli amazon-rufus watch-login`
- `opscli amazon-rufus logout`
- `opscli amazon-rufus login-status`
- `opscli amazon-rufus remote-consent`
- `opscli auth login`
- `opscli auth token refresh -s ops`
- “MCP 工具不可见时改用 CLI”
- “拒绝远程授权时改用 CLI”

允许在“CLI 兼容说明”或开发者备注中说明 CLI 仍存在，但不得作为 Skill 主流程或 fallback。
