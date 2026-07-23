# Dashboard Tool Flow

适用 Skill：`ops-dashboard-ai-bridge`。兼容工具合同：`dashboard-tools.v1`；具体参数 schema 以 Dashboard 页面宿主本轮注册结果为准。

## 目录

- [快速决策](#快速决策)
- [新增图表示例](#新增图表示例)
- [组合创建流程](#组合创建流程)
- [表格和交叉表](#表格和交叉表)
- [数据集选择闸口](#数据集选择闸口)
- [显式目标单图写入](#显式目标单图写入)
- [字段定位来源](#字段定位来源)
- [字段选择纪律](#字段选择纪律)
- [筛选流程](#筛选流程)
- [查询控件流程](#查询控件流程)
- [重试规则](#重试规则)
- [写后核验短版](#写后核验短版)
- [完成判定](#完成判定)

## 快速决策

| 需求               | 起手工具                                        | 后续工具                                                                             |
| ------------------ | ----------------------------------------------- | ------------------------------------------------------------------------------------ |
| 查看当前能做什么   | `dashboard_session_get_context`                 | 无                                                                                   |
| 新增组件           | `dashboard_editor_add_component`                | `dashboard_drag_select_chart`                                                        |
| 从模板新增图表     | `dashboard_editor_add_chart_from_template`      | `dashboard_drag_select_chart`                                                        |
| 批量配置本轮新图表 | `dashboard_editor_batch_configure_charts`       | 核验全部 `chartIds` 和 `refreshed`                                                   |
| 绑定数据集         | `dashboard_drag_select_dataset`                 | 数据集选择闸口，通过后进入字段列表工具                                               |
| 添加维度或指标     | `dashboard_drag_add_field_to_list`              | `dashboard_drag_update_chart_config`                                                 |
| 批量替换字段       | `dashboard_drag_replace_field_list`             | `dashboard_drag_update_chart_config`                                                 |
| 调整字段顺序       | `dashboard_drag_reorder_field_list`             | `dashboard_drag_update_chart_config`                                                 |
| 查看已配字段       | `dashboard_drag_list_configured_fields`         | 字段配置工具                                                                         |
| 配置字段           | `dashboard_drag_get_field_config_options`       | 聚合、排序、格式等工具                                                               |
| 配置筛选           | `dashboard_drag_get_filter_field_capability`    | `dashboard_drag_apply_filter_rule`                                                   |
| 设置查询控件       | `dashboard_drag_get_query_control_item_options` | `dashboard_drag_set_query_control_item_value`、`dashboard_drag_submit_query_control` |

## 新增图表示例

用户需求：

```text
新增一个近 30 天销售额趋势图。
```

推荐流程：

1. `dashboard_session_get_context({"include_selected_chart_config": true})`
2. 从 `dashboard_editor_add_component` 的 schema enum 选择趋势图对应 `viewType`。
3. `dashboard_editor_add_component({"viewType": "line_basic"})`
4. 从 result 取 `data.chartId`。
5. 调用 `dashboard_session_search_datasets` 选择唯一销售数据集，并从真实字段目录确认日期维度和销售额指标。
6. `dashboard_editor_batch_configure_charts({"datasetId": 123, "charts": [{"chart_id": "<chartId>", "fieldLists": [{"listType": "xAxis", "fields": [{"fieldId": "<日期 actionFieldId>", "fieldSourceType": "dimensions"}]}, {"listType": "yAxis", "fields": [{"fieldId": "<销售额 actionFieldId>", "fieldSourceType": "metrics"}]}]}]})`
7. 核验 result 中 `chartIds`、`changed=true`、`refreshed=true` 和字段数量。
8. 需要近 30 天筛选时，再对该 `chart_id` 读取筛选能力并应用规则。

## 组合创建流程

用户未指定图表类型时，先按 `dashboard-operation-standards.md` 的默认组合完成规划，再执行：

1. 确认 `dashboard_editor_batch_configure_charts` 在 `availableTools`，否则停止。
2. 选择一个能覆盖全部图表的唯一数据集；存在多个真实候选时必须通过 `ask_user_question` 选择。
3. 按默认组合一次确定全部 `viewType`；营销/转化固定为 5 张，不得缩减为单图或部分组合。
4. 依次调用 `dashboard_editor_add_component` 或模板工具，收集完整组合的全部 `chartId`。
5. 需要真实字段目录时，只对其中一个新图表调用一次 `dashboard_drag_select_dataset`；使用返回的字段目录规划全部 `fieldLists`，不得调用逐字段写工具。
6. 只调用一次 `dashboard_editor_batch_configure_charts`；根级只传一个 `datasetId`，`charts` 必须覆盖本轮全部创建结果。
7. 只有 result 同时满足 `ok=true`、`changed=true`、`refreshed=true`，且返回全部 `chartIds`，本轮基础配置才算 `PASS`。
8. 后续筛选、格式或标题操作使用明确的 `chart_id`；不得为了字段写入逐个选中图表。

## 表格和交叉表

明细表：

- `viewType=detail_table`
- 常见字段列表：`xAxis`

交叉表：

- `viewType=crosstab_table`
- 行维度：`xAxis`
- 列维度：`xAxisExt`
- 指标：`yAxis`

透视表：

- `viewType=pivot_table`
- 先读该图表支持的字段配置。
- 不确定列表类型时调用 `dashboard_drag_list_configured_fields`。

## 数据集选择闸口

目标为当前选中图表时，调用 `dashboard_drag_select_dataset` 前先比较 `selectedChartDataset.datasetId/id` 与目标 `datasetId`。目标为未选中图表时直接传显式 `chart_id`；页面会对同数据集幂等处理，不会重置既有配置。成功后先核验当前工具 result 中的数据集和字段摘要。数据集身份或业务语义不确定时停止；存在多个真实候选时调用 `ask_user_question` 提供 2 到 4 个候选并等待用户选择，禁止在正文中列选项或代选。

核验要点：

- `result.ok=true` 且 `code=OK`。
- `selectedChartDataset.datasetId/id` 等于本次传入的 `datasetId`。
- `selectedChartDataset.name/displayPath` 与用户业务问题匹配。
- `selectedChartDatasetFields.dimensions/metrics` 来自当前图表的当前数据集。
- 字段摘要覆盖本次图表需要的维度、指标和筛选字段。

只有上述核验通过，才能进入字段配置。

## 显式目标单图写入

修改既有单图且已知目标图表 ID 时，以下两项写入不依赖选中态：

```text
dashboard_drag_select_dataset({"chart_id": "<目标图表>", "datasetId": 123})
dashboard_drag_add_field_to_list({"chart_id": "<目标图表>", "listType": "yAxis", "fieldId": "<actionFieldId>", "fieldSourceType": "metrics"})
```

执行后页面继续保持原图表选中。未传 `chart_id` 时，两项工具使用当前选中图表。其他字段列表、字段配置、筛选和查询控件工具仍按原流程先选中目标图表。组合创建不得使用该流程，必须走一次 `dashboard_editor_batch_configure_charts`。

## 字段定位来源

合法来源：

- `dashboard_drag_select_dataset` 返回的字段摘要。
- `selectedChartDatasetFields.dimensions`。
- `selectedChartDatasetFields.metrics`。
- `dashboard_drag_list_configured_fields` 返回的已配置字段。

不要手写字段 ID。写工具使用字段目录中的 `actionFieldId` 作为 `fieldId`，并按外层分组填写 `fieldSourceType`；页面会从当前数据集字段池还原完整字段。

## 字段选择纪律

执行字段配置前必须先完成判断：

1. 当前图表是否已有数据集。
2. 已有字段是否能复用。
3. 候选字段属于维度还是指标。
4. 字段外层分组和 `title/key/dataType` 是否符合业务问题。
5. 指标口径是否清楚，特别是比率类指标。

禁止行为：

- 不从字段列表第一个开始逐个拖入试。
- 不用 `toggleFieldChecked` 做字段猜测。
- 不用多次 `addFieldToList` 观察哪个能渲染。
- 不把字段名相似当作口径一致。
- 不在比率指标未确认分子分母时配置计算。

如果无法判断：

- 说明当前可见字段和判断依据。
- 向用户确认字段或指标口径。
- 或加载数据集查询/知识 Skill 获取口径后再配置。

一次性配置：

- 明确字段后，优先用 `replaceFieldList` 批量设置目标列表。
- 只在追加单个明确字段时使用 `addFieldToList`。
- 调整顺序时传当前完整字段集合的 `fieldId + fieldSourceType` 定位器；只改顺序，保留原字段对象中的聚合、排序、格式、筛选和重命名。
- reorder 不负责增删字段；数量、唯一性、来源或完整覆盖不一致时必须停止并修正参数。
- 配置后用 `updateChartConfig` 提交；写回只含摘要，需要核验时重读 context 或只读工具。

## 筛选流程

1. 确定目标 `chart_id`。
2. `dashboard_drag_list_configured_filters({"chart_id": "<chartId>"})`
3. `dashboard_drag_get_filter_field_capability({"chart_id": "<chartId>", "scope": "panel", "fieldId": "<fieldId>"})`
4. 如果是枚举字段，调用 `dashboard_drag_get_filter_field_enum_options`。
5. 按 capability 返回的模式调用：
   - `dashboard_drag_apply_filter_rule`
   - `dashboard_drag_apply_filter_quick_preset`

## 查询控件流程

查询控件只对 `viewType=query_control` 生效：

1. `dashboard_drag_select_chart({"chart_id": "<queryControlChartId>", "scrollIntoView": true})`
2. `dashboard_drag_get_query_control_item_options({"chart_id": "<chartId>", "fieldId": "<fieldId>"})`
3. `dashboard_drag_set_query_control_item_value({"chart_id": "<chartId>", "fieldId": "<fieldId>", "value": "xxx"})`
4. `dashboard_drag_submit_query_control({"chart_id": "<chartId>"})`

如果要恢复默认，使用 `dashboard_drag_reset_query_control`。

## 重试规则

- 只读工具失败：可以重试一次。
- 幂等写工具失败：先读 context，再决定是否重试。
- 新增、删除、清空、批量替换失败：先确认页面状态，不直接重复。
- 字段配置失败：先核对字段来源和参数，不换一批字段继续试。
- `UNSUPPORTED`：选中目标图表并等待 handler 注册，再重读 context。
- `INVALID_REQUEST`：换正确图表或换工具。

## 写后核验短版

写操作后先判定 `PASS`、`FAIL` 或 `BLOCKED`。只有 `PASS` 可以继续下一步写操作或回复完成；`FAIL` 和 `BLOCKED` 必须停止，先重读 context、查看只读列表工具或向用户确认。

## 完成判定

完成前至少满足一个条件：

- 写工具返回 `ok=true` 且 data 包含预期结果。
- 重读 context 后看到图表、数据集、字段或筛选已生效。
- 页面返回紧凑写入摘要，或通过 context/只读工具看到配置已生效。

消息桥场景还必须锁定当前 run，并确认同一 `toolCallId` 的 claim/result 成对。`failed`、`paused` 或 completed 但未调用工具都不能声明完成。

向用户回复时，只说业务结果，不暴露内部 ID。
