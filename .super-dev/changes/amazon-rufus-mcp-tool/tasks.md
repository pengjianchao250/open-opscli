# amazon-rufus-mcp-tool Tasks

## 任务

- [x] 梳理现有 `opscli/amazon_rufus` 服务、命令和测试入口。
- [x] 增加 MCP Rufus 工具注册与授权边界测试。
- [x] 新增 `opscli/mcp/tools/amazon_rufus.py`，暴露 `amazon_rufus_init`、`amazon_rufus_get`、`amazon_rufus_get_remote`。
- [x] 在 `opscli/mcp/server.py` 注册 Rufus MCP 工具。
- [x] 复用现有 Rufus 获取和报告生成逻辑，避免复制 CLI 私有实现。
- [x] 更新 `ops-amazon-rufus` Skill 文档为“题库数据 + MCP 编排规则”。
- [x] 确认 Skill 目录不包含获取 Rufus 的 Python 脚本文件。
- [x] 运行定向测试和相关回归。

## 验证命令

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run pytest "tests/mcp" "tests/amazon_rufus" "tests/skills/test_ops_amazon_rufus_updater.py" -q
```
