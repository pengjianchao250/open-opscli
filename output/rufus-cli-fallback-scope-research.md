# Rufus CLI Fallback 限域流程调研

日期：2026-06-10

## 需求摘要

用户要求调整 `ops-amazon-rufus` Skill 的执行策略：

1. 先检测必需 MCP Tool 是否可用；如果不可用，可以回退使用 CLI。
2. 询问用户是否允许保存并复用该站点 Amazon 登录态；用户拒绝后使用 CLI 爬取。
3. 只有上述两种情况允许 CLI fallback，其他情况不允许回退 CLI。
4. 如果命中 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401，则走 `amazon_rufus_watch_login(asin, country, close_browser=true)` 逻辑。

## 当前仓库现状

当前模板位于：

- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
- `opscli/skills/templates/ops-amazon-rufus/README.md`
- `opscli/skills/templates/ops-amazon-rufus/references/rufus-mcp-workflow.md`
- `.agents/skills/ops-amazon-rufus/` 安装副本

当前规则是 MCP-only：

- 必需 MCP Tool 不可见时停止，不使用 CLI fallback。
- 用户拒绝 remote-consent 时停止，不使用 CLI fallback。
- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或平台 Cookie 401 被归类为 OPS/MCP 鉴权错误，禁止进入 `amazon_rufus_watch_login`。

这与本次需求存在三处明确反向变更。

## 可复用能力

### MCP Tool

当前 `opscli/mcp/tools/amazon_rufus.py` 已暴露：

- `amazon_rufus_remote_consent_status(country)`
- `amazon_rufus_remote_consent_set(country, allowed)`
- `amazon_rufus_login_status(country)`
- `amazon_rufus_watch_login(asin, country, close_browser=true)`
- `amazon_rufus_logout(country)`
- `amazon_rufus_get(asin, country, question/questions/skills_dir)`

这些 Tool 已通过 `RufusMcpManager` 做 MCP-safe 响应，只返回脱敏摘要或 `report_path`。

### CLI 指令

当前 `opscli amazon-rufus` 已有可用 CLI：

- `opscli amazon-rufus login-status <COUNTRY> --pretty`
- `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty`
- `opscli amazon-rufus get-backend <ASIN> <COUNTRY> --skills-dir ".agents/skills"`
- `opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题>"`
- `opscli amazon-rufus logout <COUNTRY> --pretty`
- `opscli amazon-rufus remote-consent status <COUNTRY> --pretty`
- `opscli amazon-rufus remote-consent set <COUNTRY> --allow/--deny --pretty`

根据项目铁律，项目内运行 ops CLI 默认应使用 uv 环境，因此实现文档和测试建议优先使用：

```powershell
uv run opscli amazon-rufus ...
```

或在 Windows 本地回归中使用：

```powershell
.venv/Scripts/opscli.exe amazon-rufus ...
```

## 外部资料背景

Amazon 官方资料说明 Rufus 是购物场景 AI assistant，可回答购物需求、商品和对比问题；该页面同时标注 Rufus 已在 2026-05-13 更名为 Alexa for Shopping。仓库和 Skill 当前仍使用 `Rufus` 命名，因此本次仅记录外部背景，不修改内部模块名。参考：https://www.aboutamazon.com/news/retail/amazon-rufus

MCP 官方文档把 MCP 定位为 AI 应用连接外部工具和系统的开放标准，适合把外部能力稳定暴露给 Agent。参考：https://modelcontextprotocol.io/docs/getting-started/intro

Chrome DevTools Protocol 官方说明 CDP 允许工具检查、调试并控制 Chromium/Chrome。参考：https://developer.chrome.com/devtools/docs/debugger-protocol

Playwright 官方文档说明 BrowserContext 可操作独立浏览器会话，并提供 cookies 等上下文能力；本项目的 `storage_state` 属于认证状态材料，应保持脱敏边界。参考：https://playwright.dev/docs/api/class-browsercontext

这些资料共同支持两个工程约束：

1. MCP/CLI 只是执行入口差异，敏感登录态材料仍必须被隔离和脱敏。
2. CLI fallback 必须有明确触发条件，避免 Agent 在任意错误下绕过 MCP 边界。

## 关键冲突和决策

### 冲突 1：MCP-only 与 CLI fallback

当前文档和测试明确禁止 CLI fallback。本次需求要求新增两个 fallback 例外：

- 必需 MCP Tool 不可用。
- 用户拒绝保存并复用该站点 Amazon 登录态。

决策：把 Skill 规则从 “MCP-only” 改为 “MCP-first with bounded CLI fallback”。

### 冲突 2：拒绝授权后的行为

当前 `denied` 分支停止。本次需求要求拒绝后仍用 CLI 爬取。

决策：拒绝 remote-consent 后保存偏好，然后进入 CLI 登录态检查与 CLI `get-backend` 获取；该分支不得调用 `amazon_rufus_get`。

### 冲突 3：平台 Cookie 401 的恢复路径

当前架构认为平台 Cookie 401 是 OPS/MCP 鉴权错误，不应 `watch_login`。本次需求明确要求命中 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 时走 MCP `amazon_rufus_watch_login`。

决策：按用户需求覆盖原边界。实现时需要同步删除或改写旧测试中的“401 阻止 watch_login”断言。

技术风险：`amazon_rufus_watch_login` 保存状态时仍可能依赖 OPS 平台 Cookie content 写入。如果 401 根因确实是 OPS 鉴权失效，`watch_login` 可能仍失败。Skill 只能按需求触发一次 MCP 登录采集，失败后不得自动转 CLI。

## 影响面

文档与安装副本：

- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
- `opscli/skills/templates/ops-amazon-rufus/README.md`
- `opscli/skills/templates/ops-amazon-rufus/references/rufus-mcp-workflow.md`
- `.agents/skills/ops-amazon-rufus/` 对应文件

安装引导：

- `opscli/skills/commands/cli.py` 中 `_AMAZON_RUFUS_NEXT_STEPS`

测试：

- `tests/skills/test_ops_amazon_rufus_updater.py`
- `tests/skills/test_cli.py`
- 可能需要调整 `tests/amazon_rufus/test_transport.py`、`tests/amazon_rufus/test_core.py` 中描述“401 必须阻止恢复”的注释或断言。

流程图：

- `output/rufus-current-skill-flow.mmd`
- `output/rufus-current-skill-flow.svg`

## 成功标准

1. Skill 文档明确只有两种 CLI fallback：
   - MCP Tool 不可用。
   - 用户拒绝保存并复用 Amazon 登录态。
2. 其他错误，包括普通 headless 错误、secret missing、capture error，不允许 CLI fallback。
3. 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 分支进入 MCP `amazon_rufus_watch_login(asin, country, close_browser=true)`。
4. CLI fallback 只使用脱敏 CLI 入口，不暴露 cookie、headers、payload、`storage_state`、seed request。
5. 最终只返回本次 `report_path`，不读取历史 ASIN 报告兜底。
