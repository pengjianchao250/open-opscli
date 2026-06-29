# Platform Cookie 登录态摘要调整

## 背景

当前 BI MCP OAS 中 `GET /v1/platform-cookies` 的摘要仍为“读取当前用户在指定平台的 Cookie”。Rufus Skill 实际使用该接口承载平台登录态读取，继续使用 Cookie 文案会让调用者误以为接口只暴露原始 Cookie 字符串。

## 目标

将 `GET /v1/platform-cookies` 的公开摘要调整为：

```text
读取用户在指定平台的登录态
```

同时保留现有 401 语义：HTTP 401 表示 OPS/JWT 鉴权失败，不表示 Amazon 登录态缺失。

## 范围

本变更只覆盖文案与契约验证：

- 目标 operation：`platformCookieShow`
- 目标接口：`GET /v1/platform-cookies`
- 目标 summary：`读取用户在指定平台的登录态`

不改变：

- API path、method、query 参数、operationId。
- 响应结构。
- Rufus 本地调用链。
- 敏感信息隐藏边界。

## 当前限制

当前仓库未包含 BI OAS path ref 源文件；当前可用 BI MCP 仅提供 OAS 读取/刷新能力，没有提供远端 OAS 修改能力，也没有暴露可执行 `platformCookieShow` operation 的工具。

因此仓库内可落地的是 Super Dev 文档和本地 Rufus 文案/测试同步；BI 远端 OAS 摘要需要在接口源头修改并重新发布。

## 验收

1. BI OAS 刷新后，`GET /v1/platform-cookies` summary 为“读取用户在指定平台的登录态”。
2. 401 文档仍表达 JWT 缺失或失效。
3. Rufus Skill 不展示 cookie、content、headers、payload 或登录态原文。
4. 若当前工具无法实际调用接口，应明确报告“无法用当前 BI MCP 判定成功或 401”。
