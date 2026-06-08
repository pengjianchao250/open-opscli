# ops-amazon-rufus 明文浏览器状态 UIUX

## 适用范围

本需求没有图形界面改造。UIUX 只覆盖 CLI、MCP、Skill 文案和 Agent 操作提示。

## 文案原则

1. 不再说“本地加密状态”。
2. 改为“本地明文状态（敏感）”或“本地 Rufus 状态文件”。
3. 明确该文件可以复制复用，但泄露风险由用户承担。
4. 不在交互文案中展示 cookie、headers、payload、`storage_state` 或文件内容。

## 推荐用户提示

当 `watch-login` 成功后，Agent 可描述为：

```text
已完成 Amazon 登录态捕获，并保存为本地明文 Rufus 状态文件。该文件包含 cookies/localStorage 和 Rufus 请求上下文，可复制到其他环境复用，请不要提交到仓库或发送给无关人员。
```

当 MCP 获取失败并需要恢复时：

```text
我会先清空当前国家站点的 Rufus 本地状态和 opscli 管理的浏览器 profile，再打开 Amazon 登录页等待重新登录。登录成功后 CLI 会自动打开商品页并重新捕获 Rufus 请求上下文，然后继续调用 amazon_rufus_get。
```

当用户询问是否可复制时：

```text
可以。新版本状态文件是明文 JSON，复制 browser-state-<COUNTRY>.json 到目标环境的 opscli Rufus 配置目录后即可复用。该文件包含 Amazon 登录态，泄露后可能被他人复用。
```

当用户从旧版本升级时：

```text
如果本地仍只有旧版 browser-state-<COUNTRY>.bin 和 .browser-state-key，新版本不会读取或迁移它们。请重新执行 watch-login 或 save-state，生成 browser-state-<COUNTRY>.json 后再使用 Rufus MCP/CLI。
```

## 禁止文案

不得出现：

1. “加密保存，所以复制单个状态文件不可用”。
2. “旧密文会自动迁移，不需要重新捕获”。
3. “请把 cookie 发给我”。
4. “请粘贴 Copy as cURL 内容”。
5. “我会在报告中展示 headers/payload 方便排查”。
6. “明文保存后没有安全风险”。

## CLI/MCP 输出要求

`save-cookie`、`save-curl`、`save-state`、`watch-login` 仍只输出摘要字段：

- `country`
- `asin`
- `saved`
- `cookie_count`
- `origin_count`
- `streaming_request_saved`
- `has_payload_template`

不得新增：

- `state_path`
- `cookies`
- `headers`
- `payload_template`
- `storage_state`
- `curl_data`

理由：即使用户要求明文保存，状态文件路径和内容也不应出现在 Agent 对话、MCP 结果或日志中，避免被外层系统自动收集。

## Skill 文档显示方式

主 `SKILL.md` 只保留短说明：

```text
watch-login 成功后会保存本地明文 Rufus 状态文件（敏感），MCP 后端读取该文件请求 Rufus；Skill 不读取、不展示、不上传其中的 cookie、localStorage、headers、payload 或完整请求。
```

详细风险放在 `references/rufus-mcp-workflow.md`：

```text
本地状态文件是明文 JSON，包含 Amazon cookies/localStorage 和 Rufus streaming 请求上下文。复制该文件可能复制登录态；不要提交到仓库、报告目录或发送给无关人员。旧版 .bin 加密状态不会被新版本读取；请重新捕获生成 .json。
```

## 验收检查

1. Skill 主文档不再出现“本地加密状态”。
2. workflow reference 明确“明文 JSON + 敏感 + 可复制”。
3. workflow reference 明确旧 `.bin` 不再读取或迁移。
4. CLI/MCP 返回不增加敏感字段。
5. 测试中仍断言 result/report 不包含 cookie/token/csrf。
