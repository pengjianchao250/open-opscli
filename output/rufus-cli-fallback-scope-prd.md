# Rufus CLI Fallback 限域流程 PRD

日期：2026-06-10

## 背景

当前 `ops-amazon-rufus` Skill 已完成 MCP-only 改造，但实际使用中存在两类可恢复场景：

1. 宿主没有暴露必需 Rufus MCP Tool，但本机 `opscli amazon-rufus` 能力可用。
2. 用户拒绝允许 MCP/headless 链路保存并复用 Amazon 登录态，但仍希望通过本机 CLI 完成一次 Rufus 爬取。

本需求要求保留 MCP 主路径，同时为上述两类场景提供 CLI fallback，并严格禁止其他错误随意回退 CLI。

## 目标

1. 将 Skill 运行策略调整为 “MCP-first with bounded CLI fallback”。
2. 在 Skill 文档中明确 CLI fallback 的两个唯一触发条件。
3. 在拒绝 remote-consent 后使用 CLI 获取 Rufus 报告。
4. 在平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 时，进入 MCP `amazon_rufus_watch_login(asin, country, close_browser=true)`。
5. 保持敏感字段不进入对话、报告、feedback 或 MCP/CLI 成功输出。

## 非目标

1. 不新增 MCP Tool。
2. 不新增 CLI 命令。
3. 不允许通过 CLI 参数传递 cookie、headers、payload、`storage_state` 或 seed request。
4. 不改变 Rufus 默认题库数据结构。
5. 不改平台 Cookie API 三字段契约。
6. 不实现异步 job/polling。

## 用户故事

### 场景 1：MCP Tool 不可用

作为 Agent，当当前宿主没有暴露 Rufus 必需 MCP Tool 时，我需要能回退到 CLI `opscli amazon-rufus`，以便用户仍能完成 Rufus 报告。

验收：

- 在进入 Rufus 主流程前检查必需 MCP Tool。
- 缺少任意必需 Tool 时，不尝试部分 MCP。
- 使用 CLI `login-status -> watch-login -> get-backend` 流程。
- 只返回本次 CLI 生成的报告路径。

### 场景 2：用户拒绝保存并复用登录态

作为用户，当我拒绝 MCP/headless 链路保存并复用 Amazon 登录态时，我仍希望使用本机 CLI 完成 Rufus 爬取。

验收：

- 用户拒绝后调用 `amazon_rufus_remote_consent_set(country, allowed=false)` 或 CLI 对应 `remote-consent set --deny` 保存偏好。
- 拒绝分支不调用 `amazon_rufus_get`。
- 使用 CLI `login-status -> watch-login -> get-backend`。
- CLI 获取仍不得输出敏感字段。

### 场景 3：平台 Cookie 鉴权错误

作为 Agent，当 Rufus 链路返回 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 时，我需要按新规则进入 MCP 登录采集。

验收：

- 调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`。
- 保留原 ASIN、国家和问题来源。
- 采集成功后按原问题来源重试 `amazon_rufus_get`。
- 本分支不得回退 CLI。

## 业务规则

### Fallback 白名单

CLI fallback 只允许两种情况：

1. 必需 MCP Tool 不可用。
2. 用户明确拒绝保存并复用该站点 Amazon 登录态。

除此之外，任何错误都不允许回退 CLI。

### CLI fallback 指令

默认题库：

```powershell
uv run opscli amazon-rufus get-backend <ASIN> <COUNTRY> --skills-dir ".agents/skills"
```

单题：

```powershell
uv run opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题>"
```

多题：

```powershell
uv run opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题1>" -q "<问题2>"
```

获取前检查：

```powershell
uv run opscli amazon-rufus login-status <COUNTRY> --pretty
```

登录采集：

```powershell
uv run opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty
```

### 错误处理

| 错误或状态 | 处理 | 是否 CLI fallback |
| --- | --- | --- |
| 缺少必需 MCP Tool | CLI `login-status/watch-login/get-backend` | 是 |
| remote-consent denied | CLI `login-status/watch-login/get-backend` | 是 |
| `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` | MCP `amazon_rufus_watch_login` | 否 |
| HTTP 401 | MCP `amazon_rufus_watch_login` | 否 |
| `RUFUS_SECRET_NOT_READY` | MCP 一次恢复，仍失败则报错 | 否 |
| `RUFUS_HEADLESS_CAPTURE_ERROR` | MCP 一次恢复，仍失败则报错 | 否 |
| `RUFUS_HEADLESS_REQUEST_ERROR` | MCP 一次恢复，仍失败则报错 | 否 |
| 其他错误 | 直接报错 | 否 |

## 文案要求

授权询问文案需要调整：

```text
本次 Rufus 获取需要 Amazon 登录态。是否允许当前 MCP/headless 链路保存并复用该站点的 Amazon 登录状态？

说明：
- 保存的登录态仅供当前 MCP 用户和当前 Agent 隔离凭证使用，不会写入报告或对话回复。
- 登录态相当于已登录会话，请使用独立、干净的 Amazon 账号。
- 不建议在该 Amazon 账号中绑定信用卡或其他支付方式。
- 如果拒绝，本次将改用本机 opscli CLI 获取 Rufus 报告；CLI 仍不会在回复或报告中展示 cookie、localStorage、storage_state、headers、payload 或请求种子。

请明确回复“允许”或“拒绝”。
```

## 验收标准

1. 模板 Skill 和 `.agents` 副本均体现 bounded CLI fallback。
2. README、reference 和安装后 `next_steps` 规则一致。
3. 流程图同步更新。
4. 文档契约测试覆盖：
   - 允许缺少 MCP Tool 时 CLI fallback。
   - 允许 denied 后 CLI fallback。
   - 禁止其他错误 CLI fallback。
   - 平台 Cookie 鉴权错误进入 MCP `amazon_rufus_watch_login`。
5. 定向测试通过：

```powershell
.venv/Scripts/python.exe -m pytest "tests/skills/test_ops_amazon_rufus_updater.py" "tests/skills/test_cli.py" "tests/mcp/test_amazon_rufus_tools.py" -q
```
