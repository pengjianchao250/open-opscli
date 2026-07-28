# Dashboard Tool Contract

适用 Skill：`ops-dashboard-ai-bridge`。兼容 `dashboard-tools.v2`。本文件定义页面工具顺序、参数来源、结果读取、写后核验和错误处理；业务规则见 `dashboard-operation-standards.md`。具体参数必须服从本轮工具 schema。

## 通用起点

1. 调用 `dashboard_session_get_context({"include_selected_chart_config": true})`。
2. 只使用 `availableTools` 中的工具；`pendingTools` 只能等待就绪或重读上下文。
3. 从 `charts`、`selectedChartId` 和当前配置取得真实目标，不猜测 `chart_id`。
4. 每次写入后完成本文件的核验门禁，通过后才进入下一次写入。

## 组合新增

1. 调用 `dashboard_session_search_datasets` 获取真实候选；需要选择时按操作规范使用 `ask_user_question`。
2. 调用 `dashboard_session_get_dataset_fields({"datasetId": 123})` 读取唯一数据集的完整字段目录。
3. 从 `dashboard_editor_batch_create_charts.charts[].viewType` enum 选择合法类型，一次规划全部 `title/layout/fieldLists`。
4. 字段只使用目录返回的真实定位器：

```json
{"fieldId":"<actionFieldId>","fieldSourceType":"dimensions"}
```

5. 通过一个 `dashboard_editor_batch_create_charts` 请求提交根级唯一 `datasetId` 和完整 `charts`。不得拆成逐图创建、逐图选数据集或逐字段试写。
6. 批量结果通过核验后，再对明确的 `chartId` 添加筛选、格式或其他定向配置。

显式单图未指定尺寸时可省略 `layout`。组合新增按操作规范提供默认 `w/h`；批量工具 schema 未声明 `x/y` 时不得提交。

## 既有图表修改

已知目标 `chart_id` 时直接调用显式目标工具，不改变原选中态：

```text
dashboard_drag_select_dataset({"chart_id":"<目标图表>","datasetId":123})
dashboard_drag_add_field_to_list({"chart_id":"<目标图表>","listType":"yAxis","fieldId":"<actionFieldId>","fieldSourceType":"metrics"})
dashboard_drag_set_chart_title({"chart_id":"<目标图表>","title":"区域销售额趋势"})
dashboard_drag_patch_chart_style({"chart_id":"<目标图表>","styleKey":"legend","fields":[...]})
dashboard_drag_move_chart({"chart_id":"<目标图表>","x":0,"y":6})
```

- 数据集和单字段添加工具未传 `chart_id` 时才使用当前选中图表。
- 标题、样式和移动必须直接作用于显式目标，禁止先选择其他图表。
- 字段替换、字段配置、筛选和查询控件等依赖设置面板的工具，按本轮 schema 判断是否需要先调用 `dashboard_drag_select_chart`。
- 移动前读取当前布局，调用后核验 `finalPosition`、`affectedCharts` 和 `changed`。

## 字段配置

合法字段来源包括 `dashboard_session_get_dataset_fields`、数据集选择结果、`selectedChartDatasetFields.dimensions/metrics` 和 `dashboard_drag_list_configured_fields`。

1. 调用 `dashboard_drag_list_configured_fields` 读取当前配置。
2. 使用 `dashboard_drag_replace_field_list` 一次设置明确字段；只追加一个明确字段时使用 `dashboard_drag_add_field_to_list`。
3. 需要聚合、排序或格式时，先调用 `dashboard_drag_get_field_config_options`，再使用对应设置工具。
4. 调整顺序时调用 `dashboard_drag_reorder_field_list`，提交当前完整字段集合的定位器。
5. 需要提交图表配置时调用 `dashboard_drag_update_chart_config`。

不得使用 `toggleFieldChecked` 或反复 `addFieldToList` 观察哪个字段能渲染。

## 表格和控件

| 用户表达 | `viewType` | 流程 |
| --- | --- | --- |
| 表格 | `detail_table` | 常用字段槽位 `xAxis` |
| 交叉表 | `crosstab_table` | 行 `xAxis`、列 `xAxisExt`、指标 `yAxis` |
| 透视表 | `pivot_table` | 先读取该类型支持的字段配置 |
| 查询控件 | `query_control` | 使用查询控件专用工具 |

筛选顺序：

1. `dashboard_drag_list_configured_filters`
2. `dashboard_drag_get_filter_field_capability`
3. 枚举字段调用 `dashboard_drag_get_filter_field_enum_options`
4. 调用 `dashboard_drag_apply_filter_rule` 或 `dashboard_drag_apply_filter_quick_preset`

查询控件顺序：

1. 按 schema 选择或指定 `query_control` 目标。
2. `dashboard_drag_get_query_control_item_options`
3. `dashboard_drag_set_query_control_item_value`
4. `dashboard_drag_submit_query_control`

恢复默认时使用 `dashboard_drag_reset_query_control`。普通图表返回 `INVALID_REQUEST` 时停止。

## Result 读取

页面工具统一返回：

```json
{"ok":true,"code":"OK","message":"可选说明","data":{}}
```

按 `ok -> code -> data` 读取；`message` 只用于说明，不能单独作为成功依据。写工具返回紧凑摘要，需要更多证据时重读上下文或调用对应只读工具。

`dashboard_session_get_context` 中，`selectedChartId/charts` 表示目标列表，`availableTools/pendingTools` 表示工具状态，`selectedChartDataset/selectedChartDatasetFields/selectedChartConfig` 只描述当前选中图表，不能代替显式目标工具的 result。`gridColumn` 是固定 12 列的只读诊断值。

字段摘要以外层 `dimensions/metrics` 表示角色；展示匹配使用 `title/key`，定位使用真实 `fieldId/actionFieldId`。`complete=true` 表示页面返回了未分页、未截断的完整字段目录。

## 写后核验

每次写入后必须判定 `PASS`、`FAIL` 或 `BLOCKED`，只有 `PASS` 可以继续写入或声明完成。

1. 解析 `result.ok/code/data`，明确预期状态和目标 `chartId`。
2. 使用写工具摘要、重新读取上下文或对应只读列表工具确认最终状态。
3. 组合新增逐张核验图表数量、`viewType/title/layout/fieldLists`、`changed` 和 `refreshed`。
4. 定向修改核验返回 `chartId` 等于目标，且非目标图表未变化。
5. 证据完整且符合计划为 `PASS`；明确失败为 `FAIL`；证据不足或结果不确定为 `BLOCKED`。

批量结果部分成功或任一图表不符合计划时判定 `FAIL`，确认回滚前不得追加写入。

## 错误处理

| code | 动作 |
| --- | --- |
| `DASHBOARD_CONTEXT_MISSING` | 提示从仪表盘编辑页 AI 助手进入后重试 |
| `DASHBOARD_RUN_CONTEXT_INVALID` | 停止当前调用，不要求用户补传内部标识 |
| `CAPABILITY_NOT_ALLOWED` | 停止对应操作，不绕过页面权限 |
| `UNSUPPORTED` | 检查目标图表和 `availableTools/pendingTools` |
| `VALIDATION_ERROR` | 根据真实 schema、数据集和字段目录修正；字段角色最多修正一次 |
| `INVALID_REQUEST` | 检查图表类型和工具适用范围 |
| `TIMEOUT`、`NETWORK_ERROR` | 写操作先重读页面状态，确认未生效后才可重试 |

只读工具可重试一次。新增、删除、清空、批量替换或其他结果不确定的写入不得直接重复；失败后不得更换一批字段继续试错。

## 模板和非图表组件

- 从可信模板新增图表：`dashboard_editor_add_chart_from_template`。
- 新增非图表组件：`dashboard_editor_add_component`。
- 创建后取得真实 `chartId`，后续配置按既有图表修改流程执行。
