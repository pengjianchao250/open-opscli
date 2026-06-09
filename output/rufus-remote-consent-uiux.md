# Rufus 远程授权同意交互规范

日期：2026-06-08

## 适用范围

本需求没有前端页面。这里的 UIUX 指 Agent 与 CLI 的交互文案、状态反馈和错误恢复体验。

## 交互原则

- 先说明风险，再让用户选择。
- 只问一次授权偏好；后续按 `remote-consent.json` 执行。
- 用户拒绝后仍可完成本机 CLI 获取，不把拒绝变成阻塞。
- 不展示敏感数据，也不要求用户复制 cookie、headers、payload。
- 文案保持专业、简短、可操作。

## Agent 授权询问

当 `remote-consent` 为 unknown 或 invalid，且本轮需要 Amazon 登录态时，使用以下文案：

```text
本次 Rufus 获取需要 Amazon 登录态。是否允许 opscli 保存该站点的 Amazon 登录状态，用于后续由你的账号权限触发的 MCP/headless 任务？

说明：
- 保存的登录态仅供当前 opscli 用户使用，不会写入报告或对话回复。
- 登录态相当于已登录会话，请使用独立、干净的 Amazon 账号。
- 不建议在该 Amazon 账号中绑定信用卡或其他支付方式。

请明确回复“允许”或“拒绝”。
```

允许后的短反馈：

```text
已记录：允许远程授权。接下来将优先使用 MCP/headless 链路；如需重新登录，会打开 Amazon 登录页，采集完成后关闭由 opscli 打开的调试浏览器。
```

拒绝后的短反馈：

```text
已记录：不允许远程授权。接下来将完成本机登录采集并关闭由 opscli 打开的调试浏览器，然后通过 Rufus CLI 获取答案。
```

用户回复不明确时：

```text
请明确回复“允许”或“拒绝”。允许会通过 MCP/headless 获取；拒绝则在完成本机登录采集并关闭浏览器后，通过 Rufus CLI 获取。
```

## CLI 输出规范

`remote-consent status` 只输出安全摘要：

```json
{
  "country": "US",
  "status": "allowed",
  "use_remote_authorization": true,
  "updated_at": "2026-06-08T00:00:00Z"
}
```

禁止输出：

- cookie
- localStorage
- `storage_state`
- headers
- payload
- seed request
- Amazon 账号邮箱或手机号

## 状态映射

| 状态 | Agent 行为 | 用户感知 |
|---|---|---|
| `allowed` | 直接走 MCP/headless | 不重复询问 |
| `denied` | 通用登录采集后走 Rufus CLI | 不重复询问 |
| `unknown` | 询问并保存选择 | 用户做一次明确选择 |
| `invalid` | 告知配置无效并重新询问 | 不暴露 JSON 内容 |

## CLI 拒绝路径体验

拒绝远程授权时，Agent 不应让用户理解底层 seed 或请求结构，只需说明：

```text
正在使用本机流程获取 Rufus 数据。请在打开的 Amazon 窗口完成登录；登录采集成功后，opscli 会关闭由本次流程打开的调试浏览器，并通过 Rufus CLI 生成报告。
```

登录采集完成后的短反馈：

```text
登录采集已完成，正在通过 Rufus CLI 获取答案。本次结果仍以新生成的 report_path 为准。
```

## MCP 同意路径体验

同意远程授权后，Agent 应强调“后续减少重复登录”，但不承诺登录态永久有效：

```text
已按你的授权使用 MCP/headless 链路。本次结果以新生成的 report_path 为准；如果登录态过期，后续会再次进入授权恢复流程。
```

## 安全文案边界

不得使用以下表述：

- “安全保存”作为绝对保证。
- “永久免登录”。
- “服务器可以代表你随时使用账号”。
- “请绑定信用卡以完成账号验证”。

推荐表达：

- “仅供当前 opscli 用户触发的任务使用”。
- “登录态相当于已登录会话”。
- “建议使用独立、干净的 Amazon 账号”。
- “不建议绑定信用卡或其他支付方式”。
