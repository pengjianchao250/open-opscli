# amazon-rufus-per-question-timeout Tasks

## 任务

- [x] 增加 MCP 默认 180 秒超时测试。
- [x] 增加 Manager 默认 180 秒传递到捕获和 streaming 的测试。
- [x] 增加 Headless client 多题逐次使用单题超时的测试。
- [x] 将 Rufus 获取默认超时统一为共享常量 180 秒。
- [x] 更新 Skill reference 和核心架构文档的超时说明。
- [x] 更新 `docs/change-log-pending.md`。
- [x] 运行定向 Rufus/MCP/Skill 回归测试。

## 验证命令

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run pytest "tests/mcp/test_amazon_rufus_tools.py" "tests/amazon_rufus/test_core.py" "tests/skills/test_ops_amazon_rufus_updater.py" -q
```
