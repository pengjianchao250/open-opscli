# amazon-rufus-mcp-standard-architecture

## 背景

项目内 Keepa、SellerSprite、Query 等 MCP 工具的共同架构是：MCP Tool 作为薄入口，调用内部 domain request/result 模型与 services manager，不直接调用 CLI，也不直接调独立 Python 脚本。

Rufus MCP 当前已经完成 MCP-only：Skill 运行期不再 fallback CLI，`amazon_rufus_*` 工具也直接调用 `RufusManager`、`RemoteConsentStore` 和 `RufusTransportClient`。但 `opscli/mcp/tools/amazon_rufus.py` 仍承担了较多适配职责，包括 manager 工厂、授权偏好 store 工厂、报告写入、payload allowlist 和响应构造。

为对齐项目其他 MCP 工具，需要把 MCP-facing 编排收敛到 Rufus 服务层，让 Tool 层变薄。

## 目标

1. 新增 Rufus MCP/API façade，承接 MCP 凭证注入、脱敏响应、报告写入和底层业务调用。
2. 新增 MCP-facing request/result 模型，稳定 Tool 与 service 的边界。
3. 精简 `opscli/mcp/tools/amazon_rufus.py`，只保留 Tool 签名、request 构造、`_ok/_err` 和注册。
4. 保持现有 MCP Tool 名称、入参和 Skill 文档语义不变。
5. 继续禁止 cookie、headers、payload、storage_state、seed request、平台 Cookie content 等敏感字段进入 MCP 参数、响应、报告或对话。

## 非目标

1. 不删除 `opscli amazon-rufus` CLI。
2. 不让 MCP Tool 调用 `opscli amazon-rufus *`。
3. 不让 MCP Tool 调用独立 `.py` 脚本。
4. 不新增公开 `platform_cookie_get` MCP Tool。
5. 不引入远端异步 job/polling。
6. 不改变 OPS 平台 Cookie API 契约。

## 参考文档

- `output/rufus-mcp-standard-architecture-research.md`
- `output/rufus-mcp-standard-architecture-prd.md`
- `output/rufus-mcp-standard-architecture-architecture.md`
- `output/rufus-mcp-standard-architecture-uiux.md`

## 方案摘要

新增：

```text
opscli/amazon_rufus/domain/mcp_models.py
opscli/amazon_rufus/services/mcp_manager.py
```

目标调用链：

```text
opscli/mcp/tools/amazon_rufus.py
  -> RufusMcpManager
  -> RufusManager / RemoteConsentStore / AnswerReportWriter
  -> RufusTransportClient / BrowserAttachService / HeadlessRufusClient
```

Tool 层只负责：

- FastMCP Tool 函数签名。
- 构造 request dataclass。
- 调用 `RufusMcpManager`。
- 使用 `_ok/_err` 返回统一结构。

`RufusMcpManager` 负责：

- 根据当前 MCP 凭证目录创建 `AuthClient` 和 `RufusTransportClient`。
- 创建隔离 `RemoteConsentStore`。
- 调用底层 `RufusManager`。
- 写入 Rufus 报告。
- 构造 MCP-safe allowlist payload。

## 验收标准

1. `amazon_rufus.py` 不再直接 import `AnswerReportWriter`、`RemoteConsentStore`、`RufusTransportClient`。
2. `amazon_rufus.py` 不包含业务响应 allowlist builder。
3. MCP Tool 名称和 schema 保持兼容。
4. `amazon_rufus_get` 成功响应仍只返回 `report_path`、ASIN、国家、题目数、答案数和 next_action。
5. `watch_login`、`login_status`、`logout`、remote-consent 响应仍脱敏。
6. 平台 Cookie 鉴权错误仍保持 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 边界。
7. 定向测试通过。
