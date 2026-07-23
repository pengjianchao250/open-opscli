# Bridge Result Protocol

适用 Skill：`ops-dashboard-ai-bridge`。兼容工具合同：`dashboard-tools.v1`；具体参数 schema 以 Dashboard 页面宿主本轮注册结果为准。

## 目录

- [单通道流程](#单通道流程)
- [Claim / Result](#claim--result)
- [Result 输出](#result-输出)
- [getContext data](#getcontext-data)
- [字段摘要](#字段摘要)
- [写工具紧凑结果](#写工具紧凑结果)
- [数据集决策](#数据集决策)
- [字段决策](#字段决策)
- [运行终态](#运行终态)
- [常见失败码](#常见失败码)

## 单通道流程

Dashboard 不注册页面 session，也没有独立 action SSE。当前链路固定为：

```text
消息 SSE / List Messages -> 当前 run 的 tool call -> claim
-> 主应用 executor -> result -> 同一 run 继续
```

AI-chat 只选择当前 active run 中 `status=running`、参数完整且尚无 result 的 Dashboard tool part。动作身份固定为：

```text
conversationId + runId + toolCallId + pageInstanceId
```

页面 executor 接收：

```json
{
  "toolCallId": "tool-call-1",
  "toolName": "dashboard_session_get_context",
  "arguments": {
    "include_selected_chart_config": true
  }
}
```

`scope=session/editor_api/drag_api` 仍可出现在 manifest 到页面方法的映射中，但它只是页面能力分组，不表示 HTTP session、页面建联或独立 SSE。

## Claim / Result

claim：

```http
POST /api/v1/conversations/{conversationId}/runs/{runId}/tool-calls/{toolCallId}/claim
```

```json
{
  "page_instance_id": "page-uuid",
  "resource_id": "dashboard-id"
}
```

result：

```http
POST /api/v1/conversations/{conversationId}/runs/{runId}/tool-calls/{toolCallId}/result
```

```json
{
  "page_instance_id": "page-uuid",
  "resource_id": "dashboard-id",
  "claim_token": "opaque-token",
  "result": {
    "ok": true,
    "code": "OK",
    "data": {}
  }
}
```

API 边界规则：

- claim/result 请求体和 `forwardedProps.tool_context` 只发送 snake_case，例如 `resource_id`、`page_instance_id`、`manifest_version`、`claim_token`。
- TypeScript 内部状态和后端响应可以使用 `resourceId`、`pageInstanceId`、`claimToken`、`toolCallId`。
- 工具 `arguments` 必须严格保持 manifest 字段名，不能全局转 snake_case。例如 `datasetId`、`listType`、`fieldSourceType` 仍按各工具 schema 发送。
- claim 425 表示 pending 暂未可见，可有限重试；409 表示其他页面已认领，当前页面必须停止执行。
- result 网络重试只能重传冻结的 result 和同一 claim token，不能再次执行页面动作。

## Result 输出

所有前端执行结果统一为：

```json
{
  "ok": true,
  "code": "OK",
  "message": "可选说明",
  "data": {}
}
```

解析顺序：

1. 看 `ok`。
2. 看 `code`。
3. 看 `message`。
4. 读取 `data` 中的下一步参数。

不要只看自然语言回复。工具 result 是下一步动作的事实来源。

## getContext data

`dashboard_session_get_context` 成功后，常见 `data` 字段：

| 字段                         | 用途                   |
| ---------------------------- | ---------------------- |
| `dashboardId`                | 当前仪表盘 ID          |
| `selectedChartId`            | 当前选中图表           |
| `charts`                     | 页面图表列表           |
| `availableTools`             | 当前已可执行工具       |
| `pendingTools`               | 当前暂未就绪工具       |
| `selectedChartDataset`       | 当前图表已绑定数据集   |
| `selectedChartDatasetFields` | 显式请求的完整字段目录 |
| `selectedChartConfig`        | 当前图表配置，按需返回 |
| `contextWarnings`            | 降级提示               |

数据集目录使用 `dashboard_session_search_datasets` 独立查询。字段目录只在选择数据集结果或 `include_dataset_fields=true` 时返回，避免每次 context 重复携带。

`dashboard_editor_batch_configure_charts` 是页面级组合写入能力，不依赖当前选中图表。调用时根级传一个 `datasetId`，并为每个 `chart_id` 传完整 `fieldLists`；页面会在全部图表和字段校验通过后统一写入并刷新。不得把它拆成多次逐图调用。

`dashboard_drag_select_dataset` 和 `dashboard_drag_add_field_to_list` 是页面级显式目标能力。只要页面存在支持的图表，它们可在没有当前选中图表时出现在 `availableTools` 中；调用时传 `chart_id` 即可。`selectedChartDataset`、`selectedChartDatasetFields` 和 `selectedChartConfig` 始终只描述当前选中图表，不代表显式目标图表。

## 字段摘要

字段摘要结构：

```json
{
  "fieldId": 101,
  "actionFieldId": "uuid-or-field",
  "title": "销售额",
  "key": "sales_amount",
  "dataType": "number"
}
```

使用规则：

- 展示和匹配用 `title`、`key`。
- 工具定位优先用 `actionFieldId`。
- 数字型数据集字段操作使用 `fieldId`。
- 外层 `dimensions` 表示维度，`metrics` 表示指标。
- `fieldExtType` 只在非空时出现。
- `selectedFieldIds` 在目录顶层集中表达已选状态。
- 字段类型和口径不明确时，不能用拖拽试错代替确认。
- 比率类指标必须确认分子、分母、统计粒度和筛选范围。

## 写工具紧凑结果

写工具成功后只返回下一步核验所需摘要，页面内部继续保留完整对象：

| 工具类型     | result.data                                                                   |
| ------------ | ----------------------------------------------------------------------------- |
| 批量图表配置 | `datasetId`、`chartIds`、`chartCount`、各字段列表数量、`changed`、`refreshed` |
| 数据集写     | `chartId`、`datasetId`、紧凑字段目录和 `selectedFieldIds`                     |
| 字段列表写   | `chartId`、`listType`、`fieldId/fieldIds`、`fieldCount`、`changed`            |
| 字段配置写   | `chartId`、`listType`、`fieldId`、`appliedKeys`、`changed`                    |
| 图表配置确认 | `chartId`、`viewType`、`changed`                                              |
| 筛选写       | `chartId`、筛选定位信息或 `logic/ruleCount`、`changed`                        |
| 查询控件值写 | `chartId`、`fieldId`、`changed`                                               |

写回不重复发送 `fields`、`field`、`filter`、`filterRule`、`previewFilter` 或 `chartConfig`。需要精确核验时，调用 `listConfiguredFields`、`listConfiguredFilters`、`getContext` 或对应读取工具。

## 数据集决策

选择数据集后的事实来源是 `selectedChartDataset` 和 `selectedChartDatasetFields`。继续字段配置前，必须确认已选数据集与请求的 `datasetId` 一致，且字段摘要能覆盖用户需要的维度、指标和筛选条件。

核验顺序：

1. 核对 `selectedChartDataset.datasetId/id` 是否等于本次传入的 `datasetId`。
2. 核对 `selectedChartDataset.name/displayPath` 是否符合用户业务问题。
3. 核对 `selectedChartDatasetFields.dimensions` 和 `.metrics` 是否来自当前图表的当前数据集。
4. 核对字段摘要是否包含本次图表需要的维度、指标、筛选字段。
5. 任一项不清楚时，停止字段配置并确认；不要用字段试错代替核验。

## 字段决策

字段配置前先从 result 读这些信息：

- 当前图表：`selectedChartId`、`selectedChartConfig`、已配置字段。
- 当前数据集：`selectedChartDataset`。
- 候选字段：`selectedChartDatasetFields.dimensions` 和 `selectedChartDatasetFields.metrics`。
- 字段业务线索：外层分组、`title`、`key`、`dataType` 和可选 `fieldExtType`。

决策顺序：

1. 根据用户业务问题确定维度、指标、筛选条件。
2. 在 result 字段摘要里匹配候选字段。
3. 说明不确定字段的判断依据。
4. 必要时询问用户确认。
5. 确认后一次性配置字段列表。

不要做字段试错：

- 不逐个字段拖入图表看结果。
- 不把 `metrics` 里的相似字段轮流放入 `yAxis`。
- 不把比率字段、金额字段、数量字段混着试。
- 不用失败结果驱动换字段，除非失败明确说明字段无效。

字段重排只接收当前完整字段集合的 `fieldId + fieldSourceType` 定位器。数量、唯一性、来源和完整覆盖必须一致；页面只调整已有对象顺序，聚合、排序、格式、筛选和重命名等配置必须保留。增删字段使用 replace/add 工具。

## 运行终态

- 排查时锁定发送后创建的当前 run ID，不能把历史消息水合出的 completed run 当成本轮结果。
- `failed` 或 `paused` 是终态；迟到的 delta、tool、todo 或 completed 事件不能恢复运行态。
- `completed` 只有在当前 run 的 claim/result 成对、页面写入核验通过后才能视为业务完成。
- 工具执行无需人工审批。业务目标或关键参数存在实质歧义时可以询问用户，这不属于工具审批。

## 常见失败码

| code                            | 含义                  | 推荐动作                          |
| ------------------------------- | --------------------- | --------------------------------- |
| `OK`                            | 成功                  | 读取 `data` 继续                  |
| `DASHBOARD_CONTEXT_MISSING`     | 未绑定编辑页          | 让用户从编辑页 AI 助手打开        |
| `DASHBOARD_RUN_CONTEXT_INVALID` | 后端运行上下文不完整  | 停止当前调用并排查 Runner 注入    |
| `CAPABILITY_NOT_ALLOWED`        | 当前页面不允许该能力  | 停止对应操作                      |
| `UNSUPPORTED`                   | 工具或 handler 未注册 | 选中图表并重读 context            |
| `VALIDATION_ERROR`              | 参数缺失或无效        | 从 context/result 补参数          |
| `INVALID_REQUEST`               | 工具不适用于当前图表  | 检查 viewType 和工具范围          |
| `TIMEOUT`                       | 页面未按时回传        | 写动作先读 context 判断是否已生效 |
| `NETWORK_ERROR`                 | 网络或接口异常        | 只读可重试，写动作先确认状态      |

## 不要做

- 不根据字段中文名编造 `fieldId`。
- 不把 `pendingTools` 当成可立即调用。
- 不把 `message` 当成功依据。
- 不在 `TIMEOUT` 后马上重复创建图表。
- 不要求 `getContext` 重复返回完整工具合同。
- 不把字段一个个拖进去试。
