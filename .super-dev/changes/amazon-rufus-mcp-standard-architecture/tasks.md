# amazon-rufus-mcp-standard-architecture tasks

## 1. 新增 domain 模型

- [x] 1.1 新增 `opscli/amazon_rufus/domain/mcp_models.py`。
- [x] 1.2 定义 `RufusGetRequest`。
- [x] 1.3 定义 `RufusWatchLoginRequest`。
- [x] 1.4 定义 `RufusRemoteConsentRequest`。
- [x] 1.5 定义 `RufusMcpResult` 或等价 MCP-safe 结果模型。

## 2. 新增 MCP façade

- [x] 2.1 新增 `opscli/amazon_rufus/services/mcp_manager.py`。
- [x] 2.2 实现 `RufusMcpManager.for_current_request()`。
- [x] 2.3 实现 remote-consent status/set。
- [x] 2.4 实现 login_status、watch_login、logout。
- [x] 2.5 实现 get，并迁移报告写入逻辑。
- [x] 2.6 将响应 allowlist 和敏感字段治理集中到 façade。

## 3. 精简 MCP Tool 层

- [x] 3.1 更新 `opscli/mcp/tools/amazon_rufus.py` 导入和工厂。
- [x] 3.2 Tool 函数改为构造 request 并调用 `RufusMcpManager`。
- [x] 3.3 移除 Tool 内部的 `AnswerReportWriter`、`RemoteConsentStore`、`RufusTransportClient` 直接依赖。
- [x] 3.4 保持 `_ALL_TOOLS` 和 Tool schema 兼容。

## 4. 测试调整

- [x] 4.1 新增 `tests/amazon_rufus/test_mcp_manager.py`。
- [x] 4.2 迁移脱敏、报告写入、凭证隔离测试到 façade 层。
- [x] 4.3 更新 `tests/mcp/test_amazon_rufus_tools.py`，聚焦 Tool 注册、schema 和参数转发。
- [x] 4.4 保留现有错误边界测试。

## 5. 变更记录与验证

- [x] 5.1 追加 `docs/change-log-pending.md`。
- [x] 5.2 运行 `uv run pytest tests/amazon_rufus/test_mcp_manager.py -q`。
- [x] 5.3 运行 `uv run pytest tests/mcp/test_amazon_rufus_tools.py -q`。
- [x] 5.4 运行 `uv run pytest tests/amazon_rufus/test_transport.py -q`。
- [x] 5.5 运行 `uv run pytest tests/skills/test_ops_amazon_rufus_updater.py -q`。
