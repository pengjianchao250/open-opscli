# Tasks

## 1. 契约测试

- [x] 更新 `tests/skills/test_ops_amazon_rufus_updater.py`，把旧 MCP-only 断言改为 bounded CLI fallback 断言。
- [x] 更新 `tests/skills/test_cli.py`，覆盖安装后引导中的两个 CLI fallback 场景。
- [x] 运行定向测试，确认新测试在旧实现下失败。

## 2. Skill 文档

- [x] 更新模板 `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md`。
- [x] 同步更新 `.agents/skills/ops-amazon-rufus/` 安装副本。
- [x] 保持敏感字段禁止输出规则。

## 3. 安装引导

- [x] 更新 `opscli/skills/commands/cli.py` 中 `_AMAZON_RUFUS_NEXT_STEPS`。
- [x] 保持终端输出 GBK 安全，不使用 emoji。

## 4. 流程图和记录

- [x] 更新 `output/rufus-current-skill-flow.mmd`。
- [x] 渲染 `output/rufus-current-skill-flow.svg`。
- [x] 追加 `docs/change-log-pending.md`。

## 5. 验证

- [x] `.venv/Scripts/python.exe -m pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q`
- [x] `.venv/Scripts/python.exe -m pytest "tests/skills/test_cli.py" -q`
- [x] `.venv/Scripts/python.exe -m pytest "tests/mcp/test_amazon_rufus_tools.py" -q`
