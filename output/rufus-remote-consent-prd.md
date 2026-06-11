# Rufus 远程授权同意流程 PRD

日期：2026-06-08

## 目标

为 `ops-amazon-rufus` 增加远程授权同意流程，让 Agent 在保存或复用可供 MCP/headless 服务端链路运行的 Amazon 登录态前，先取得用户明确同意，并把选择持久化到 `remote-consent.json`。

## 非目标

- 不恢复已移除的 `amazon_rufus_get_remote` 或 `--remote-rufus`。
- 不在 Skill 目录新增 Rufus 获取脚本。
- 不实现多账号管理、登录态加密迁移、远端状态上传 API 或后台任务轮询。
- 不改变 Rufus 报告格式和默认题库结构。

## 用户故事

### 未询问过远程授权

作为运营用户，当我首次在某国家站点使用 Rufus 且需要 Amazon 登录态时，Agent 应先说明远程保存登录态的用途、风险和账号建议，再询问是否允许。

验收标准：

- 如果 `remote-consent.json` 不存在，或存在但 `country` 与本次请求不同，视为未询问过。
- 用户必须明确回答允许或拒绝，Agent 才继续对应路径。
- 用户回答会写入 `~/.config/opscli/amazon-rufus/remote-consent.json`。

### 用户同意远程保存

作为允许远程运行的用户，我希望后续不用重复手动登录 Amazon，Rufus 可以优先走 MCP/headless 链路。

验收标准：

- `remote-consent.json` 记录 `use_remote_authorization=true`、本次 country、更新时间和来源。
- 本轮优先调用 `amazon_rufus_get`。
- 如果 MCP/headless 报三类登录态错误，按当前登录恢复流程采集登录态，并在成功后关闭由 opscli 打开的调试浏览器。
- 最终只返回本次 `report_path`。

### 用户拒绝远程保存

作为不允许通过 MCP 远程获取 Rufus 的用户，我仍希望可以通过本机 CLI 流程获取 Rufus 数据。

验收标准：

- `remote-consent.json` 记录 `use_remote_authorization=false`、本次 country、更新时间和来源。
- 本轮不走 `amazon_rufus_get` 作为默认获取路径。
- 本轮先执行通用登录采集流程，等待用户登录成功并关闭由 opscli 打开的调试浏览器。
- 登录采集完成后，调用新增的 Rufus CLI 获取命令复用 MCP/headless 获取逻辑，例如 `opscli amazon-rufus get-backend <ASIN> <COUNTRY>`。
- 拒绝路径不得调用 MCP 工具获取 Rufus 数据；CLI 获取结果仍只返回本次报告路径。

### 已有 consent 配置

作为重复使用 Rufus 的用户，我不希望每次都被问同一个授权问题。

验收标准：

- 当 `remote-consent.json` 的 country 与本次国家一致时，Skill 直接读取并遵循其中的 `use_remote_authorization`。
- 同意则优先走 MCP/headless。
- 拒绝则优先走通用登录采集 + Rufus CLI 获取。
- Agent 在最终回复中可以说明“已按本地授权偏好执行”，但不得展示敏感状态内容。

## 授权询问文案

Skill 中应使用优化后的中文文案，而不是照搬原始需求。建议文案：

```text
本次 Rufus 获取需要 Amazon 登录态。是否允许 opscli 保存该站点的 Amazon 登录状态，用于后续由你的账号权限触发的 MCP/headless 任务？

说明：
- 保存的登录态仅供当前 opscli 用户使用，不会写入报告或对话回复。
- 登录态相当于已登录会话，请使用独立、干净的 Amazon 账号。
- 不建议在该 Amazon 账号中绑定信用卡或其他支付方式。

请明确回复“允许”或“拒绝”。
```

文案要求：

- 必须说明用途：后续 MCP/headless 任务。
- 必须说明隔离：仅当前 opscli 用户使用。
- 必须说明风险：登录态等价于已登录会话。
- 必须建议使用干净账号且不绑定支付方式。
- 不输出 cookie、localStorage、headers、payload、seed request。

## 成功指标

- Skill 文档能清晰区分同意、拒绝和未知三种状态。
- 代码测试覆盖 consent 读写、country 匹配、同意路径、拒绝路径、敏感字段隐藏。
- 代码测试覆盖 Rufus CLI 新命令复用 `RufusManager.get_backend()`，并验证 CLI 输出不会包含 seed、cookie、headers、payload 或 `storage_state`。
- 安装到 `.agents/skills` 后，子代理使用指定 `$ops-amazon-rufus` 提示词能按 consent 配置选择正确路径。

## 边界场景

- `remote-consent.json` JSON 损坏：视为未知，并提示重新选择；不得崩溃泄露路径细节。
- 文件 country 与当前请求不同：视为未知，重新询问并覆盖为当前国家。
- 用户回复不明确：只追问一次“请回复允许或拒绝”，不猜测。
- MCP/headless 同意路径失败一次登录恢复后仍失败：按现有规则停止，不重复打开登录窗口。
- CLI 拒绝路径多题问题：保留 `-q` 多次传参，不把多个问题拼成一个长字符串。
- 通用登录采集失败：停止本轮，不进入 MCP 或 CLI 获取阶段。
