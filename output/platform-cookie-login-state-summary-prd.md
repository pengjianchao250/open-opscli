# 平台登录态接口摘要 PRD

日期：2026-06-11

## 目标

让 `GET /v1/platform-cookies` 的公开接口摘要表达业务语义：读取用户在指定平台的登录态。

## 用户故事

作为 Rufus Skill 调用者，我希望接口文档明确该接口读取的是用户在指定平台保存的登录态，而不是引导我理解为只读取原始 Cookie 字符串。

作为维护者，我希望 401 语义保持清晰：401 是 OPS/JWT 鉴权失败，不是 Amazon 登录态缺失。

## 范围

本次只调整接口摘要文本：

- 目标接口：`GET /v1/platform-cookies`
- 目标摘要：`读取用户在指定平台的登录态`

不改变：

- API path、method、operationId。
- query 参数 `platform`。
- 鉴权方式 `bearerAuth`。
- 响应结构。
- Rufus 本地调用链和错误映射。

## 验收标准

1. BI MCP 刷新后的 OAS 中，`GET /v1/platform-cookies` summary 为“读取用户在指定平台的登录态”。
2. 401 文档语义仍为 JWT 缺失或失效。
3. 未保存平台登录态时不误报为 401。
4. 对话回复不展示 cookie、content、headers、payload 或登录态原文。

## 当前阻塞

当前仓库没有该 OAS 摘要的本地源文件；当前可用 BI MCP 工具也没有提供修改远端 OAS 或执行 `GET /v1/platform-cookies` 的 operation 工具。
