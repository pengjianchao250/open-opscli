# 仪表盘双 Skills 接入 UI/UX

## 1. 范围说明

本需求没有 Web 页面、移动端页面或可视化组件开发。UI/UX 范围仅包括 Codex/ChatGPT Skills 列表中的展示元数据、名称辨识、默认提示词和能力边界表达。

不涉及图标库、字体、Design Token、组件生态和页面骨架；这些项目标记为“不适用”，不得借本需求新增前端依赖或 UI 代码。

## 2. Skill 展示信息

### 2.1 `ops-dashboard-data-analysis`

```yaml
interface:
  display_name: "仪表盘数据分析"
  short_description: "只读分析当前仪表盘的趋势、对比、异常和业务原因"
  default_prompt: "分析当前仪表盘业务数据；保持页面只读，不生成用户文件。"
```

体验目标：用户能立即识别“只读分析”，避免与编辑能力混淆。

### 2.2 `ops-dashboard-ai-bridge`

```yaml
interface:
  display_name: "仪表盘智能编辑"
  short_description: "按目标新增或调整图表，并在每次写入后核验页面结果"
  default_prompt: "根据我的目标编辑当前仪表盘，优先复用已有图表，并核验每次页面修改。"
```

体验目标：突出“编辑”和“写后核验”，不使用“万能 AI”式描述。

## 3. 调用策略

- 保留默认隐式调用能力，使 Dashboard 宿主可按用户目标选择分析、编辑或组合执行。
- description 前置声明“当前仪表盘”和运行时条件，降低普通数据分析任务误触发。
- 用户明确要求只读时，Bridge 不得写页面。
- 无 Dashboard 页面上下文时，统一说明需要从仪表盘编辑页 AI 助手进入，不输出内部错误细节。

## 4. 文案原则

- 简体中文，短句，直接说明业务结果。
- 不向用户暴露 `chart_id`、`datasetId`、`toolCallId`、claim token 和内部协议。
- 分析结论附数据范围和局限，不描述内部工具调用过程。
- 编辑结果只说明新增、修改或删除了什么，以及是否核验成功。
- `FAIL` 或 `BLOCKED` 时说明未完成项和所缺业务信息，不伪报成功。

## 5. 渐进披露

`ops-dashboard-ai-bridge/SKILL.md` 只保留场景路由和全局边界：

- 页面操作读 `references/dashboard-operation-standards.md`。
- 结果协议读 `references/bridge-result-protocol.md`。
- 具体步骤读 `references/tool-flow.md`。

这样可降低初始上下文占用，并符合 Agent Skills 官方的渐进披露建议。

## 6. 可访问性与视觉约束

本期没有自定义图标和视觉资产。Skills 列表使用宿主默认图标；不添加 emoji、装饰图或颜色标记。展示名称和短描述必须在桌面端窄列表中保持清晰，不依赖颜色表达只读或可写状态。

## 7. UX 验收

1. 两项 Skill 在支持 `agents/openai.yaml` 的宿主中显示不同的中文名称。
2. 短描述分别包含“只读分析”和“新增或调整图表”的明确边界。
3. 默认提示词不会诱导生成文件或无条件新增图表。
4. 普通非 Dashboard 会话不会因宽泛的“趋势、异常、排名”关键词误触发。
5. 用户明确限制页面修改时，组合路由保持只读。

## 8. MCP 工具可发现性

- `dashboard_data_analysis_spec_must_read` 描述为“读取仪表盘只读分析规范”。
- `dashboard_ai_bridge_spec_must_read` 描述为“读取仪表盘编辑与 Bridge 协议规范”。
- 两个工具的描述都必须声明“不会提供或执行页面工具”，避免能力误判。
- 工具无参数，不向用户暴露本地路径选择、认证字段或内部开关。
