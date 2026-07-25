# 平台登录态接口摘要架构说明

日期：2026-06-11

## 契约位置

当前 BI MCP 返回的 OAS 中，接口位于：

```text
GET /v1/platform-cookies
operationId: platformCookieShow
```

建议将该 operation 的 summary 从：

```text
读取当前用户在指定平台的 Cookie
```

调整为：

```text
读取用户在指定平台的登录态
```

## 调用链

Rufus Skill 不直接读取登录态原文，而是通过 MCP 工具获取脱敏摘要：

```text
ops-amazon-rufus Skill
  -> amazon_rufus_login_status(country)
  -> RufusMcpManager.login_status(country)
  -> RufusManager.login_status(country)
  -> RufusBrowserStateStore.load(country)
  -> RufusTransportClient.get_platform_cookie(platform="amazon")
  -> GET /v1/platform-cookies?platform=amazon
```

## 401 语义

`GET /v1/platform-cookies` 的 401 属于 OPS 平台接口鉴权失败：

- JWT 缺失。
- JWT 失效。
- 当前 MCP/OPS 凭证不可用。

该错误不表示 Amazon 未登录。Rufus transport 已将该 HTTP 401 映射为 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`，用于防止误判为 Amazon 登录态缺失。

## 实施方式

如果 OAS 摘要源在 BI 后端或 Apifox：

1. 修改 `platformCookieShow` 的 `summary` 为“读取用户在指定平台的登录态”。
2. 重新发布或导出 OAS。
3. 使用 BI MCP 刷新 OAS。
4. 再读取 `/paths/_v1_platform-cookies.json` 验证。

如果后续在本仓库同步 OAS 源文件：

1. 只改 `GET /v1/platform-cookies` 的 summary。
2. 不改响应结构和 Rufus 代码。
3. 增加文档契约断言，避免回退到 Cookie 文案。
