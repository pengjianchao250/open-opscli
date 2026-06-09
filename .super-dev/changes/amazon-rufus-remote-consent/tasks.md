# amazon-rufus-remote-consent Tasks

## 任务

- [x] RED：为 `RemoteConsentStore` 写缺失、country 不匹配、格式无效、allow/deny 写入的失败测试。
- [x] RED：为 `remote-consent status/set` CLI 写失败测试，验证输出只包含安全摘要。
- [x] RED：为 `get-backend` CLI 写失败测试，验证调用 `RufusManager.get_backend()` 而不是 CDP `get()`。
- [x] RED：为 `watch-login --close-browser` 写失败测试，验证参数透传和关闭浏览器行为。
- [x] GREEN：实现 `RemoteConsentStore` 与 CLI 子命令。
- [x] GREEN：实现 `opscli amazon-rufus get-backend`。
- [x] GREEN：实现 `watch-login --close-browser`。
- [x] 更新 `ops-amazon-rufus` Skill、README、`rufus-mcp-workflow.md` 和安装后提示文案。
- [x] 更新 `docs/change-log-pending.md`。
- [x] 运行定向测试、Rufus core 回归、MCP 工具回归和 Skill 文档契约测试。
- [x] 执行 `opscli skills install ops-amazon-rufus --skills-dir ".agents/skills" --force`。
- [x] 开启子代理，用指定 `$ops-amazon-rufus` 提示词测试 allowed/denied 两类配置。

## 追加需求：获取前登录态检查

- [x] RED：为 `RufusManager.login_status()` 写缺失、无效、可用状态测试。
- [x] RED：为 `opscli amazon-rufus login-status` 写 CLI 安全输出测试。
- [x] RED：更新 Skill 文档契约测试，要求 Rufus 获取前先执行 `login-status`，无可用登录态再执行 `watch-login --close-browser`。
- [x] GREEN：实现 `RufusManager.login_status()` 与 CLI `login-status`。
- [x] GREEN：更新 `ops-amazon-rufus` Skill、README、`rufus-mcp-workflow.md` 和安装后提示文案。
- [x] 更新 `docs/change-log-pending.md`。
- [x] 重新安装 `ops-amazon-rufus` 到 `.agents/skills`。
- [x] 运行 Rufus core、MCP、Skill 文档和 Skill CLI 回归。
- [x] 开启子代理验证 allowed/denied 路径都会先执行 `login-status`，且已有登录态时跳过 `watch-login`。

## 验证命令

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; .venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" "tests/mcp/test_amazon_rufus_tools.py" "tests/skills/test_ops_amazon_rufus_updater.py" -q
opscli skills install ops-amazon-rufus --skills-dir ".agents/skills" --force
```
