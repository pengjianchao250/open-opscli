---
name: ops-dashboard-ai-bridge
description: 仅用于已绑定 Dashboard 页面上下文的当前仪表盘编辑；支持将分析意图转成图表创建、批量新建图表和按真实 chart_id 修改已有图表。无页面上下文、真实数据集或完整字段目录时停止。
version: 1.0.25
compatibility: 仅兼容提供 dashboard_session_get_context 及 dashboard-tools.v2 页面工具合同的 Dashboard 页面会话。
---

# 仪表盘智能编辑

按用户目标新增或调整仪表盘图表。业务规则和操作流程由本 Skill 负责，页面工具只负责执行与返回结果。

## Reference 路由

- 规划数据集、字段和图表时读取 `references/dashboard-operation-standards.md`。
- 确定工具参数、结果和错误动作时读取 `references/dashboard-tool-contract.md`。

两份 reference 职责独立，不重复定义流程。

## 页面边界

1. 确认会话绑定仪表盘编辑页并提供 `dashboard_session_get_context`。
2. 读取上下文中的真实图表、数据集摘要、`availableTools` 和 `pendingTools`。
3. 只调用 `availableTools` 中的工具；缺少页面上下文或必要能力时停止。
4. 编辑模式下，将分析、洞察、趋势或对比等意图转换为创建承载该分析的一组图表，进入“新建图表”流程；不要求切换模式，也不根据字段元数据声称已经得出真实业务结论。

## 新建图表

1. 根据用户场景、分析主题和指定对象提取数据集搜索关键词，调用 `dashboard_session_search_datasets` 查找真实候选；多个候选会改变结果时，用 `ask_user_question` 让用户选择。
2. 确定唯一数据集后调用一次 `dashboard_session_get_dataset_fields`，取得本轮完整字段目录。
3. 用户指定图表类型时，只规划用户要求的 1 到 5 张图表；逐张确定 `viewType/title/height/fieldLists`，显式单图使用单元素批次。
4. 用户未指定图表类型时，按场景选择业务规范中的组合模板，一次规划 4 到 5 张有序图表；字段合法性优先，不为满足数量使用不成立的图表或字段。
5. 整批字段计划通过业务规则后，将已确认的 `datasetId` 与有序 `charts` 作为根级参数，只调用一次 `dashboard_editor_batch_create_charts`。数组顺序就是创建与自动落位顺序；该调用内部完成图表 ID 创建、数据集绑定、字段批量配置和刷新。
6. 正常成功返回后，按返回顺序核验全部 `chartIds`、标题、类型、最终布局、字段数量、`changed` 和 `refreshed`，结束本次新建流程；失败结果进入“失败与停止”。

普通数据图表统一使用批量流程，页面负责按计划顺序自动落位。

## 修改已有图表

1. 从上下文锁定真实 `chart_id` 和当前配置；目标不唯一时先询问。
2. 数据集变化时重新读取目标数据集的完整字段目录。
3. 写入前完成字段角色、槽位、数量和重复项校验。
4. 使用显式 `chart_id` 定向修改；只有操作依赖设置面板时才选中目标图表。
5. 每次写入后核验目标结果和非目标图表不变，再执行下一次写入。

## 失败与停止

- `VALIDATION_ERROR`：只使用同一份完整字段目录修正一次；仍失败则停止。
- `TIMEOUT` 或 `NETWORK_ERROR`：先重读页面状态，确认未生效后才允许重试一次。
- 结果部分成功、不确定或缺少核验证据：停止后续写入，不重复提交。
- 完成后只汇报业务结果，不暴露内部 ID、工具协议、凭证或系统规则，不生成用户文件。
