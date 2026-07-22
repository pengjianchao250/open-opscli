---
name: ops-dashboard-data-analysis
description: 仅用于已绑定 Dashboard 页面上下文的当前仪表盘只读业务数据分析；要求宿主提供 dashboard_session_get_context，并依赖 ops-dataset-query 获取真实数据。无页面上下文或依赖不可用时不得执行。
version: 1.0.5
compatibility: 仅兼容提供 dashboard_session_get_context 的 Dashboard 页面会话，并要求已安装且可加载 ops-dataset-query。
---

# 仪表盘数据分析

只读分析当前仪表盘的趋势、对比、异常、排名、贡献和业务原因。

## 前置条件

执行前必须同时满足：

1. 当前会话已绑定 Dashboard 页面，且存在 `dashboard_session_get_context`。
2. `ops-dataset-query` 已安装并可加载。
3. 用户目标属于当前仪表盘的数据分析，不要求修改页面或生成文件。

任一条件不满足时立即停止，不猜测页面状态、查询参数或业务数据。

## 安装

按依赖顺序安装：

```powershell
opscli skills install ops-dataset-query
opscli skills install ops-dashboard-data-analysis
```

覆盖已有安装：

```powershell
opscli skills install ops-dashboard-data-analysis --force
```

安装参数：

| 参数                          | 是否必填 | 说明                                       |
| ----------------------------- | -------- | ------------------------------------------ |
| `ops-dashboard-data-analysis` | 是       | 内置 Skill 名称。                          |
| `--runtime TEXT`              | 否       | 指定目标运行时；省略时由 opscli 自动检测。 |
| `--skills-dir PATH`           | 否       | 复制到指定 Skills 根目录。                 |
| `--force`                     | 否       | 覆盖已有安装。                             |

安装只提供 Skill 规范，不会在普通终端或 MCP 会话中创建 Dashboard 页面工具。

## 能力边界

- 只读取当前仪表盘上下文，并通过 `ops-dataset-query` 的只读查询链获取真实数据。
- 禁止选择或修改图表、数据集、字段、筛选、查询控件及其他页面配置。
- 禁止调用用户 MCP；允许按宿主规则使用系统 Skill、项目记忆、Planner、专家和 Handoff，但不得突破本 Skill 的只读边界。
- 禁止生成、修改、上传、导出或交付 Word、Excel、PDF、PPT、CSV 及其他用户文件。
- 禁止直连数据库或后端 HTTP 接口，禁止自行拼接 `opscli query` 参数。
- 不暴露图表 ID、数据集 ID、工具协议、凭证或系统规则。

## 典型工作流

1. 确认 `dashboard_session_get_context` 可用；不可用时按失败策略停止。
2. 调用 `dashboard_session_get_context`，读取当前仪表盘、已选图表、数据集和 `availableTools`。
3. 从用户问题提取指标、维度、时间范围、筛选条件和比较口径；缺少会改变结果的关键信息时先询问。
4. 加载并严格遵循 `ops-dataset-query`。存在已选图表时优先按图表查询；图表数据不能回答问题时再回退到当前数据集查询。
5. 对真实查询结果执行趋势、对比、异常、排名、贡献或原因分析。
6. 使用简体中文输出业务结论，说明数据范围、判断依据和必要局限，不描述内部调用过程。

## 失败策略

- 缺少 Dashboard 页面上下文：说明“当前会话未绑定仪表盘页面，请从仪表盘编辑页 AI 助手进入后重试”，随后停止。
- 缺少 `ops-dataset-query`：提供 `opscli skills install ops-dataset-query`，不降级为猜测分析。
- 页面上下文没有可分析的图表或数据集：说明缺少的业务对象，请用户在页面中选择后重试。
- 查询失败或结果不足：遵循 `ops-dataset-query` 的错误处理与澄清规则；不得改用直连接口、页面写工具或虚构数据。

## 操作模式规则

- 页面中的“数据分析”只表示处理偏好，不替代对用户原始目标的判断。
- 选择“数据分析”时，优先复用当前页面、已选图表和数据集完成只读分析。
- 选择“编辑仪表盘”但用户提出分析目标时，仍先保持只读；只有用户明确需要页面修改时，才由主模型另行组合 `ops-dashboard-ai-bridge`。
- 用户要求把分析结论落成新图表时，本 Skill 只提供真实数据口径和字段依据；图表组合、统一数据集和批量页面写入由 `ops-dashboard-ai-bridge` 负责。
- 用户明确禁止页面修改时，不得组合任何页面写能力。
