# amazon-rufus-mcp-only-flow

## 背景

`ops-amazon-rufus` Skill 已切换为 MCP-first 使用方式，但当前文档和安装引导仍把部分前置流程交给 `opscli amazon-rufus` CLI，包括授权偏好、登录态检查、登录采集、登出恢复和拒绝远程授权后的 `get-backend` fallback。

用户已明确要求：Skill 使用 MCP 后不再使用 opscli CLI 处理，运行期全程走 MCP 提供的工具。

## 目标

1. 为 Rufus Skill 补齐运行期所需 MCP Tool。
2. Skill 主流程不再调用 `opscli amazon-rufus *` 或 `opscli auth *`。
3. MCP 鉴权失败通过 MCP auth 工具处理。
4. 用户拒绝远程授权时停止，不再 fallback CLI。
5. 保持敏感 Rufus 状态不进入 MCP 参数、响应、报告或 feedback。

## 非目标

1. 不删除已有 CLI 命令。
2. 不新增平台 Cookie content 直读 MCP Tool。
3. 不引入异步 job/polling。
4. 不改变 Rufus 获取报告格式。

## 参考文档

- `output/rufus-mcp-only-flow-research.md`
- `output/rufus-mcp-only-flow-prd.md`
- `output/rufus-mcp-only-flow-architecture.md`
- `output/rufus-mcp-only-flow-uiux.md`

## 设计摘要

新增 MCP Tool：

- `amazon_rufus_remote_consent_status`
- `amazon_rufus_remote_consent_set`
- `amazon_rufus_login_status`
- `amazon_rufus_watch_login`
- `amazon_rufus_logout`

保留既有：

- `amazon_rufus_get`

所有 MCP Tool 复用 `RufusManager` 或 `RemoteConsentStore`，只增加轻量 wrapper 和脱敏输出。

## 验收标准

1. `list_tools` 可见新增 Rufus MCP Tool。
2. Skill 文档不再把 CLI 作为主流程或 fallback。
3. 安装后引导改为 MCP 工具链。
4. `watch_login`、`login_status`、`logout` 返回脱敏摘要。
5. 定向测试通过。
