# amazon-rufus-mcp-only-flow tasks

## 1. MCP 工具补齐

- [x] 在 `opscli/mcp/tools/amazon_rufus.py` 新增 remote-consent store 工厂。
- [x] 新增 `amazon_rufus_remote_consent_status`。
- [x] 新增 `amazon_rufus_remote_consent_set`。
- [x] 新增 `amazon_rufus_login_status`。
- [x] 新增 `amazon_rufus_watch_login`。
- [x] 新增 `amazon_rufus_logout`。
- [x] 将新增工具注册到 `_ALL_TOOLS`。
- [x] 确认各工具输出不包含敏感字段。

## 2. Skill 文档改写

- [x] 更新 `opscli/skills/templates/ops-amazon-rufus/SKILL.md`。
- [x] 更新 `opscli/skills/templates/ops-amazon-rufus/README.md`。
- [x] 更新 `opscli/skills/templates/ops-amazon-rufus/references/rufus-mcp-workflow.md`。
- [x] 同步 `.agents/skills/ops-amazon-rufus/` 对应文件。
- [x] 删除拒绝远程授权后的 CLI fallback。
- [x] 删除 MCP 工具不可见时改用 CLI 的提示。

## 3. 安装引导调整

- [x] 更新 `opscli/skills/commands/cli.py` 中 `ops-amazon-rufus` 安装后 next_steps。
- [x] 引导内容只出现 MCP 工具链。

## 4. 测试更新

- [x] 更新 `tests/mcp/test_amazon_rufus_tools.py`。
- [x] 更新 `tests/skills/test_ops_amazon_rufus_updater.py`。
- [x] 更新 `tests/skills/test_cli.py`。
- [x] 验证新增工具 schema 和脱敏响应。

## 5. 验证和记录

- [x] 运行 `uv run pytest tests/mcp/test_amazon_rufus_tools.py -q`。
- [x] 运行 `uv run pytest tests/skills/test_ops_amazon_rufus_updater.py -q`。
- [x] 运行 `uv run pytest tests/skills/test_cli.py -q`。
- [x] 追加 `docs/change-log-pending.md`。
