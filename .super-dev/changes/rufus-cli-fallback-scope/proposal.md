# Rufus CLI Fallback 限域流程

## 背景

`ops-amazon-rufus` 当前文档约束为 MCP-only：缺少必需 MCP Tool 时停止，用户拒绝 remote-consent 时停止，平台 Cookie 401 时不进入 `watch_login`。用户新需求要求恢复两个明确 CLI fallback 场景，并调整平台 Cookie 鉴权错误的恢复路径。

## 目标

1. 将 Skill 运行策略调整为 MCP 优先、CLI fallback 限域。
2. 只允许两种 CLI fallback：
   - 必需 MCP Tool 不可用。
   - 用户拒绝保存并复用该站点 Amazon 登录态。
3. 其他错误不得 CLI fallback。
4. `OPS 平台 Cookie 鉴权错误`、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 进入 MCP `amazon_rufus_watch_login(asin, country, close_browser=true)`。
5. 继续保护 cookie、localStorage、`storage_state`、headers、payload、seed request 等敏感材料。

## 非目标

1. 不新增 MCP Tool。
2. 不新增 CLI 命令。
3. 不改 Rufus 底层获取实现。
4. 不提交 git commit 或创建分支。

## 影响范围

- `opscli/skills/templates/ops-amazon-rufus/`
- `.agents/skills/ops-amazon-rufus/`
- `opscli/skills/commands/cli.py`
- `tests/skills/test_ops_amazon_rufus_updater.py`
- `tests/skills/test_cli.py`
- `output/rufus-current-skill-flow.mmd`
- `docs/change-log-pending.md`

## 验收

1. 文档明确两个唯一 CLI fallback 场景。
2. 文档明确 denied 分支走 CLI `login-status -> watch-login -> get-backend`。
3. 文档明确平台 Cookie 鉴权错误和 401 走 MCP `amazon_rufus_watch_login`。
4. 安装后 next_steps 与 Skill 文档一致。
5. 定向测试通过。
