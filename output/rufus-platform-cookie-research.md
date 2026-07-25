# Rufus 平台 Cookie CLI 调研

日期：2026-06-08

## 需求背景

用户要求参考 Apifox 文档，为 Rufus Skill 补齐平台 Cookie 对应 CLI 功能，并明确 CLI/API 只需要 `platform`、`country`、`content` 三个字段。Rufus 的 cookie、headers、payload、`storage_state`、seed request 等内部材料统一整合成大 JSON 字符串保存在 `content` 中。

参考文档：

- Apifox 分享页：<https://s.apifox.cn/9c71c630-8d57-44b7-becd-f09fbe370f5e/470200491e0>
- 已刷新 OAS：`/v1/platform-cookies`，下载时间 `2026-06-08T09:34:30.657Z`

## Apifox 契约结论

`/v1/platform-cookies` 提供两个操作：

1. `POST /v1/platform-cookies`
   - 用途：保存或覆盖当前用户指定平台 Cookie。
   - 同一用户同一平台只保留一份记录。
   - Apifox 示例包含 `cookie_content`、`account_identifier`、`domain` 等字段，但本次 CLI 只发送 `platform`、`country`、`content`。
   - `content` 承载 Rufus 状态大 JSON；不拆分内部字段。

2. `GET /v1/platform-cookies?platform=<PLATFORM>`
   - 用途：读取当前用户在指定平台保存的 Cookie 记录。
   - `platform` query 必填，最大长度 50。
   - 未命中时 HTTP 仍可能是 200，但业务码 `code=404`，消息为“该平台尚未保存 Cookie”。

认证方式：

- `bearerAuth`，即 `Authorization: Bearer <JWT>`。
- opscli 侧应复用 `AuthClient().build_request_auth("ops")`，与 Rufus 上传接口、Skill 升级接口保持一致。

## 本地现状

当前 Rufus 相关入口：

- `opscli/amazon_rufus/transport/client.py`
  - 已有 `RufusTransportClient.submit_upload_payload()`。
  - 固定 path `/v1/rufus/upload`。
  - 已复用 `AuthClient().build_request_auth("ops")`、`get_mcp_request_headers()` 和 `parse_remote_response()`。

- `opscli/amazon_rufus/commands/cli.py`
  - 已有 `cookie`、`curl`、`remote-consent` 子命令组。
  - 现有本地 Cookie 输入只允许 `--from-stdin`，避免进入 shell history。
  - `remote-consent` 和 `login-status` 输出均为脱敏摘要。

- `opscli/skills/templates/ops-amazon-rufus/`
  - Skill 明确禁止输出 cookie、localStorage、`storage_state`、headers、payload、seed request。
  - Skill 不承载 Python 获取脚本，所有实现必须放在 `opscli/amazon_rufus/` 或 MCP 工具中。

## 风险与约束

1. Apifox GET 响应示例包含 `cookie_content`，CLI 默认不能直接输出远端原文，避免泄露平台 Cookie。
2. 用户明确“除国家和平台外，其他整合为 content”，所以不增加 `--cookie-content`、`--domain`、`--account-identifier` 等参数。
3. 保存接口发送 `{"platform": "<PLATFORM>", "country": "<COUNTRY>", "content": "<JSON_STRING>"}`。
4. 读取接口按 `platform` 查询后，CLI/Manager 用返回记录或 content 中的 `country` 做国家匹配。
5. 业务码 `404` 应映射成 `status=missing` 的稳定结构，而不是把它当成崩溃类错误。

## 推荐方向

采用“Transport 转发 + Manager 校验 + 状态 store 远端 content 适配 + CLI 子命令组”的最小方案：

- 在 `RufusTransportClient` 增加 `save_platform_cookie(platform, country, content)` 和 `get_platform_cookie(platform)`。
- 在 `RufusBrowserStateStore` 增加可注入远端 platform cookie client，把完整 Rufus record 序列化到 `content`。
- 在 `RufusManager` 增加 `save_platform_cookie(platform, country, content)` 和 `get_platform_cookie(platform, country)`。
- 在 `opscli amazon-rufus` 下新增 `platform-cookie` 子命令组：
  - `opscli amazon-rufus platform-cookie save <PLATFORM> <COUNTRY> --from-stdin --pretty`
  - `opscli amazon-rufus platform-cookie get <PLATFORM> <COUNTRY> --pretty`
- Skill 文档只描述 platform/country/content 三字段操作，不要求用户提供 Cookie 原文。

该方案满足 KISS/YAGNI：只实现当前明确需要的三字段契约，不扩展可选字段输入，现有 Rufus provider 继续消费统一 record。
