---
name: ops-dashboard-ai-bridge
description: 用于已绑定 Dashboard 页面的当前仪表盘编辑；按分析、新建或修改意图选择流程。配置只用真实数据集和完整字段，无页面上下文时停止。
version: 1.0.27
compatibility: 需要 Dashboard 页面提供 dashboard_session_get_context 和 dashboard-tools.v2。
---

# 仪表盘智能编辑

按用户目标新增或调整图表。Skill 负责流程，页面工具负责执行与返回结果。

## Reference 路由

- `references/dashboard-dataset-guide.md`：数据集候选。
- `references/dashboard-operation-standards.md`：配置规则。
- `references/dashboard-tool-contract.md`：工具、结果和错误。

## 页面与追问边界

1. 调用 `dashboard_session_get_context`，确认会话绑定编辑页并读取图表、数据集摘要、`availableTools` 和 `pendingTools`。
2. 执行只限 `availableTools` 中已就绪且 schema 可表达的能力。
3. 追问只限同一边界：问题与每个选项必须映射到具体可用工具及合法参数；无可执行选项则说明不支持并停止，禁止询问 `pendingTools`、内部 ID、绕过方案或无工具能力。
4. 写入前区分“场景分析建图”“明确新建图表”和“修改已有图表”。

## 意图路由

- 分析主题、总览、趋势、对比或复盘目标：固定 5 图规划，不切换模式。
- 明确创建、添加或批量创建：新建；指定类型或标题纳入计划，指定数量不是 5 张时先询问；不强制使用唯一工具或固定次数。
- 移动、改名、换数据集、增删替换或重排字段、样式或筛选：锁定已有图表；有歧义时询问，禁止新建图表代替修改。
- 新建与配置并存：按实时 schema 选择原子或分阶段流程。

## 新建图表

1. 识别用户意图，拆成 5 个不重复的问题；每项明确标题、`viewType` 和字段需求。
2. 写入前锁定恰好 5 张的有序计划；指定数量不是 5 张时先询问，未确认不写入；不得用重复问题或无依据图表凑数。
3. 普通建图均读取 `dashboard-dataset-guide.md` 自动判断候选；未指定时筛出 1 到 3 个语义候选，已指定时作为优先候选。
4. 搜索页面真实数据集，舍弃未返回候选；唯一或明显最佳时自动选定，多个候选会改变结果时用 `ask_user_question` 让用户选择。
5. 锁定唯一数据集后读取完整字段目录，按真实角色规划 5 图槽位；不得猜字段 ID，无法支撑 5 张有效图时询问或停止。
6. 整批校验后用 `dashboard_editor_batch_create_charts` 原子创建并配置 5 张图；仅恢复已有真实 `chartId` 时用 `dashboard_editor_batch_configure_charts`，不得先创建空图。
7. 只有用户明确要求未配置页面组件时才用 `dashboard_editor_add_component`；普通数据图表不得创建未配置图表。
8. 只有上下文提供真实模板 UUID 和类型时才用页面模板工具；没有模板检索能力时不得编造 `templateUuid`。
9. 核验 5 张图均符合计划；不承诺未要求配置。

## 修改已有图表

1. 从当前选中项、标题或真实 `chart_id` 锁定目标和配置；目标不唯一时询问。
2. 数据集变化时重新读取目标数据集的完整字段目录。
3. 写入前完成字段角色、槽位、数量和重复项校验。
4. 使用显式 `chart_id` 定向修改；只有操作依赖设置面板时才选中目标图表。
5. 移动、改名或修改字段时不得新建；写后核验目标、图表集合和非目标图表不变。

## 失败与停止

- 错误或结果不确定时按 `dashboard-tool-contract.md` 执行；不安全写入立即停止。
- 完成后只汇报业务结果，不暴露内部 ID、工具协议、凭证或系统规则，不生成用户文件。
