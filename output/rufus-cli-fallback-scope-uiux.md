# Rufus CLI Fallback 限域流程 UIUX

日期：2026-06-10

## 适用范围

本需求没有前端页面改造。这里的 UIUX 指 Agent 与用户之间的交互文本、流程可理解性和报告交付体验。

## 交互原则

1. 默认 MCP 优先，不让用户先理解 CLI。
2. CLI fallback 只在两个白名单场景出现，并明确原因。
3. 授权询问必须用中文，说明保存登录态的边界和风险。
4. 用户拒绝时不再停掉任务，而是说明将改用本机 CLI。
5. 最终回复只展示本次 `report_path`，不混入历史报告。

## 用户可见状态

| 状态 | 用户感知文案方向 |
| --- | --- |
| MCP Tool 不可用 | 当前宿主缺少 Rufus MCP Tool，本次改用本机 opscli CLI 获取 |
| 询问授权 | 是否允许 MCP/headless 保存并复用该站点 Amazon 登录态 |
| 用户允许 | 使用 MCP 登录态检查和 Rufus 获取 |
| 用户拒绝 | 保存拒绝偏好，并改用本机 CLI 获取 |
| 401 或平台 Cookie 鉴权错误 | 按当前规则重新进行 MCP Amazon 登录采集 |
| CLI fallback 成功 | 返回 CLI 本次生成的 `report_path` |
| MCP 成功 | 返回 MCP 本次生成的 `report_path` |
| 非白名单错误 | 返回错误，不建议 CLI fallback |

## 授权询问文案

```text
本次 Rufus 获取需要 Amazon 登录态。是否允许当前 MCP/headless 链路保存并复用该站点的 Amazon 登录状态？

说明：
- 保存的登录态仅供当前 MCP 用户和当前 Agent 隔离凭证使用，不会写入报告或对话回复。
- 登录态相当于已登录会话，请使用独立、干净的 Amazon 账号。
- 不建议在该 Amazon 账号中绑定信用卡或其他支付方式。
- 如果拒绝，本次将改用本机 opscli CLI 获取 Rufus 报告；CLI 仍不会在回复或报告中展示 cookie、localStorage、storage_state、headers、payload 或请求种子。

请明确回复“允许”或“拒绝”。
```

## CLI fallback 文案

### MCP Tool 不可用

```text
当前宿主未暴露 Rufus 必需 MCP Tool，本次按规则回退到本机 opscli CLI。该回退仅适用于 MCP Tool 不可用场景。
```

### 用户拒绝授权

```text
已记录你拒绝 MCP/headless 复用该站点 Amazon 登录态。本次按规则改用本机 opscli CLI 获取 Rufus 报告。
```

### 禁止泛化文案

禁止使用：

```text
MCP 失败，改用 CLI。
```

原因：该文案会暗示任意 MCP 错误都可 fallback，违反本需求第 3 条。

## 错误文案

### 非白名单错误

```text
本次错误不属于允许 CLI fallback 的两类场景，因此不会改用 CLI。错误：<ERROR_CODE>: <message>
```

### 二次恢复失败

```text
本次已按规则执行一次 MCP 登录采集恢复，仍未成功；为避免重复登录循环，不再继续打开登录窗口。错误：<ERROR_CODE>: <message>
```

## 图标、字体和设计 token

本需求不涉及前端 UI 实现。

如果后续需要做可视化流程页或文档站：

- 图标库：Lucide。
- 字体：沿用项目文档站或宿主默认文档字体，不新增 Web Font。
- Token：使用文档站现有颜色和间距 token。
- 页面骨架：左侧目录、右侧正文、流程图嵌入 Mermaid/SVG。
- 禁止使用 emoji 作为功能图标。

## 可用性验收

1. 用户能从文案判断当前是否在 MCP 主路径或 CLI fallback。
2. 用户能明确知道 CLI fallback 只因 MCP Tool 不可用或拒绝授权触发。
3. 用户不会被引导复制 cookie、headers、payload、`storage_state` 或 seed request。
4. 最终回复只出现本次 `report_path`。
