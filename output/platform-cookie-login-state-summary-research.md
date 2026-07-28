# 平台登录态接口摘要调研

日期：2026-06-11

## 需求

将 BI MCP OAS 中 `GET /v1/platform-cookies` 的接口摘要从“读取当前用户在指定平台的 Cookie”调整为“读取用户在指定平台的登录态”。

同时延续上一轮检查：确认 Rufus Skill 中通过 BI MCP 读取 Amazon 登录态的接口当前是否能成功，还是会返回 401。

## 当前 OAS 观察

通过 BI MCP 的 OAS 读取工具获取到当前远端 OAS，下载时间为 `2026-06-08T09:34:30.657Z`。

`/v1/platform-cookies` 当前定义：

- `POST /v1/platform-cookies`：保存或覆盖平台 Cookie。
- `GET /v1/platform-cookies`：读取当前用户在指定平台的 Cookie。
- `GET` 参数：`platform`，必填，例如 `amazon`。
- `GET` 鉴权：`bearerAuth`。
- `GET` 未授权：HTTP 401，说明 JWT 缺失或失效。
- `GET` 未命中：HTTP 仍可能成功，业务码 `code=404`。

## 本地代码观察

当前仓库没有保存该 OAS path ref 源文件，也没有找到“读取当前用户在指定平台的 Cookie”这段接口摘要的本地源码。

本仓库 Rufus 调用链位于：

- `opscli/amazon_rufus/transport/client.py`
  - `PLATFORM_COOKIE_ENDPOINT = "/v1/platform-cookies"`
  - `get_platform_cookie(platform="amazon")` 调用 `GET /v1/platform-cookies?platform=amazon`。
  - 请求使用 `AuthClient().build_request_auth("ops")` 和当前 MCP 请求头。
  - 平台 Cookie API HTTP 401 会映射为 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
- `opscli/mcp/tools/amazon_rufus.py`
  - `amazon_rufus_login_status(country)` 返回 Rufus 获取前可用的 Amazon 登录态脱敏摘要。

## 验证结论

当前会话可用的 BI MCP 工具只暴露 OAS 读取与刷新能力，没有暴露执行 `platformCookieShow` 或直接请求 `GET /v1/platform-cookies` 的工具。

因此本轮不能通过“当前 BI MCP operation 实际调用”判定接口是否成功或返回 401。能确认的是：

1. OAS 当前仍显示旧摘要，需要在 BI 接口源头或 OAS 生成源中修改为“读取用户在指定平台的登录态”。
2. 如果实际调用返回 HTTP 401，按 OAS 和本地 Rufus transport 语义，原因是 OPS/JWT 鉴权缺失或失效，不是 Amazon 登录态缺失。
3. 如果鉴权成功但没有保存 `platform=amazon` 登录态，预期不是 401，而是业务码 `code=404` 或 Rufus 侧 `status=missing/invalid` 的脱敏状态。

## 边界

本次不执行反馈上报，不调用 CLI fallback，不启动 Amazon 登录采集，不尝试其他方式获取登录态。
