---
name: ops-amazon-rufus
description: Amazon Rufus 默认题库数据与 Agent 编排入口。用于基于 MCP 工具链对 ASIN 商品页进行 Rufus 问答、Listing 诊断、报告读取、回答质量判断、问题改写有限重试、远程授权偏好处理和 headless 后端获取错误恢复。
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
9. 同一次 Skill 调用最多触发一次 `watch_login`：MCP `amazon_rufus_watch_login` 和 CLI `opscli amazon-rufus watch-login` 都计入。任何分支准备调用 `amazon_rufus_watch_login` 前必须先检查 `watch_login_attempted=false`，并在调用前立即设置为 `watch_login_attempted=true`。
10. 获取结果只以本次 `amazon_rufus_get` 或 CLI `get-backend` 返回的 `report_path` 为准。
11. Rufus 获取成功后必须执行回答质量判断；无回答、拒答、答非所问或复杂问题退化为商品详情时，按“回答质量判断与问题重写重试”规则改写问题并重新请求 Rufus；多问题获取保持在同一个 Rufus 对话中，每个问题最多 10 次。

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

1. 解析用户提供的 ASIN、国家站点和可选 Rufus 问题，并初始化本次 Skill 调用状态：`login_recovery_attempted=false`、`watch_login_attempted=false`、`answer_rewrite_attempts_by_question={}`。
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
10. 如果 `amazon_rufus_login_status` 返回 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401，且 `watch_login_attempted=false`，先设置 `watch_login_attempted=true`，再调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`，采集后按原问题来源调用 `amazon_rufus_get`；本分支不允许 CLI fallback。
11. 如果 `amazon_rufus_login_status` 返回 `can_get_backend=false` 或 `status=missing/invalid`，且 `watch_login_attempted=false`，先设置 `watch_login_attempted=true`，再调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`。该工具会等待用户完成 Amazon 登录、捕获 `/rufus/cl/streaming` 请求种子，并在采集完成后关闭本次由工具启动的调试浏览器。
12. 登录采集成功后，再次调用 `amazon_rufus_login_status(country)` 确认可用。
13. 调用 `amazon_rufus_get`，由 MCP 后端使用 headless 链路获取 Rufus 回答并写入报告。单题传 `question`，多题传 `questions`，未提供问题时传 `skills_dir=".agents/skills"` 读取默认题库；多问题在同一个 Rufus 对话中获取，不拆成多个独立对话。
14. 如果 `amazon_rufus_get` 返回 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401，且 `watch_login_attempted=false`，先设置 `watch_login_attempted=true`，再调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`，采集后按原问题来源重试 `amazon_rufus_get`；本分支不允许 CLI fallback。
15. 如果 `amazon_rufus_get` 返回 `RUFUS_HEADLESS_REQUEST_ERROR`、`RUFUS_HEADLESS_CAPTURE_ERROR` 或 `RUFUS_SECRET_NOT_READY`，且 `login_recovery_attempted=false`、`watch_login_attempted=false`，按 `references/rufus-mcp-workflow.md` 进入一次 MCP 登录采集恢复。
16. 进入恢复后立即记录 `login_recovery_attempted=true` 和 `watch_login_attempted=true`，先调用 `amazon_rufus_logout(country)` 清理旧 Rufus 状态和工具管理的 Chrome profile；成功后再调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`。
17. 恢复采集成功后，按原 ASIN、国家和问题来源重新调用 `amazon_rufus_get`；MCP 服务层从 OPS 平台 Cookie 接口 content 读取亚马逊 Rufus 登录态，该登录态以浏览器 cURL 命令态保存并用于请求 Rufus，不在 MCP 参数、报告或回复中展示 cookie、localStorage、`storage_state`、headers、payload、cURL 命令或完整请求。
18. 如果 OPS 平台 Cookie 接口 content 中的亚马逊 Rufus 登录态只有旧 `curl_data` 或仅 `storage_state`，视为 `invalid`；仅在 `watch_login_attempted=false` 时设置为 true 并重新执行 `amazon_rufus_watch_login(asin, country, close_browser=true)`。
19. 如果本次 Skill 调用已经触发过一次 `watch_login` 或登录恢复，或保存后重新调用仍失败，不再打开第二次登录窗口，直接返回错误；其他错误不允许 CLI fallback。
20. Rufus 获取成功后，必须读取本次返回的 `report_path` 做回答质量判断；不得读取历史报告参与判断。
21. 如果存在无回答、拒答、答非所问，或用户问题不止商品详情但回答退化为商品详情的情况，进入问题重写重试流程。
22. 问题重写重试必须按问题分别记录 `answer_rewrite_attempts_by_question`，每个问题最多 10 次；达到上限的题目不再交给子 agent。
23. 对未达到上限的不合格题目开启一个子 agent，提示词固定为：`重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。`
24. 拿到新问题后，按改写后的完整问题来源重新调用 `amazon_rufus_get` 或 CLI `get-backend`；不要把多个问题拼成一个长字符串，不要改跑默认题库。
25. 重新请求 Rufus 时仍保持同一个 Rufus 对话的多问题语义：单题继续传 `question`，多题或默认题库重试时传完整 `questions` 列表，只替换本轮改写题目的原位置。
26. 每完成一次 Rufus 重新请求，只增加本轮被改写题目的计数；某题达到 10 次后停止重试该题，其他不合格题目仍可按各自上限继续。
27. 如果仍有题目达到上限后不合格，最终回复只展示最新一次 `report_path` 并说明对应题目已达到回答质量重试上限。
28. 最终回复只展示本次工具返回的 `report_path` 或本次 CLI 返回的 `report_path`；如需正文，只读取本次返回的 `report_path`，不得按 ASIN 读取历史报告。

## watch_login 单次触发规则

1. `watch_login` 是登录态监听和 Rufus streaming 请求种子采集入口；它会打开或连接 Chrome、等待 Amazon 登录完成并捕获 `/rufus/cl/streaming`，不是普通重试动作。
2. `watch_login_attempted` 只存在于当前 Skill 调用内，不写入 Skill 目录、报告、`output/` 或 feedback。
3. 同一次 Skill 调用最多触发一次 `watch_login`；MCP `amazon_rufus_watch_login` 和 CLI `opscli amazon-rufus watch-login` 都计入。
4. 任何分支准备调用 `amazon_rufus_watch_login` 或 CLI `opscli amazon-rufus watch-login` 前，必须先检查 `watch_login_attempted=false`，并在调用前立即设置 `watch_login_attempted=true`。
5. 如果 `watch_login_attempted=true`，不得再次调用 `amazon_rufus_watch_login`，也不得改走 CLI `watch-login` 或先 `amazon_rufus_logout` 后重新登录；直接返回最新错误并说明本次 Skill 调用已触发过登录监听。
6. 回答质量重试不得重置 `watch_login_attempted`；问题改写只影响 Rufus 问题文本，不影响登录采集状态。

## 回答质量判断与问题重写重试

1. 每次 `amazon_rufus_get` 或 CLI `get-backend` 成功后，先读取本次 `report_path`，按原问题逐题判断回答质量；多问题属于同一个 Rufus 对话，不拆分为多个独立判断任务。
2. 以下任一情况视为回答不合格：
   - `answer_count=0`、报告为空、题目下没有实际答案。
   - Rufus 明确拒答、要求重试、表示无法回答或只返回错误性文本。
   - 回答没有覆盖问题意图，例如问题询问差评、风险、评价、适配人群、广告投放、对比或优化建议，但答案只描述商品详情、规格或基础卖点。
   - 多题场景中某一题答案串题、漏题，或回答内容明显属于另一道题。
3. 只把未达到 10 次上限的不合格题目交给子 agent 改写；合格题目保留原文。拿到改写结果后，用改写后的题目替换原位置，形成完整问题列表。
4. 子 agent 提示词必须固定为：

```text
重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。
```

5. 子 agent 只接收待改写问题文本，不接收 cookie、headers、payload、`storage_state`、cURL 命令、请求种子或任何登录态内容。
6. 子 agent 输出必须保持问题数量一致、语义不变、总字数不超过 200；如果输出为空、数量不一致或明显改变语义，本轮不请求 Rufus，先要求子 agent 修正一次。
7. 重新请求时必须保持原 ASIN、国家站点、登录态、同一个 Rufus 对话和问题来源语义。单题继续传 `question`；多题或默认题库重试时传完整 `questions` 列表。
8. 回答质量重试与登录恢复相互独立：重写问题不得触发 `amazon_rufus_logout`，不得扩大 CLI fallback，且不得重置 `login_recovery_attempted` 或 `watch_login_attempted`。
9. `answer_rewrite_attempts_by_question` 按问题分别记录回答质量重试次数，每个问题最多 10 次；某题达到上限后不再开启子 agent 改写该题，也不再为该题单独请求 Rufus。

## CLI fallback 子流程

1. 先执行 `opscli amazon-rufus login-status <COUNTRY> --pretty`。
2. 如果 `can_get_backend=false` 或状态为 `missing/invalid`，且 `watch_login_attempted=false`，先设置 `watch_login_attempted=true`，再执行 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty`；如果 `watch_login_attempted=true`，直接返回错误，不再打开浏览器。
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
