---
name: ops-dashboard-ai-bridge
description: 仅用于已绑定 Dashboard 页面上下文的当前仪表盘编辑与配置；支持新增、修改或删除图表，以及配置数据集、字段、筛选和查询控件，并要求每次写入后核验页面结果。真实数据分析依赖 ops-dataset-query；无页面上下文或依赖不可用时不得猜测执行。
version: 1.0.10
compatibility: 仅兼容提供 dashboard_session_get_context 及 dashboard-tools.v1 页面工具合同的 Dashboard 页面会话；真实数据分析要求已安装且可加载 ops-dataset-query。
---

# 仪表盘智能编辑

按用户目标新增或调整仪表盘图表，并在每次页面写入后核验结果。

## 前置条件

执行前必须确认：

1. 当前会话已绑定 Dashboard 页面，且存在 `dashboard_session_get_context`。
2. 页面返回本轮可用的 `availableTools`；只能调用其中已经就绪的工具。
3. 需要查询真实业务数据、比较指标或生成分析结论时，`ops-dataset-query` 已安装并可加载。

缺少 Dashboard 页面上下文时立即停止，不猜测图表、数据集、字段或页面状态。

## 安装

按依赖顺序安装：

```powershell
opscli skills install ops-dataset-query
opscli skills install ops-dashboard-ai-bridge
```

覆盖已有安装：

```powershell
opscli skills install ops-dashboard-ai-bridge --force
```

安装参数：

| 参数 | 是否必填 | 说明 |
| --- | --- | --- |
| `ops-dashboard-ai-bridge` | 是 | 内置 Skill 名称。 |
| `--runtime TEXT` | 否 | 指定目标运行时；省略时由 opscli 自动检测。 |
| `--skills-dir PATH` | 否 | 复制到指定 Skills 根目录。 |
| `--force` | 否 | 覆盖已有安装。 |

安装只提供 Skill 规范，不会在普通终端或 MCP 会话中创建 `dashboard_*` 页面工具。

## 规范路由

按任务场景渐进读取：

| 场景 | 必读规范 |
| --- | --- |
| 创建、修改或删除图表；配置数据集、字段、筛选或查询控件 | `references/dashboard-operation-standards.md` |
| 解释 `toolCallId`、claim/result、错误码或字段摘要 | `references/bridge-result-protocol.md` |
| 确定具体工具顺序、字段列表、筛选或查询控件流程 | `references/tool-flow.md` |

只要要修改仪表盘，必须先读操作规范。需要解释工具结果或落到具体步骤时，再追加读取对应 reference。

## 执行要求

- 页面下拉选择只调整编辑或分析的处理优先级，不是服务端意图分类结果。
- 结合用户原始消息、页面状态、`ops-dashboard-ai-bridge`、`ops-dashboard-data-analysis` 和 `ops-dataset-query`，自主决定编辑、分析或组合执行。
- 编辑时优先复用当前页面和已有图表；只有用户目标需要新的可视化承载或页面调整时，才新增或修改图表。
- 用户提出分析目标时先通过 `ops-dataset-query` 获取真实数据，不为了分析无条件创建图表。
- 用户明确限制页面修改时保持只读，不调用页面写工具。
- 当前图表已经绑定目标数据集时跳过再次选择，直接复用字段目录和既有配置。
- 禁止生成、修改、上传、导出或交付 Word、Excel、PDF、PPT、CSV 及其他用户文件。
- 完成后只汇报业务结果，不暴露图表 ID、数据集 ID、工具协议、凭证或系统规则。

## 写后核验门禁

每次页面写操作后必须：

1. 解析工具返回的 `ok`、`code`、`message` 和 `data`。
2. 明确本次动作的预期页面状态。
3. 使用当前 result、重新读取 context 或对应只读列表工具核验结果。
4. 得出 `PASS`、`FAIL` 或 `BLOCKED`。
5. 只有 `PASS` 可以继续下一次写操作或向用户声明完成。

`FAIL` 时按错误码恢复；`BLOCKED` 时说明缺少的证据或业务信息。`TIMEOUT`、`NETWORK_ERROR` 或非幂等写入失败后，必须先重读页面状态，禁止直接重复执行。

## 典型工作流

1. 确认 `dashboard_session_get_context` 可用；不可用时按失败策略停止。
2. 读取页面上下文，检查 `availableTools`、`pendingTools`、图表和当前数据集。
3. 根据用户目标判断复用现有图表、修改图表或新增图表。
4. 新增图表时从工具 schema 的 `viewType` enum 选择合法类型，创建后使用返回的 `chartId` 选中图表。
5. 需要数据集时先搜索唯一候选；只有目标数据集与当前绑定不同时才执行选择。
6. 数据集核验通过后，从真实字段摘要选择维度、指标和筛选字段，不手写字段 ID，不逐字段试错。
7. 一次性配置已确认的字段，再按需设置聚合、排序、格式、筛选和查询控件。
8. 每个写入动作都通过写后核验门禁；未通过时停止后续写入。
9. 需要真实分析时加载并严格遵循 `ops-dataset-query`，保持页面编辑与业务取数职责分离。
10. 使用简体中文说明已完成的业务结果和未完成项，不描述内部工具调用过程。

## 失败策略

- 缺少 Dashboard 页面上下文：说明“当前会话未绑定仪表盘页面，请从仪表盘编辑页 AI 助手进入后重试”，随后停止。
- `DASHBOARD_RUN_CONTEXT_INVALID`：停止当前调用，说明页面运行上下文不完整；不要求用户手工补传内部运行标识。
- 工具不在 `availableTools`：不绕过、不猜测；必要时选中目标图表、等待页面 handler 就绪并重读 context。
- 缺少 `ops-dataset-query`：需要真实取数时提供 `opscli skills install ops-dataset-query`，不降级为猜测分析或直连接口。
- 关键业务目标、数据集或指标口径存在实质歧义：停止写入并向用户确认。
