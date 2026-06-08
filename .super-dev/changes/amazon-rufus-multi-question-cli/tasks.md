# amazon-rufus multi question CLI tasks

## 任务

- [x] 为 Manager 多题模式新增失败测试，验证跳过题库并保序。
- [x] 为 CLI 多次 `-q/--question` 新增失败测试。
- [x] 为 MCP `questions` 参数新增失败测试。
- [x] 实现 Manager `questions` 参数与统一问题解析。
- [x] 实现 CLI `-q` 和可重复 `--question`。
- [x] 实现 MCP `questions` 参数透传。
- [x] 同步 `ops-amazon-rufus` Skill/README 问题来源说明。
- [x] 追加 `docs/change-log-pending.md` 变更记录。
- [x] 运行定向测试验证。

## 验证命令

```powershell
uv run pytest "tests/amazon_rufus/test_core.py" -k "multi_question or passes_question or remote_rufus_calls or login_required_accepts_remote_flow" -q
uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q
```
