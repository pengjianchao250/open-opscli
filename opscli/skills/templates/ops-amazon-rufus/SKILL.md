---
name: ops-amazon-rufus
description: Amazon Rufus 默认题库数据与 Agent 编排入口。用于基于 MCP 工具链对 ASIN 商品页进行 Rufus 问答、Listing 诊断、报告读取、远程授权偏好处理和 headless 后端获取错误恢复。
---

# ops-amazon-rufus

本 Skill 是 Amazon Rufus 默认题库数据包与 Agent 编排入口。Rufus 运行期以 MCP Tool 优先编排，只有明确白名单场景允许 CLI fallback；获取 Rufus 的 Python 工具文件归属 `opscli/mcp/tools/amazon_rufus.py` 和 `opscli/amazon_rufus/`，不得放在本 Skill 目录中。

## 术语约定

1. 面向用户和 Agent 的流程统一称为“亚马逊 Rufus 登录态”，不得把它描述为普通 Cookie。
2. 后端接口和工具名仍保留 `platform-cookie` / OPS 平台 Cookie 命名；其 `content` 实际承载亚马逊 Rufus 登录态，当前规范直接保存浏览器 `/rufus/cl/streaming` cURL 命令态。

## 触发范围

当用户提到 Amazon Listing、listing 商品页、listing 分析或 listing 优化，并且目标是通过 Rufus 对 ASIN 商品页进行问答、诊断、报告或表达风险判断时，使用本 Skill。

如果用户要求基于卖家精灵采集材料、关键词、高频词、PPC/ABA 数据做 Listing 表达与一致性优化，优先使用 `ops-amazon-listing-analysis`，不要用本 Skill 代替。

## 前置条件

1. 确认本 Skill 已安装并完成题库升级。
2. 必需 MCP Tool：`auth_is_authenticated`、`auth_mcp_login`、`auth_check_token`、`auth_token_refresh`、`amazon_rufus_remote_consent_status`、`amazon_rufus_remote_consent_set`、`amazon_rufus_login_status`、`amazon_rufus_watch_login`、`amazon_rufus_logout`、`amazon_rufus_get`。
3. 排障/初始化 MCP Tool：`amazon_rufus_platform_cookie_save`、`amazon_rufus_platform_cookie_get`、`amazon_rufus_curl_save`。这些工具只在用户明确要求排障、迁移或初始化 Rufus 状态时使用，不进入默认获取主流程。
4. 如果必需 MCP Tool 不可见，进入 CLI fallback；这是允许 CLI fallback 的白名单场景之一。
5. 每次获取前必须通过 `amazon_rufus_remote_consent_status(country)` 读取该站点远程授权偏好。不同国家站点授权偏好相互独立，例如 `US` 对应 `amazon.com`，`DE` 对应 `amazon.de`。
6. `remote-consent` 只保存用户是否允许当前 MCP/headless 链路复用亚马逊 Rufus 登录态的偏好，不保存 cookie、localStorage、`storage_state`、headers、payload、cURL 命令或请求种子。
7. 发起 Rufus 获取前必须通过 `amazon_rufus_login_status(country)` 检查亚马逊 Rufus 登录态。如果 `can_get_backend=false`，说明没有可用亚马逊 Rufus 登录态，必须先走 MCP 登录采集。
8. OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 按本 Skill 新规则进入 MCP 登录采集：`amazon_rufus_watch_login(asin, country, close_browser=true)`；本分支不允许 CLI fallback。
9. 获取结果只以本次 `amazon_rufus_get` 或 CLI `get-backend` 返回的 `report_path` 为准。

## 排障/初始化 MCP 工具边界

1. `amazon_rufus_platform_cookie_save(platform, country, content)` 可通过 OPS 平台 Cookie 接口保存亚马逊 Rufus 登录态 content，但成功响应只展示平台、国家、状态和 content 长度，不回显 content。
2. `amazon_rufus_platform_cookie_get(platform, country, include_content=false)` 默认只返回亚马逊 Rufus 登录态摘要、消息、长度和 `has_content`。只有用户明确要求排障读取完整 content 时，才允许传 `include_content=true`。
3. `amazon_rufus_curl_save(asin, country, raw_curl)` 可保存浏览器 cURL 原文状态，但成功响应只展示 ASIN、国家、保存状态、cookie/header 数量和是否存在请求模板摘要，不回显 raw cURL。
4. 上述工具的错误反馈只能记录是否提供敏感参数和字符串长度，不得记录 content、raw cURL、cookie、headers、payload、`storage_state` 或请求种子。
5. 即使 `amazon_rufus_platform_cookie_get(..., include_content=true)` 返回 content，也不得把 content 写入报告、最终回复、feedback 或普通日志。

## CLI fallback 边界

只有以下两种情况允许 CLI fallback：

1. 必需 MCP Tool 不可用。
2. 用户拒绝保存并复用该站点亚马逊 Rufus 登录态。

其他错误不允许 CLI fallback，包括 `RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`RUFUS_HEADLESS_REQUEST_ERROR`、OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401。

CLI fallback 只允许使用正式脱敏入口：

```text
opscli amazon-rufus login-status <COUNTRY> --pretty
opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty
opscli amazon-rufus get-backend <ASIN> <COUNTRY> --skills-dir ".agents/skills"
opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题>"
opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题1>" -q "<问题2>"
```

在本项目内运行时优先使用 `uv run opscli ...` 或 `.venv/Scripts/opscli.exe ...`。

## 主流程

1. 解析用户提供的 ASIN、国家站点和可选 Rufus 问题，并初始化本次 Skill 调用状态：`login_recovery_attempted=false`。
2. 检测必需 MCP Tool 是否可见。不可见时进入 CLI fallback，原因记为 `mcp_tools_unavailable`。
3. 调用 `auth_is_authenticated()`。如果未登录，调用 `auth_mcp_login()`；随后调用 `auth_check_token(system="ops")`，Token 失效时调用 `auth_token_refresh(system="ops")`。
4. 调用 `amazon_rufus_remote_consent_status(country)`，读取该站点的远程授权偏好。
5. 如果状态为 `unknown` 或 `invalid`，先询问用户：

```text
本次 Rufus 获取需要亚马逊 Rufus 登录态。是否允许当前 MCP/headless 链路保存并复用该站点的亚马逊 Rufus 登录状态？

说明：
- 保存的亚马逊 Rufus 登录态仅供当前 MCP 用户和当前 Agent 隔离凭证使用，不会写入报告或对话回复。
- 亚马逊 Rufus 登录态相当于已登录会话，请使用独立、干净的 Amazon 账号。
- 不建议在该 Amazon 账号中绑定信用卡或其他支付方式。
- 如果拒绝，本次将改用本机 opscli CLI 获取 Rufus 报告；CLI 仍不会在回复或报告中展示 cookie、localStorage、storage_state、headers、payload 或请求种子。

请明确回复“允许”或“拒绝”。
```

6. 用户回复“允许”时，调用 `amazon_rufus_remote_consent_set(country, allowed=true)`。
7. 用户回复“拒绝”时，调用 `amazon_rufus_remote_consent_set(country, allowed=false)`，然后进入 CLI fallback，原因记为 `remote_consent_denied`。
8. 状态为 `denied` 时进入 CLI fallback，说明用户拒绝保存并复用该站点亚马逊 Rufus 登录态。
9. 状态为 `allowed` 时，调用 `amazon_rufus_login_status(country)`。
10. 如果 `amazon_rufus_login_status` 返回 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401，调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`，采集后按原问题来源调用 `amazon_rufus_get`；本分支不允许 CLI fallback。
11. 如果 `amazon_rufus_login_status` 返回 `can_get_backend=false` 或 `status=missing/invalid`，调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`。该工具会等待用户完成 Amazon 登录、捕获 `/rufus/cl/streaming` 请求种子，并在采集完成后关闭本次由工具启动的调试浏览器。
12. 登录采集成功后，再次调用 `amazon_rufus_login_status(country)` 确认可用。
13. 调用 `amazon_rufus_get`，由 MCP 后端使用 headless 链路获取 Rufus 回答并写入报告。单题传 `question`，多题传 `questions`，未提供问题时传 `skills_dir=".agents/skills"` 读取默认题库。
14. 如果 `amazon_rufus_get` 返回 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401，调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`，采集后按原问题来源重试 `amazon_rufus_get`；本分支不允许 CLI fallback。
15. 如果 `amazon_rufus_get` 返回 `RUFUS_HEADLESS_REQUEST_ERROR`、`RUFUS_HEADLESS_CAPTURE_ERROR` 或 `RUFUS_SECRET_NOT_READY`，且 `login_recovery_attempted=false`，按 `references/rufus-mcp-workflow.md` 进入一次 MCP 登录采集恢复。
16. 进入恢复后立即记录 `login_recovery_attempted=true`，先调用 `amazon_rufus_logout(country)` 清理旧 Rufus 状态和工具管理的 Chrome profile；成功后再调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`。
17. 恢复采集成功后，按原 ASIN、国家和问题来源重新调用 `amazon_rufus_get`；MCP 服务层从 OPS 平台 Cookie 接口 content 读取亚马逊 Rufus 登录态，该登录态以浏览器 cURL 命令态保存并用于请求 Rufus，不在 MCP 参数、报告或回复中展示 cookie、localStorage、`storage_state`、headers、payload、cURL 命令或完整请求。
18. 如果 OPS 平台 Cookie 接口 content 中的亚马逊 Rufus 登录态只有旧 `curl_data` 或仅 `storage_state`，视为 `invalid`，重新执行 `amazon_rufus_watch_login(asin, country, close_browser=true)`。
19. 如果本次 Skill 调用已经触发过一次登录恢复，或保存后重新调用仍失败，不再打开第二次登录窗口，直接返回错误；其他错误不允许 CLI fallback。
20. 如果成功但 `answer_count=0`，按正常 0 答案报告处理，不推断为登录恢复。
21. 最终回复只展示本次工具返回的 `report_path` 或本次 CLI 返回的 `report_path`；如需正文，只读取本次返回的 `report_path`，不得按 ASIN 读取历史报告。

## CLI fallback 子流程

1. 先执行 `opscli amazon-rufus login-status <COUNTRY> --pretty`。
2. 如果 `can_get_backend=false` 或状态为 `missing/invalid`，执行 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty`。
3. 按原问题来源执行 `opscli amazon-rufus get-backend`：
   - 单题使用 `-q "<问题>"`。
   - 多题重复 `-q`。
   - 未提供问题时传 `--skills-dir ".agents/skills"` 读取默认题库。
4. CLI fallback 成功后只返回本次报告路径，不读取历史报告兜底。
5. CLI fallback 失败时直接返回错误，不再切回 MCP 或继续扩大 fallback。

## References

- `references/rufus-mcp-workflow.md`：Rufus MCP-first 获取、bounded CLI fallback、remote-consent 分流、登录态检查、MCP 登录采集恢复、问题来源选择和 `report_path` 输出规则。
- `references/question-templates.md`：默认题库数据结构、问题模板维护和本地题库文件说明。
- `references/rufus-report-formatting.md`：报告格式化、拒答改写和输出隐藏规则。

## 数据文件

- `data/VERSION.json`：Skill 名称与版本。
- `data/question_templates.json`：合并模板与题目的默认题库；未传临时问题时由 Rufus 获取链路读取。

## 文件边界

本 Skill 目录只承载文档、题库数据和 reference，不承载 Rufus 获取实现。

不得在本 Skill 下新增：

```text
scripts/get_rufus.py
scripts/rufus.py
scripts/headless_rufus.py
```

所有获取 Rufus、读取后端授权材料、请求 Amazon Rufus 的 Python 代码必须位于 `opscli/amazon_rufus/` 或 `opscli/mcp/tools/amazon_rufus.py`。
