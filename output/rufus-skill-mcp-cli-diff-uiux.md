# Rufus Skill MCP 与 CLI 差异 UIUX 说明

## 本次 UI 范围

本次任务是后端工具链与 Skill 编排差异审计，不涉及前端页面、组件或视觉交互实现。

## 冻结项

如后续进入 UI 实现阶段，必须重新基于明确需求冻结以下内容：

- 图标库：未启用，本次不使用功能图标。
- 字体系统：未启用，本次无界面文本排版。
- Design token system：未启用，本次无视觉 token。
- 组件生态：未启用，本次不新增 UI 组件。
- 页面骨架：未启用，本次不新增页面。

## Agent 交互体验要求

虽然无 UI，本次差异审计仍影响 Agent 运行体验：

- 最终答复只展示本次工具返回的 `report_path`，不得按 ASIN 读取历史报告。
- 询问远程授权时必须使用 Skill 中固定文案，明确“允许”或“拒绝”。
- CLI fallback 只在 MCP 工具不可用或用户拒绝保存登录态时出现。
- 遇到敏感字段时不展示 cookie、headers、storage_state、seed_request、upload_payload 或 cURL 命令。
- 新增 `platform-cookie get/save` 与 `curl save` 后，Agent 交互必须把它们视为排障/初始化动作，而不是普通 Rufus 获取动作。
- `platform-cookie get` 默认只展示状态和长度；只有用户明确要求排障读取完整 content 时才允许请求完整 content，并且不得把完整 content 写入报告或最终回复。
- `platform-cookie save` 和 `curl save` 成功后只展示保存摘要，不回显原始 content 或 raw cURL。

## 后续 UI 风险

如果未来为 Rufus 构建可视化控制台，不能直接复用 CLI 调试面作为普通用户入口。平台 Cookie content、Copy-as-cURL、手工 Cookie 保存等能力应保留在受限运维区，并默认隐藏敏感内容。

本次用户已要求 MCP 支持平台 Cookie content 与 cURL 保存，因此未来 UI 若呈现这些能力，应采用显式“敏感排障模式”入口、默认隐藏原文和一次性确认提示，不应混入默认获取流程。
