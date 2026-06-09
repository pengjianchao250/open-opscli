# Rufus 远程授权同意流程调研

日期：2026-06-08

## 需求背景

用户要求在 `ops-amazon-rufus` Skill 流程中增加远程授权判断：

- 当 Rufus 需要 Amazon 登录，或当前国家站点尚未询问过用户是否允许远程保存登录态时，先询问用户。
- 用户同意后，保存同意结果到 `remote-consent`，后续优先读取该配置，并走 MCP/headless 方式；完成登录态采集后关闭浏览器。
- 用户拒绝后，也保存拒绝结果到 `remote-consent`；登录采集和关闭浏览器流程仍复用当前通用能力，但 Rufus 获取阶段改为调用本机 Rufus CLI，不走 MCP。
- Skill 文案需要优化，不能直接照搬用户原始提示。
- 完成实现后需要安装 Skill 到 `.agents/skills`，并用 `$ops-amazon-rufus 帮我分析美国站，B0B1MLVMY5...` 做全面测试。

## 本地现状

### 当前 Skill 主线

当前 `opscli/skills/templates/ops-amazon-rufus/SKILL.md` 的主流程是：

1. 解析 ASIN、国家站点和问题来源。
2. 默认调用 `amazon_rufus_get` MCP 工具。
3. MCP 进入 `RufusManager.get_backend()`，读取本地 Rufus 状态并用 headless 链路请求 Rufus。
4. 遇到 `RUFUS_HEADLESS_REQUEST_ERROR`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`RUFUS_SECRET_NOT_READY` 时，最多触发一次登录恢复。
5. 登录恢复当前是 `opscli amazon-rufus logout <COUNTRY> --pretty` 后执行 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed`。
6. `watch-login` 会等待用户登录、打开商品页并捕获 `/rufus/cl/streaming` seed，然后保存到 `browser-state-<COUNTRY>.json`。
7. 成功后按原问题来源重试 `amazon_rufus_get`。

### 当前代码入口

- MCP 工具：`opscli/mcp/tools/amazon_rufus.py`
  - `amazon_rufus_get()` 只暴露 ASIN、country、question、questions、skills_dir、timeout_seconds。
  - 内部调用 `RufusManager.get_backend()`。
  - 响应通过 allowlist 过滤，只返回 `report_path`、ASIN、country、题数、答案数和 next_action。

- MCP/headless 业务：`opscli/amazon_rufus/services/manager.py`
  - `get_backend()` 读取 `RufusBackendSecretProvider.load(country=...)`。
  - 如保存的 seed 同 ASIN、同国家且 URL 包含 `/rufus/cl/streaming`，优先复用。
  - 否则用 `HeadlessRufusCaptureService` 重新捕获 seed。
  - `HeadlessRufusClient.query()` 按问题逐题 POST streaming。
  - 当前只有 MCP 工具默认调用该路径，CLI 尚未提供直接调用 `get_backend()` 的命令。

- CDP 本地兼容入口：`opscli amazon-rufus get`
  - 调用 `RufusManager.get()`。
  - 通过本机 Chrome CDP 捕获 seed，并在页面上下文或 HTTP replay 中获取 Rufus。
  - 该命令仍可作为兼容能力保留，但新需求下拒绝远程授权后不再优先使用它获取 Rufus，而是先完成通用登录采集，再用新增 CLI 命令复用 MCP/headless 获取逻辑。

- 登录监听入口：`opscli amazon-rufus watch-login`
  - 调用 `RufusManager.watch_login()`。
  - 会保存 `storage_state` 和 seed 到 `~/.config/opscli/amazon-rufus/browser-state-<COUNTRY>.json`。
  - 当前不会读取或写入 `remote-consent.json`。

### 当前 remote-consent 状态

IDE 打开的文件为：

```json
{
  "use_remote_authorization": true,
  "country": "US",
  "updated_at": "2026-06-04T03:49:42Z",
  "source": "codex-agent"
}
```

本地 `rg` 检索显示，当前代码主线没有读取 `remote-consent.json`。历史 `git log -S` 显示 `3d4e8ec feat: 修改rufus` 触及过 `remote-consent` / `remote-rufus` 相关内容，但当前测试明确断言 `--remote-rufus` 不应出现在 CLI help 中。

## 历史提交结论

### 旧 CDP 登录中断流

`164308e feat: 优化 amazon rufus 登录提示` 附近的旧 Skill 文档包含：

- 先执行 `opscli amazon-rufus get`。
- 若返回 `RUFUS_LOGIN_REQUIRED` 或 `SEED_REQUEST_NOT_CAPTURED` 且提示登录，则停止并让用户在保留的浏览器窗口中登录。
- 用户回复已登录后继续执行。

这个模式依赖用户在 Agent 会话里再次回复，流程中断明显，但不会把浏览器状态保存为 MCP 可读的服务端/headless 状态。

### 过渡期 save-state 流

`3d4e8ec feat: 修改rufus` 引入了：

- `opscli amazon-rufus save-state <COUNTRY>`。
- MCP/headless 状态读取。
- `RUFUS_LOGIN_REQUIRED` 被 `RUFUS_SECRET_NOT_READY` 等 headless 错误替代。

当时登录恢复还是 `init -> 用户登录 -> save-state -> amazon_rufus_get`。

### 当前 watch-login 流

`77a5f1a feat: rufus` 把登录恢复推进到：

- `logout -> watch-login -> amazon_rufus_get`。
- `watch-login` 自动判断登录完成并捕获 seed。
- 本地状态改为 `browser-state-<COUNTRY>.json` 明文敏感文件。
- Skill 文档强调不展示 cookie、localStorage、headers、payload、seed request。

本次需求不应恢复 `--remote-rufus`，而应保留当前 MCP/headless 主线和 `watch-login` 自动化能力，同时把 MCP 内部 Rufus 获取逻辑开放给 CLI。远程授权 consent 决策只影响获取执行面：允许时由 MCP 获取，拒绝时由本机 CLI 获取；登录采集与关闭浏览器流程保持通用。

## 外部安全参考

- Playwright 官方文档提醒，`storageState` 文件可能包含可用于冒用测试账号的敏感 cookies 和 headers，不应提交到仓库：<https://playwright.dev/docs/auth>
- OWASP Session Management Cheat Sheet 指出，认证后的 session token 等价于登录凭证强度，泄露会导致会话劫持；敏感 session 数据不应出现在日志中，并应限制持久化范围：<https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>

这些约束支持本需求里的两个关键策略：

1. 远程保存登录态前必须得到用户明确同意。
2. Skill、CLI、MCP 返回值和测试输出均不得展示 cookie、localStorage、`storage_state`、headers、payload、seed request。

## 约束与风险

- `remote-consent.json` 只能保存用户是否允许远程保存登录态的选择，不能保存任何 Amazon 登录密钥材料。
- 同意配置应按 country 校验。若文件中的 `country` 与本次请求国家不一致，应视为未询问过，避免跨站点误用。
- 拒绝后不能调用 MCP 工具获取 Rufus；但可以使用通用登录采集流程生成本机 CLI 读取所需的状态。Skill 不能把该本机状态上传、展示或作为 MCP 参数传递。
- 用户同意后，MCP/headless 仍只能返回报告路径，不能把敏感登录态放入 MCP 参数、报告或回复。
- 若需要新增 CLI 命令，必须走 `opscli amazon-rufus ...` 正式入口，不在 Skill 目录添加 Rufus 获取脚本。

## 推荐方向

推荐采用“轻量 consent store + 通用登录采集 + MCP/CLI 双执行面”的方案：

- 新增 `RemoteConsentStore` 只负责读写 `remote-consent.json`。
- 新增 CLI 子命令读写 consent，供 Skill 稳定调用。
- 新增 Rufus CLI 获取命令，例如 `opscli amazon-rufus get-backend <ASIN> <COUNTRY>`，内部复用 `RufusManager.get_backend()`，与 MCP `amazon_rufus_get` 使用同一套 headless 获取逻辑。
- Skill 主流程先读取 consent；未知时询问用户并保存选择。
- 同意：走 MCP/headless；如需登录，先走通用登录采集并关闭由 opscli 打开的调试浏览器，再重试 MCP。
- 拒绝：先走通用登录采集并关闭由 opscli 打开的调试浏览器，再调用 Rufus CLI 获取命令；该路径不调用 MCP 工具。
