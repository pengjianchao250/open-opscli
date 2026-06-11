# amazon-rufus-mcp-headless-backend Tasks

## 任务

- [x] 增加 MCP 默认后端/headless 路径测试，证明不再调用 CDP `RufusManager.get()`。
- [x] 增加 `RufusManager` 后端入口测试，覆盖 secret、headless capture、streaming client 的数据流。
- [x] 新增 Rufus secret 模型/provider 与稳定错误。
- [x] 实现 `RufusManager.get_backend()` 或等价入口。
- [x] 将 `amazon_rufus_get` 默认切换到后端/headless 入口。
- [x] 更新 `ops-amazon-rufus` Skill/README/reference 默认流程。
- [x] 运行定向测试并更新 `docs/change-log-pending.md`。

## 验证命令

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run pytest "tests/mcp/test_amazon_rufus_tools.py" "tests/amazon_rufus/test_core.py" "tests/skills/test_ops_amazon_rufus_updater.py" -q
```
