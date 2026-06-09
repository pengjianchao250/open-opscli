# amazon-rufus-login-state-loop Tasks

- [x] 1. 写失败测试
  - [x] 1.1 为 `RufusManager.save_state()` 写测试：fake browser 返回 storage_state，fake store 记录保存参数。
  - [x] 1.2 为 CLI `save-state` 写测试：输出成功摘要且不泄露敏感字段。
  - [x] 1.3 为 CLI `init --help` 写测试：包含 `--chrome-path`。
  - [x] 1.4 为安装后指引写测试：包含 `save-state` 且不推荐 `--new-chrome`。

- [x] 2. 实现登录态保存
  - [x] 2.1 `BrowserAttachService` 新增 `capture_storage_state()`。
  - [x] 2.2 `RufusManager` 新增 `save_state()`。
  - [x] 2.3 CLI 新增 `save-state` 命令。
  - [x] 2.4 CLI `init` 暴露 `--chrome-path` 与 `--launch-if-needed`。

- [x] 3. 同步文档和指引
  - [x] 3.1 更新安装后 next_steps。
  - [x] 3.2 更新模板 Skill `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md`。
  - [x] 3.3 同步 `.agents/skills/ops-amazon-rufus` 副本。
  - [x] 3.4 追加 `docs/change-log-pending.md`。

- [x] 4. 验证
  - [x] 4.1 运行 Rufus 定向测试。
  - [x] 4.2 检查敏感字段没有进入 CLI 成功输出和 Skill 文档示例。
