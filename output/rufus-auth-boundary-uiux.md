# Rufus 认证边界修复交互规范

日期：2026-06-09

## 适用范围

本需求没有图形界面。这里的 UIUX 指 CLI 输出、MCP 错误语义和 Skill 文案。不开启前端实现，不新增图标库、字体系统、design token、组件生态或页面骨架。

## 用户心智

用户只需要区分两层认证：

1. OPS/MCP 认证：用于访问 OPS 平台 Cookie API。
2. Rufus/Amazon 登录态：保存在平台 Cookie content 中，用于请求 Amazon Rufus。

两层认证的错误提示必须分开：

- OPS/MCP 认证失败：先登录或刷新 OPS/MCP。
- Amazon 登录态缺失：执行一次 `watch-login` 保存登录态和 streaming seed。

面向 Agent 的判断必须优先使用错误码，不解析 message 文案：

- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`：OPS 平台 Cookie API 鉴权失败，禁止进入 Amazon 登录恢复。
- `RUFUS_SECRET_NOT_READY`：平台 content 已可访问但 Rufus 登录态不可用，可进入一次 Amazon 登录恢复。
- `RUFUS_REMOTE_HTTP_ERROR`：保留为通用远端 HTTP 错误，只有明确不是平台 Cookie API 401 时才按其它远端错误处理。

## CLI 错误体验

### 平台 Cookie API 401

推荐 JSON：

```json
{
  "success": false,
  "command": "amazon-rufus login-status",
  "data": null,
  "error": {
    "code": "RUFUS_PLATFORM_COOKIE_AUTH_ERROR",
    "message": "OPS 平台 Cookie 接口未授权，请先刷新 opscli OPS 认证；这不是 Amazon 登录态缺失。",
    "status_code": 401
  }
}
```

推荐用户提示：

```text
OPS 平台 Cookie 接口未授权。请先执行 opscli auth token refresh -s ops；如果仍失败，重新执行 opscli auth login。不要因为该错误重新登录 Amazon。
```

### 平台 content 未命中

保持状态摘要：

```json
{
  "success": true,
  "command": "amazon-rufus login-status",
  "data": {
    "country": "US",
    "status": "missing",
    "has_login_state": false,
    "can_get_backend": false,
    "session_cookie_count": 0,
    "has_streaming_request": false
  },
  "error": null
}
```

该状态才允许进入：

```powershell
opscli amazon-rufus watch-login <ASIN> US --launch-if-needed --close-browser
```

## MCP 错误体验

### MCP OPS 未登录

推荐 Agent 提示：

```text
当前 MCP 会话没有可用 OPS 登录态，无法读取平台 Cookie content。我会先完成 MCP 登录，再重试 Rufus 获取。
```

执行顺序：

```text
auth_is_authenticated()
auth_mcp_login()
amazon_rufus_get(...)
```

### 平台 Cookie API 401

推荐 Agent 提示：

```text
Rufus MCP 无法访问 OPS 平台 Cookie 接口，错误为 RUFUS_PLATFORM_COOKIE_AUTH_ERROR。本次不会打开 Amazon 登录窗口；请先修复 MCP/OPS 认证后再重试。
```

禁止提示用户刷新 Amazon 登录态，因为此时 Amazon 登录态即使有效也无法被 OPS 平台 Cookie API 读取。

### Rufus secret 缺失

推荐 Agent 提示：

```text
当前国家站点没有可用 Amazon/Rufus 登录态。我会运行一次 watch-login 保存登录态和 Rufus 请求种子，然后按原 ASIN、国家和问题重试。
```

## Skill 分支限制

允许触发一次 `watch-login` 的错误：

- `RUFUS_SECRET_NOT_READY`
- `RUFUS_HEADLESS_CAPTURE_ERROR`
- `RUFUS_HEADLESS_REQUEST_ERROR`

禁止触发 `watch-login` 的错误：

- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`
- `RUFUS_REMOTE_HTTP_ERROR` 且 `status_code=401`
- MCP `auth_is_authenticated=false`
- OPS token refresh/login 失败

二次失败提示：

```text
本次已完成一次 Amazon 登录态刷新并重试 Rufus MCP，仍未成功；为避免重复登录循环，不再打开第二次登录窗口。错误：<ERROR_CODE>: <message>
```

## 输出边界

允许输出：

- `country`
- `status`
- `has_login_state`
- `can_get_backend`
- `session_cookie_count`
- `has_streaming_request`
- `report_path`
- 错误码和脱敏 message

禁止输出：

- OPS JWT
- session ID
- Amazon Cookie header
- `content` 原文
- `cookie_content`
- headers
- payload
- `storage_state`
- `curl_data`
- seed request
- upload payload

## 文案禁用项

不得在 OPS/MCP 鉴权失败时提示：

- “请重新登录 Amazon”
- “请运行 watch-login”
- “Rufus 登录态失效”

推荐表达：

- “OPS 平台 Cookie 接口未授权”
- “这不是 Amazon 登录态缺失”
- “先刷新 OPS/MCP 认证”

不得在 Amazon 登录态缺失时提示：

- “OPS token 过期”
- “调用 auth login 就能解决”

推荐表达：

- “当前国家站点没有可用 Amazon/Rufus 登录态”
- “运行一次 watch-login 保存登录态和 Rufus 请求种子”
