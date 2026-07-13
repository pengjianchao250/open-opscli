---
name: ops-dataset-query-mcp
description: 当前已认证账号的 MCP-only 元数据与查询路由
---

# MCP-only 运行契约

## 权威边界

当前已认证账号的 `query_metadata` 响应是唯一运行时来源。数据集、字段、公式、聚合方式、查询组件和枚举候选都必须源自本次请求链中的响应。

认证或远程元数据失败时阻断选择，先完成认证或恢复远程元数据。不得使用任何替代来源，也不得混用其他账号的响应。

## 标准流程

1. 确认 MCP 认证就绪；预期的未认证状态只引导登录。
2. 调用无参 `query_metadata()` 取得当前账号数据集卡片。
3. 自然语言只按卡片的中文名称和中文说明选择。用户明确提供精确完整英文 key 时，才对技术标识做精确匹配。
4. 候选不唯一或业务粒度不明时，展示中文卡片并澄清；用户确认前不构造查询。
5. 对已选数据集调用 `query_metadata(dataset="<alias>")`，只使用该响应的 `fields`、公式信息和 `select_columns`。
6. 确认数据集、字段、时间、筛选、排序、行数和对比口径后，只用正式 `query_simple` 执行。

## 字段与公式

- 维度、指标、聚合和输出名称以已选数据集响应为准，不跨数据集补字段。
- 公式字段含 `formula_config`、`summary_expression` 或 `detail_expression` 时不再传普通 `aggregation`。
- 快照类指标（如库存量）默认取最新快照日的值，禁止跨日累加；需要趋势时按日展示快照序列。
- 环比、同比或上期对比同时传主周期日期 `filters` 和 `data_comparison`。

## 查询组件

明确筛选字段出现在已选数据集的 `select_columns` 时：

1. 只读取该关系返回的 `component_dataset_alias`；缺少 alias 时只阻断该筛选。
2. 对该 alias 调用 `query_metadata(dataset=...)`，确认其仍属于当前账号，并取得枚举查询需要的 `table_id` 和字段。
3. 用 `query_simple` 查询组件合法值。用户值不在返回值中时，展示当前可用值并请用户重选。

## 结果与失败

按 `references/result-analysis.md` 的证据顺序输出。0 行、需要澄清、预期的认证未就绪和用户取消不是工具故障。只有意外 MCP 失败才按 `references/feedback-guide.md` 提交一次反馈；成功查询不自动提交反馈。
