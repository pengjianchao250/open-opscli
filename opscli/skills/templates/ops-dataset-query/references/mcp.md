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
6. 确认数据集、字段、时间、筛选、排序、行数和对比口径后，只用正式 `query_simple` 执行。多币种请求须保持其他参数完全一致，为每个币种分别调用一次并传对应 `global_currency`。

## 多币种查询

- “分别使用人民币和加拿大元”“CNY/CAD 双币种”“同时用加拿大元对比显示”都必须执行 CNY 与 CAD 两次 `query_simple`，禁止查询一次后换算。
- 每次只传一个 `global_currency`，并以该次返回的 `meta.currency` 验证实际币种；不一致时停止金额对比并披露。
- 只有两次结果都取全，且共同维度键集合与非金额指标一致时，才能按共同维度关联金额列。
- 禁止引用 Bank of Canada Valet `FXCNYCAD`、任何其他汇率服务、模型记忆或本地计算生成另一币种金额。

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

## 意图目录工具（`query_catalog` / `query_intent_match`）

当前请求的数据集在标准流程第 2 步的 `query_metadata()` 卡片列表中不易定位、或需要业务语义辅助选表时，可用这两个工具作为选表候选参考；命中意图后仍必须按标准流程第 5 步对该数据集调用 `query_metadata(dataset="<alias>")`，**最终字段以该次响应为唯一运行时来源**，不得直接采用 intent 候选里的字段名执行查询——这与「权威边界」条款一致，不得冲突。

- `query_catalog(skills_dir=None, source="remote", fallback_local=True, session_id=None, jwt=None)`：读取数据集业务语义索引，返回完整 catalog JSON（`version`、`intent_count`、`intents` 数组、`query_strategy`）。`source` 默认 `remote`（远端优先），`fallback_local=True` 时远端失败自动回退本地缓存。

- `query_intent_match(query, skills_dir=None, source="remote", fallback_local=True, session_id=None, jwt=None)`：将自然语言 `query` 匹配到 catalog intents。返回体关键键：
  - `matched` / `selected`：`matched=true` 且候选唯一时 `selected` 即为参考候选。
  - `candidates[]`：每项含 `intent_code`、`table_id`、`dataset_alias`、`score`、`intent_constraints`（含 `hard_constraints`/`avoid_when`/`clarify_when`/`recommended_dimensions`/`recommended_metrics`/`default_filters` 等业务约束，处置口径与「查询组件」一节的组件枚举校验并列，需先向用户复述确认再套用）、`routing_status`（`direct_intent`/`embedded_intent`）、`embedded_from_table_id`。
  - `ask_user_question_required`：候选不唯一时须让用户在 `candidates` 里选，不得默认取第一个。
  - `fallback_required` / `fallback_reason`：`true` 表示 catalog 未命中，改回标准流程第 2 步的 `query_metadata()` 卡片列表选表。
  - `match_record_id`：本次匹配的服务端归因记录 ID（上报失败为 `null`）。命中候选并执行查询时，应将其与 `intent_code` 一并透传给 `query_run` / `query_build_and_run`（见下）。

## 查询执行工具的意图归因参数

`query_run` 与 `query_build_and_run` 均支持三个可选参数，用于向服务端透传本次选表来源：`intent_code`（取自 `query_intent_match` 候选的 `intent_code`）、`selection_source`（`planner`/`intent_route`/`local_fallback`/`user_specified` 四选一）、`match_record_id`（取自 `query_intent_match` 返回值的 `match_record_id`）。三者均可选，不传不影响查询执行；经 `query_intent_match` 命中候选后应一并透传，便于闭环统计。

## 结果与失败

按 `references/result-analysis.md` 的证据顺序输出。0 行、需要澄清、预期的认证未就绪和用户取消不是工具故障。只有意外 MCP 失败才按 `references/feedback-guide.md` 提交一次反馈；成功查询不自动提交反馈。
