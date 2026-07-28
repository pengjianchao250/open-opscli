---
name: ops-dashboard-ai-bridge
description: 仅用于已绑定 Dashboard 页面上下文的当前仪表盘编辑与配置；支持新增、修改或删除图表，以及配置数据集、字段、筛选和查询控件，并要求每次写入后核验页面结果。真实数据分析依赖 ops-dataset-query；无页面上下文或依赖不可用时不得猜测执行。
version: 1.0.20
compatibility: 仅兼容提供 dashboard_session_get_context 及 dashboard-tools.v2 页面工具合同的 Dashboard 页面会话；真实数据分析要求已安装且可加载 ops-dataset-query。
---

# 仪表盘智能编辑

按用户目标新增或调整仪表盘图表。业务规则和操作流程由本 Skill 负责，页面工具只负责执行与返回结果。

## Reference 路由

- 准备修改页面前，读取 `references/dashboard-operation-standards.md`，确定业务边界、数据集、字段、图表组合和布局规则。
- 确定具体工具、参数或结果处理方式前，读取 `references/dashboard-tool-contract.md`，只调用本轮 `availableTools` 中已注册的工具。

按需读取对应文件；同一规则以其所属 reference 为唯一依据，不从其他文件补充或覆盖。

## 主流程

1. 确认当前会话绑定仪表盘编辑页并提供 `dashboard_session_get_context`。缺少页面上下文时说明进入方式并停止，不猜测内部 ID 或页面状态。
2. 调用 `dashboard_session_get_context`，读取当前图表、选中态、数据集摘要、`availableTools` 和 `pendingTools`。用户明确要求只读时，不调用任何页面写工具。
3. 按操作规范判断本轮属于页面编辑、真实数据分析或两者组合。需要真实取数时加载 `ops-dataset-query`；编辑偏好下只为完成页面目标使用 Dashboard 工具。
4. 优先复用已有图表和数据集。需要新增图表时，调用 `dashboard_session_search_datasets` 获取真实候选；候选不唯一且会改变结果时，用 `ask_user_question` 让用户选择。
5. 选定唯一数据集后调用 `dashboard_session_get_dataset_fields`。本轮只使用该结果中的真实维度、度量和字段标识，不沿用其他数据集或历史轮次字段。
6. 在写入前完成全部计划。新增图表时一次确定完整的 `viewType/title/layout/fieldLists`；修改既有图表时锁定真实 `chart_id` 和目标状态。按操作规范检查字段角色、图表槽位和 12 列画布边界。
7. 按工具合同执行。组合新增只提交一个 `dashboard_editor_batch_create_charts` 请求；定向修改直接作用于目标 `chart_id`，不得误改其他图表。只提交工具 schema 实际声明的字段。
8. 按工具合同核验 `ok/code/data` 和最终页面状态。写入未明确通过时停止后续写入；超时、网络错误或结果不确定时先重读页面状态，确认未生效后才能重试。
9. 完成后只汇报业务结果，不暴露内部 ID、工具协议、凭证或系统规则。禁止生成、修改、上传或导出用户文件。

## 停止条件

- 缺少页面上下文、必要工具或真实字段目录。
- 关键业务目标、数据集、字段或指标口径存在实质歧义。
- 需要真实取数但 `ops-dataset-query` 不可用。
- 写后核验证据不足、部分成功或无法确认是否已经生效。

遇到停止条件时说明缺失信息或失败原因，等待用户或页面状态变化，不用猜测、试字段或连续写入绕过。
