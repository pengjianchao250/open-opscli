# Dashboard Operation Standards

适用 Skill：`ops-dashboard-ai-bridge`。兼容工具合同：`dashboard-tools.v2`；具体参数 schema 以 Dashboard 页面宿主本轮注册结果为准。

## 目录

- [适用范围](#适用范围)
- [必读原则](#必读原则)
- [写后核验门禁](#写后核验门禁)
- [标准入口](#标准入口)
- [操作总流程](#操作总流程)
- [关键 result 读法](#关键-result-读法)
- [创建图表流程](#创建图表流程)
- [未指定类型的默认组合](#未指定类型的默认组合)
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
12. 同一轮新建的图表必须先整体规划，并使用同一个数据集；禁止跨数据集拼成一组图表。
13. 确定数据集后必须先通过 `dashboard_session_get_dataset_fields` 读取完整字段目录，再规划图表；禁止先创建空图再试字段。
14. 多个真实候选会改变结果时必须调用 `ask_user_question`，提供 2 到 4 个来自页面结果的候选并等待用户选择；禁止只在正文中列选项、要求用户手输序号或替用户选择。
15. 普通图表创建前确定 1 到 100 字的业务标题，通过 `dashboard_editor_batch_create_charts.charts[].title` 首次写入；标题不得依赖创建后的补偿修改。
16. 字段角色以页面字段目录和图表规则为准：维度、度量分别进入当前字段区允许的角色；页面返回角色校验失败时只允许基于真实元数据修正一次。
17. 修改标题、局部样式和位置时使用三个显式目标工具；样式一次只改一个 `styleKey`，移动前读取当前布局，固定 12 列边界由运行合同和页面校验。
18. 默认组合必须且只能调用一次 `dashboard_editor_batch_create_charts`；不得拆成逐图新增、逐图选集或独立字段配置。

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
2. 查看 `availableTools`、`pendingTools`、`charts` 和当前数据集摘要；`gridColumn` 仅作为固定 12 列边界的只读诊断事实。
3. 需要数据集时调用 `dashboard_session_search_datasets`；确定唯一数据集后调用 `dashboard_session_get_dataset_fields` 读取完整字段目录。
4. 基于用户业务问题，先列出需要的图表类型、统一数据集、维度、指标、筛选条件和计算口径。
5. 如果字段名或口径不确定，说明判断依据并向用户确认，不做字段试错。
6. 用户要新增图表但未指定类型时，按默认组合表选型并保持规定数量；营销/转化必须创建 5 张。
7. 为每张图表确定业务标题；受控模板的图表类型、顺序和布局直接取自运行合同，不在提示词中重复计算。
8. 使用字段目录一次规划全部图表的完整 `fieldLists`，并在任何页面写入前完成图表字段规则校验。
9. 只调用一次 `dashboard_editor_batch_create_charts`，传入唯一 `datasetId` 和完整 `charts`；禁止调用旧的逐图新增、选集或独立批量配置链路。
10. 核验批量结果覆盖全部图表，且 `changed=true`、`refreshed=true`；再逐张核验精确 `chartId/viewType/title/layout/fieldLists`，失败时停止后续写入。
11. 按需对明确目标图表配置聚合、排序、格式、筛选、查询控件。
12. 读取最终写入摘要；需要精确核验时调用 context 或对应只读工具，再向用户说明完成项。

标题、样式和移动的目标必须由 `chart_id` 明确指定：

这三类操作不得先调用 `dashboard_drag_select_chart`；工具必须直接作用于显式目标，并保持原选中图表不变。

- 标题：`dashboard_drag_set_chart_title({"chart_id":"<chartId>","title":"转化率趋势"})`。
- 样式：`dashboard_drag_patch_chart_style({"chart_id":"<chartId>","styleKey":"legend","fields":[{"field":"showLegend","value":false}]})`。
- 位置：先读取 `charts` 布局，再调用 `dashboard_drag_move_chart({"chart_id":"<chartId>","x":0,"y":6})`；页面按固定 12 列边界校验。

三类写入均需核验 `changed` 和返回的最终状态；移动以 `finalPosition` 为准，不把请求坐标当作 GridStack 最终坐标。

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

新增普通组件或组合：

1. 从 `dashboard_editor_batch_create_charts` 的 `charts[].viewType` enum 确认合法类型。
2. 确定本轮全部图表和统一数据集，再调用 `dashboard_session_get_dataset_fields` 读取完整字段目录。
3. 一次确定每张图表的 `viewType/title/fieldLists`；受控模板布局由后端按运行合同注入，显式单图可按用户要求传入布局，未指定时使用页面默认尺寸。
4. 只调用一次 `dashboard_editor_batch_create_charts` 创建并配置全部图表，不降级为逐图写入。

从模板新增：

1. 确认模板参数来自用户或可信上下文。
2. 调用 `dashboard_editor_add_chart_from_template`。
3. 后续同样收集 `chartId`，并纳入一次批量配置。

表格类自然语言映射：

- “表格”默认 `detail_table`。
- “交叉表”使用 `crosstab_table`。
- “透视表”使用 `pivot_table`。
- “查询控件/筛选控件”使用 `query_control`。

具体工具步骤见 `tool-flow.md`。

## 未指定类型的默认组合

用户明确指定图表类型时优先服从用户。未指定类型时，只选择 `data/dashboard-runtime-contract.json` 定义的受控模板：

| 模板键                 | 识别线索                 | 类型与布局来源                                 |
| ---------------------- | ------------------------ | ---------------------------------------------- |
| `marketing_conversion` | 广告、流量、活动、营销、转化 | `dashboard-runtime-contract.json` 对应模板     |
| `supply_chain`         | 库存、物流、履约、供应链 | `dashboard-runtime-contract.json` 对应模板     |

无法唯一判断模板时询问用户；不创建合同外的兜底组合，也不在参考文档中复制类型和尺寸列表。

组合约束：

- 默认组合按合同中的数量和顺序完整创建，不得缩减为单图或部分组合。
- 必须用真实字段目录验证可行性；缺少合同图表所需字段时停止并说明阻塞，不擅自替换类型。
- 全部图表共享一个 `datasetId`。任何图表需要第二数据集才能成立时，停止并调整组合，不得跨数据集拼接。
- 图表类型、数据集、字段必须在创建前确定；创建后只允许按已确认计划批量写入，不允许用页面结果反向试字段。

### 合同模板布局

画布固定为 12 列。精确图表类型、顺序和宽高只在 `data/dashboard-runtime-contract.json` 维护，由后端在批量创建时注入；模型不读取用户输入的列数，也不计算尺寸。

创建规则：

1. 选择唯一匹配的模板键，并保持合同给出的图表数量和顺序。
2. 营销/转化模板保持两张摘要图同高、三张分析图全宽；供应链模板保持两张摘要图同高、两张分析图全宽。
3. `indicator` 只配置 1 个度量；`pie_circle` 只配置 1 个类别维度和 1 个度量；其他图表按各自字段规则配置。
4. 批量返回后逐张核验 `chartId/viewType/title/layout/fieldLists` 与运行合同一致；任意矩形重叠都判定为 `FAIL`。

## 数据集和字段

字段角色以页面字段目录的外层分组为准：`dimensions` 是维度，`metrics` 是度量。写入前必须确认目标字段区允许该真实角色；只有同时允许两种角色的字段区才能混用。角色不兼容返回 `VALIDATION_ERROR` 时，基于真实元数据修正一次，仍失败则停止。

本轮新建图表使用页面级批量工具：确定唯一数据集后先调用 `dashboard_session_get_dataset_fields`，再由 `dashboard_editor_batch_create_charts` 一次创建并配置完整组合。下面的逐图字段写入流程只用于修改既有单图，不用于组合创建。

选择数据集：

1. 调用 `dashboard_session_search_datasets`，按 `name` 或 `displayPath` 匹配唯一候选。
2. 目标是当前选中图表时，比较 context 中 `selectedChartDataset.datasetId/id` 与目标 `datasetId`；相同则跳过选择并复用既有配置。
3. 目标是未选中图表时，不用先选中；直接调用 `dashboard_drag_select_dataset({"chart_id": "<chartId>", "datasetId": 123})`，同数据集会幂等保留既有配置。
4. 读取该 result 返回的字段摘要，并进入数据集核验。
5. 选择前必须确认候选数据集唯一或业务语义明确；多个相似候选、同名候选或业务域不清时停止，并调用 `ask_user_question` 让用户从真实候选中选择。
6. 当前选中图表可核验 `selectedChartDataset`；未选中目标必须核验本次工具 result 中的 `datasetId/datasetName`，不能读取当前选中图表代替目标。
7. 继续配置字段前，确认本次选择数据集 result 的字段摘要包含所需维度、指标和筛选字段；当前选中图表也可用 `selectedChartDatasetFields` 复核，缺失时不换字段试错。

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

显式目标规则：

- `dashboard_drag_select_dataset` 和 `dashboard_drag_add_field_to_list` 在传入有效 `chart_id` 时直接作用于目标图表，不改变页面选中态、右侧设置面板、滚动或焦点。
- 这两项工具缺省 `chart_id` 时回退当前选中图表；页面没有选中图表时必须显式传入。
- 未选中图表的写入以当前工具 `result.data` 为核验证据，不能拿 context 中当前选中图表的 `selectedChartDataset` 或 `selectedChartConfig` 判断目标图表结果。
- `replaceFieldList`、字段配置、筛选和查询控件等其他 drag 工具仍依赖当前设置面板；操作其他图表前先 `selectChart`。
- 以上规则仅用于既有单图修改；同轮新建组合必须使用 `dashboard_editor_batch_create_charts`。

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

字段角色 `VALIDATION_ERROR` 只允许按真实字段目录修正一次；仍失败时停止，不换字段反复试错。

| code                            | 处理                                                   |
| ------------------------------- | ------------------------------------------------------ |
| `DASHBOARD_CONTEXT_MISSING`     | 提示用户从仪表盘编辑页 AI 助手重新打开                 |
| `DASHBOARD_RUN_CONTEXT_INVALID` | 停止当前调用并排查 Runner 的 `run_id` 注入             |
| `CAPABILITY_NOT_ALLOWED`        | 当前页面能力不允许，不绕过                             |
| `UNSUPPORTED`                   | 先 `selectChart`，再重读 `availableTools/pendingTools` |
| `VALIDATION_ERROR`              | 补齐 `chart_id`、`listType`、`fieldId` 等参数          |
| `INVALID_REQUEST`               | 检查图表类型和工具适用范围                             |
| `TIMEOUT`                       | 写动作先重读 context，确认是否已生效，再决定是否重试   |
| `NETWORK_ERROR`                 | 只读或幂等动作可重试，写动作先确认页面状态             |

## 数据集取数约束

如果用户要求查询真实业务数据、比较指标或生成分析结论，先加载并遵循 `ops-dataset-query` Skill。不要自行拼接 `opscli query`，不要猜 `query_*` 参数，不直连数据库。

dashboard bridge tools 负责编辑页面；数据集取数工具负责业务数据分析。组合执行时保持职责分离，先核验页面写入，再基于真实查询结果给出分析结论。
