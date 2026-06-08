# amazon-rufus-remote-consent Proposal

## 背景

`ops-amazon-rufus` 当前默认通过 `amazon_rufus_get` MCP 工具调用 `RufusManager.get_backend()` 获取 Rufus。登录态不可用时，Skill 通过 `opscli amazon-rufus logout -> watch-login -> amazon_rufus_get` 进行一次登录恢复。

用户要求新增远程授权同意流程：当国家站点未询问过授权偏好，或 Rufus 需要 Amazon 登录态时，先询问是否允许保存 Amazon 登录状态供后续 MCP/headless 任务使用；选择写入 `remote-consent.json`。如果拒绝，不再调用 MCP 获取 Rufus，而是在完成通用登录采集并关闭浏览器后，通过 Rufus CLI 获取数据。追加要求：发起 Rufus 获取前必须先检查本机是否已有可用 Amazon 登录态；没有可用登录态时先走登录采集流程。

## 范围

1. 新增 `remote-consent.json` 读写服务和 CLI 子命令，用于记录当前国家站点是否允许远程授权。
2. 新增 Rufus CLI 获取命令，复用 MCP 当前的 `RufusManager.get_backend()` 获取逻辑。
3. 新增脱敏登录态检查命令，供 Skill 在获取前判断是否需要执行 `watch-login`。
4. 增强 `watch-login` 支持在采集完成后关闭由 opscli 本次启动的调试浏览器。
5. 更新 `ops-amazon-rufus` Skill、README 和 workflow reference：
   - unknown/invalid consent 时询问用户；
   - 获取前先检查登录态；
   - allowed 时走 MCP `amazon_rufus_get`；
   - denied 时走通用登录采集 + CLI `get-backend`。
6. 安装更新后的 Skill 到 `.agents/skills`，并用指定 `$ops-amazon-rufus` 提示词进行子代理测试。

## 非目标

1. 不恢复 `amazon_rufus_get_remote` 或 `--remote-rufus`。
2. 不在 Skill 目录新增 Rufus 获取脚本。
3. 不把 cookie、localStorage、`storage_state`、headers、payload、seed request 输出到 CLI、MCP、报告或反馈。
4. 不实现远端账号池、多账号管理或 Amazon 信用卡绑定检测。

## 验收标准

1. `remote-consent status/set` 能按国家站点读取和保存 allow/deny/unknown/invalid 状态。
2. `opscli amazon-rufus login-status` 能返回缺失、无效、可用三类脱敏登录态摘要，且不输出敏感字段。
3. `opscli amazon-rufus get-backend` 调用 `RufusManager.get_backend()`，支持默认题库、单题、多题和报告写入。
4. `watch-login --close-browser` 采集成功后关闭 opscli 本次启动的调试浏览器；默认行为保持兼容。
5. Skill 文档清晰约束：发起 Rufus 获取前先检查登录态；没有登录态先登录采集；拒绝授权时不调用 MCP 获取 Rufus，而是登录采集后调用 Rufus CLI。
6. 定向测试、Skill 文档契约测试、MCP schema 回归通过。
