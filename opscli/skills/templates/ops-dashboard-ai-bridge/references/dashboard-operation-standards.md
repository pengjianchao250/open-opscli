# Dashboard Operation Standards

适用 Skill：`ops-dashboard-ai-bridge`。兼容工具合同：`dashboard-tools.v1`；具体参数 schema 以 Dashboard 页面宿主本轮注册结果为准。

## 目录

- [适用范围](#适用范围)
- [必读原则](#必读原则)
- [写后核验门禁](#写后核验门禁)
- [标准入口](#标准入口)
- [操作总流程](#操作总流程)
- [关键 result 读法](#关键-result-读法)
- [创建图表流程](#创建图表流程)
- [数据集和字段](#数据集和字段)
- [筛选和查询控件](#筛选和查询控件)
- [错误恢复](#错误恢复)
- [数据集取数约束](#数据集取数约束)

## 适用范围

用于运营系统仪表盘编辑页的 AI 对话操作，包括：

- 新增、修改、配置仪表盘图表。
- 分析前端返回的 dashboard bridge `result`。
- 选择数据集、字段、筛选、查询控件。
- 排查 dashboard tools、临时 `tool_context`、消息工具调用、claim/result 或页面回传失败。

## 必读原则

1. 下拉选择只调整创建或分析的处理优先级；主模型结合用户原始消息、页面状态和 Skill 规范自主决定是否写页面。
2. 选择创建偏好并提出分析目标时，优先评估创建相关图表后再分析；选择数据分析偏好时优先复用当前页面直接分析。
3. 先读页面上下文，再执行写操作。
4. 不猜 `chart_id`、`datasetId`、`fieldId`、`actionFieldId`。
5. 每个工具结果都按 `ok/code/message/data` 解析。
6. 写操作后用 result 或重新读取 context 验证。
7. 用户目标清楚时直接执行完成任务所需的 dashboard tools，不因 destructive 标签额外审批或逐步确认；目标或关键参数有实质歧义时再询问，业务询问不等于工具审批。
8. 字段必须来自前端 result 或已配置字段，不允许一个个拖字段试错。
9. 数据集业务口径不确定时，先问用户或加载 `ops-dataset-query`，不硬猜。
10. 比率类指标必须先确认分子、分母、粒度和筛选口径，再计算或配置。
11. 禁止生成、修改、上传或导出任何文件产物。

## 写后核验门禁

任何写操作完成后，必须先完成核验门禁，才允许继续下一次写操作、重试写工具或向用户声明完成。

写操作包括：新增图表、删除、清空、批量替换、选择数据集、添加或替换字段、字段配置、筛选配置、查询控件提交、`updateChartConfig` 以及其他会改变页面状态的工具。

门禁步骤：

1. 解析本次工具 `result.ok/code/message/data`。
2. 明确本次动作的预期页面状态，例如：新增图表存在、目标图表被选中、数据集已绑定、字段列表已更新、筛选已生效。
3. 使用以下证据之一核验：
   - 当前写工具返回 `ok=true`，且 `data` 明确包含预期状态。
   - 重新读取 `dashboard_session_get_context({"include_selected_chart_config": true})` 后看到预期状态。
   - 调用对应只读列表工具后看到预期状态，例如已配字段、筛选、查询控件配置。
4. 得出判定：`PASS`、`FAIL` 或 `BLOCKED`。
5. 只有 `PASS` 可以继续下一步写操作或回复完成。

失败处理：

- `FAIL`：停止后续写操作，先按 `code` 恢复或重读 context。
- `BLOCKED`：证据不足时停止，不猜测成功，不继续试错；向用户说明缺少什么证据。
- `TIMEOUT`、`NETWORK_ERROR`：写动作必须先重读 context 判断是否已生效，再决定是否重试。
- 新增、删除、清空、批量替换失败：不得直接重复调用同一写工具。
- 字段配置失败：不得换一批字段继续试，必须先核对字段来源、字段类型、参数和业务口径。

禁止绕过：

- 不用自然语言 `message` 当作成功依据。
- 不因操作简单、用户催促而跳过核验。
- 不把“下一步工具也会报错”当作核验。
- 不在核验未通过时声明“已完成”。

## 标准入口

在 dashboard editor context 中，优先调用：

- `dashboard_session_get_context`

`dashboard_session_*` 是稳定工具名，`scope=session` 是页面能力分组；两者都不表示 HTTP session 或页面建联。

如果返回 `DASHBOARD_CONTEXT_MISSING`，说明当前对话没有从仪表盘编辑页绑定页面工具。提示用户从编辑页 AI 助手重新打开。

如果返回 `DASHBOARD_RUN_CONTEXT_INVALID`，说明后端没有为当前工具调用注入运行标识。停止当前工具调用并排查 Runner 上下文；不要让用户重新绑定页面，也不要要求客户端补传 `run_id`。

## 操作总流程

1. 调用 `dashboard_session_get_context({"include_selected_chart_config": true})`。
2. 查看 `availableTools`、`pendingTools`、`charts` 和当前数据集摘要。
3. 需要数据集时调用 `dashboard_session_search_datasets`；需要字段时读取选择数据集结果，或显式传 `include_dataset_fields=true`。
4. 基于用户业务问题，先列出需要的维度、指标、筛选条件和计算口径。
5. 如果字段名或口径不确定，说明判断依据并向用户确认，不做字段试错。
6. 如果用户要新增图表，按工具 schema 的 `viewType` enum 调用 `dashboard_editor_add_component`，或使用 `dashboard_editor_add_chart_from_template`。
7. 新增成功后，用返回的 `data.chartId` 调 `dashboard_drag_select_chart`。
8. 需要数据时，从 `dashboard_session_search_datasets` 的唯一候选取真实 `datasetId`；仅当当前图表未绑定该数据集时调用 `dashboard_drag_select_dataset`。
9. 数据集核验 `PASS` 后，从字段 result 中选择维度或指标，一次性配置到字段列表。
10. 按需配置聚合、排序、格式、筛选、查询控件。
11. 调用 `dashboard_drag_update_chart_config` 或对应提交工具。
12. 读取最终写入摘要；需要精确核验时调用 context 或对应只读工具，再向用户说明完成项。

## 关键 result 读法

工具返回结构固定：

```json
{
  "ok": true,
  "code": "OK",
  "message": "可选说明",
  "data": {}
}
```

处理规则：

- `ok=true`：把 `data` 当作下一步输入；写工具的 `data` 是紧凑摘要。
- `ok=false`：先按 `code` 恢复，不要立刻放弃。
- 工具合同由后端注册层直接提供，不再通过 `getContext` 重复返回。
- `data.availableTools`：当前可调用工具。
- `data.pendingTools`：页面 handler 暂未注册，通常需要选中图表、等待或重读 context。
- `data.selectedChartDatasetFields`：显式请求时返回的完整紧凑字段目录。
- 写工具不重复返回完整字段、筛选或图表配置；需要核验时调用对应读取工具。

协议细节见 `bridge-result-protocol.md`。

## 创建图表流程

新增普通组件：

1. 从 `dashboard_editor_add_component` 的 `viewType` enum 确认合法类型。
2. 调用 `dashboard_editor_add_component({"viewType": "<viewType>"})`。
3. 从 result 取 `data.chartId`。
4. 调用 `dashboard_drag_select_chart({"chart_id": "<chartId>", "scrollIntoView": true})`。

从模板新增：

1. 确认模板参数来自用户或可信上下文。
2. 调用 `dashboard_editor_add_chart_from_template`。
3. 后续同样先 `selectChart`，再配置数据集和字段。

表格类自然语言映射：

- “表格”默认 `detail_table`。
- “交叉表”使用 `crosstab_table`。
- “透视表”使用 `pivot_table`。
- “查询控件/筛选控件”使用 `query_control`。

具体工具步骤见 `tool-flow.md`。

## 数据集和字段

选择数据集：

1. 调用 `dashboard_session_search_datasets`，按 `name` 或 `displayPath` 匹配唯一候选。
2. 比较 context 中当前 `selectedChartDataset.datasetId/id` 与目标 `datasetId`；相同则跳过选择，直接复用当前字段目录和既有配置。
3. 仅在数据集不同时调用 `dashboard_drag_select_dataset({"chart_id": "<chartId>", "datasetId": 123})`。
4. 读取该 result 返回的字段摘要，并进入数据集核验。
5. 选择前必须确认候选数据集唯一或业务语义明确；多个相似候选、同名候选或业务域不清时停止并询问用户。
6. 选择后先核验 `selectedChartDataset`：其 `datasetId/id` 必须等于本次传入的 `datasetId`，`name/displayPath` 必须匹配用户业务问题。
7. 继续配置字段前，确认 `selectedChartDatasetFields` 来自当前图表和当前数据集，并包含本次图表需要的维度、指标和筛选字段；缺失时不换字段试错。

字段选择纪律：

- 先确认当前图表已选数据集、已有字段、字段类型和字段口径。
- 先把业务问题拆成维度、指标、筛选条件，再找对应字段。
- 字段名或口径不确定时，说明依据并询问用户。
- 一次性配置判断明确的字段，不通过反复拖入字段观察效果来试错。
- 比率类指标不能随便试字段，必须确认分子、分母、统计粒度、筛选范围。
- 如果 result 没有足够字段信息，先重读 context、选择数据集或加载数据集 Skill。

字段选择：

- 维度字段来自 `dimensions`。
- 指标字段来自 `metrics`。
- 字段操作优先使用 `actionFieldId`。
- 数字型数据集操作使用 `fieldId`；字段列表写入优先使用 `actionFieldId`。

字段列表：

- `xAxis`：行、维度。
- `xAxisExt`：列维度，常用于交叉表或透视表。
- `yAxis`：指标、度量。
- `drillFields`：下钻。
- `shortcutFilter`：快捷筛选。

常用工具：

- `dashboard_drag_add_field_to_list`
- `dashboard_drag_replace_field_list`
- `dashboard_drag_list_configured_fields`
- `dashboard_drag_get_field_config_options`
- `dashboard_drag_set_field_aggregation`
- `dashboard_drag_set_field_sort`
- `dashboard_drag_set_field_value_format`
- `dashboard_drag_reorder_field_list`

字段写入定位器：

```json
{
  "fieldId": "<字段目录中的 actionFieldId>",
  "fieldSourceType": "dimensions"
}
```

`fieldSourceType` 根据字段所在的 `dimensions/metrics` 外层分组填写，不传完整字段对象。

字段重排规则：

- `dashboard_drag_reorder_field_list` 只接收当前完整字段集合的 `fieldId + fieldSourceType` 定位器。
- 定位器数量、唯一性、来源和完整覆盖必须与已配置字段一致。
- 重排只改变顺序，必须保留聚合、排序、格式、筛选、重命名和其他已有配置。
- 需要增加或删除字段时使用 replace/add/delete 工具，不能用 reorder 重建字段对象。

## 筛选和查询控件

筛选规则：

1. `dashboard_drag_list_configured_filters`
2. `dashboard_drag_get_filter_field_capability`
3. 枚举字段再调用 `dashboard_drag_get_filter_field_enum_options`
4. `dashboard_drag_apply_filter_rule` 或 `dashboard_drag_apply_filter_quick_preset`

查询控件只用于 `query_control`：

1. 选中查询控件图表。
2. 必要时调用 `dashboard_drag_get_query_control_item_options`。
3. 调用 `dashboard_drag_set_query_control_item_value`。
4. 调用 `dashboard_drag_submit_query_control`。

如果普通图表调用查询控件工具，页面会返回 `INVALID_REQUEST`。

## 错误恢复

| code | 处理 |
| --- | --- |
| `DASHBOARD_CONTEXT_MISSING` | 提示用户从仪表盘编辑页 AI 助手重新打开 |
| `DASHBOARD_RUN_CONTEXT_INVALID` | 停止当前调用并排查 Runner 的 `run_id` 注入 |
| `CAPABILITY_NOT_ALLOWED` | 当前页面能力不允许，不绕过 |
| `UNSUPPORTED` | 先 `selectChart`，再重读 `availableTools/pendingTools` |
| `VALIDATION_ERROR` | 补齐 `chart_id`、`listType`、`fieldId` 等参数 |
| `INVALID_REQUEST` | 检查图表类型和工具适用范围 |
| `TIMEOUT` | 写动作先重读 context，确认是否已生效，再决定是否重试 |
| `NETWORK_ERROR` | 只读或幂等动作可重试，写动作先确认页面状态 |

## 数据集取数约束

如果用户要求查询真实业务数据、比较指标或生成分析结论，先加载并遵循 `ops-dataset-query` Skill。不要自行拼接 `opscli query`，不要猜 `query_*` 参数，不直连数据库。

dashboard bridge tools 负责编辑页面；数据集取数工具负责业务数据分析。组合执行时保持职责分离，先核验页面写入，再基于真实查询结果给出分析结论。
