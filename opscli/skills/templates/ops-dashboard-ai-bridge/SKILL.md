---
name: ops-dashboard-ai-bridge
description: 仅用于已绑定 Dashboard 页面上下文的当前仪表盘编辑与配置；支持新增、修改或删除图表，以及配置数据集、字段、筛选和查询控件，并要求每次写入后核验页面结果。真实数据分析依赖 ops-dataset-query；无页面上下文或依赖不可用时不得猜测执行。
version: 1.0.20
compatibility: 仅兼容提供 dashboard_session_get_context 及 dashboard-tools.v2 页面工具合同的 Dashboard 页面会话；真实数据分析要求已安装且可加载 ops-dataset-query。
---

# 仪表盘智能编辑

按用户目标新增或调整仪表盘图表。业务规则和操作流程由本 Skill 负责，页面工具只负责执行与返回结果。

## 能力边界

- 当前会话必须绑定仪表盘编辑页，并提供 `dashboard_session_get_context`；缺少上下文时立即停止。
- 只调用页面返回的 `availableTools`，不猜测图表、数据集、字段或页面状态。
- 页面编辑只读取页面状态、数据集目录和字段元数据。真实数据分析由 `ops-dataset-query` 负责。
- 用户明确要求只读时，不调用页面写工具。
- 禁止生成、修改、上传、导出或交付 Word、Excel、PDF、PPT、CSV 及其他用户文件。

## 规范路由

按任务场景渐进读取：

| 场景                                                   | 必读规范                                      |
| ------------------------------------------------------ | --------------------------------------------- |
| 创建、修改或删除图表；配置数据集、字段、筛选或查询控件 | `references/dashboard-operation-standards.md` |
| 解释 `toolCallId`、claim/result、错误码或字段摘要      | `references/bridge-result-protocol.md`        |
| 确定具体工具顺序、字段列表、筛选或查询控件流程         | `references/tool-flow.md`                     |

只要要修改仪表盘，先读操作规范。需要解释工具结果或落到具体步骤时，再追加读取对应 reference。

## 模式语义

- 页面下拉选择只调整编辑或分析的处理优先级，不替代用户当前消息。
- 编辑偏好下，分析目标通过创建或调整图表完成，不调用 `ops-dataset-query` 获取真实数据。
- 数据分析偏好下，优先通过 `ops-dataset-query` 查询真实数据；只有用户目标需要页面变化时才组合编辑。
- 编辑时优先复用当前图表和数据集，只有现有页面不能承载目标时才新增图表。

## 创建原则

以下六条是所有创建和修改操作的强制规则：

1. 数据集和字段必须真实存在，并来自本轮页面工具返回的目录；禁止猜测或手写 ID。
2. 字段必须属于本轮选定的数据集；不得复用其他数据集、历史轮次或其他图表返回的字段 ID。
3. 维度、度量与图表槽位必须兼容：`dimensions` 只进入维度槽位，`metrics` 只进入度量槽位；双角色槽位才允许两者。
4. 画布固定 12 列，不询问或接受其他列数；默认组合只固定宽度 `w`，`x/y` 由模型结合当前画布和本轮全部图表决定。最终每张图必须满足 `x >= 0`、`w > 0`、`x + w <= 12`、`y >= 0`、`h > 0`，且同一画布内矩形不得重叠。
5. 批量创建必须原子、幂等并可回滚：写入前完成整批校验；任一图表失败时不得保留部分结果；结果不确定时先重读页面状态，确认未生效后才能重试同一计划。
6. `chart_id` 定向修改不能误改其他图表：已知目标图表时必须直接传 `chart_id`，不得把选择其他图表作为前置步骤，也不得改变非目标图表的标题、样式、位置、数据集或字段。

## 创建流程

1. 调用 `dashboard_session_get_context` 读取当前页面、图表和 `availableTools`。
2. 调用 `dashboard_session_search_datasets` 获取真实数据集；候选不唯一且会改变结果时，用 `ask_user_question` 展示 2 到 4 个真实候选。
3. 选定唯一数据集后调用 `dashboard_session_get_dataset_fields`，保存本轮 `datasetId`、`dimensions` 和 `metrics`，后续只使用这份字段目录。
4. 在任何写入前一次性规划全部图表的 `viewType/title/layout/fieldLists`，逐项检查六条强制规则；模型结合当前画布决定期望 `x/y`，但调用时只能提交工具 schema 实际声明的布局字段。批量创建 schema 若只接受 `w/h`，不得附加 `x/y`；先按 `w/h` 创建并核验页面实际落位，需要调整时再调用移动工具。禁止先创建空图再试字段。
5. 用户未指定类型时按业务语义选择默认组合；括号内明确标注默认宽度 `w` 和建议高度 `h`，`x/y` 不固定：
   - 营销/转化：`indicator(w=4,h=16)`、`pie_circle(w=8,h=16)`、`combo_bar_line(w=12,h=30)`、`hbar_basic(w=12,h=30)`、`detail_table(w=12,h=30)`。
   - 供应链：`metric_trend(w=4,h=20)`、`hbar_basic(w=8,h=20)`、`bar_stacked(w=12,h=30)`、`detail_table(w=12,h=30)`。
   - 无法唯一判断组合时询问用户，不自行删减或替换图表。
6. 指标卡只配置 1 个度量，环形图只配置 1 个类别维度和 1 个度量；其余图表按页面工具 schema 的字段槽位规则配置。默认宽度不要求固定排序、固定行或固定坐标。
7. 通过一个 `dashboard_editor_batch_create_charts` 请求提交唯一 `datasetId` 和完整 `charts` 计划；不得拆成逐图创建、逐图选数据集或逐字段试写。
8. 核验返回的图表数量、`viewType/title/layout/fieldLists`、`changed/refreshed`；任一项失败或部分成功时按返回结果或重读上下文确认回滚，不继续追加写入。

## 定向修改流程

1. 从本轮上下文或工具结果取得真实 `chart_id`，并读取该图表当前状态。
2. 标题、局部样式、位置分别直接调用 `dashboard_drag_set_chart_title`、`dashboard_drag_patch_chart_style`、`dashboard_drag_move_chart`，请求中必须传目标 `chart_id`。
3. 修改数据集或字段时同样传目标 `chart_id`；字段必须重新按目标数据集的本轮字段目录校验，禁止沿用其他图表字段。
4. 写后核验返回的 `chartId` 等于目标 `chart_id`，目标状态符合预期，并确认原选中图表及其他图表未被误改。

完成后只汇报业务结果，不暴露内部 ID、工具协议、凭证或系统规则。

## 失败策略

- 缺少 Dashboard 页面上下文：说明“当前会话未绑定仪表盘页面，请从仪表盘编辑页 AI 助手进入后重试”，随后停止。
- `DASHBOARD_RUN_CONTEXT_INVALID`：停止当前调用，说明页面运行上下文不完整；不要求用户手工补传内部运行标识。
- 工具不在 `availableTools`：不绕过、不猜测；按上下文等待页面能力就绪或停止。
- 缺少 `ops-dataset-query`：需要真实取数时说明依赖不可用，不降级为猜测分析或直连接口。
- 关键业务目标、数据集或指标口径存在实质歧义：停止写入并向用户确认。
- `TIMEOUT`、`NETWORK_ERROR` 或非幂等写入失败：先重读页面状态确认是否已经生效，禁止直接重复写入。
