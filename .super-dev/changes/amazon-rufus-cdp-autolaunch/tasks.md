# amazon-rufus CDP 自动启动任务

## 任务清单

- [x] 补充 BrowserAttachService 的 CDP 自动启动 RED 测试。
- [x] 补充 CLI `--launch-if-needed` / `--chrome-path` 透传 RED 测试。
- [x] 补充 MCP `launch_if_needed` / `chrome_path` 透传 RED 测试。
- [x] 实现 CDP 探测、Chrome 路径发现和 Python 启动逻辑。
- [x] 将 Manager、CLI、MCP 参数接入真实调用链。
- [x] 更新 `ops-amazon-rufus` Skill/README 的 CDP 处理规则。
- [x] 追加 `docs/change-log-pending.md` 变更记录。
- [x] 运行定向测试和 Rufus 相关回归测试。

## 验证命令

```powershell
uv run pytest "tests/amazon_rufus/test_core.py" -k "cdp or launch_if_needed or chrome_path" -q
uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q
uv run pytest "tests/amazon_rufus/test_core.py" -q
uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q
```
