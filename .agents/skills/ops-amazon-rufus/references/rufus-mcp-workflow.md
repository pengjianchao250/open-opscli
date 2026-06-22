# Rufus MCP-first 获取流程

## 适用范围

本文描述 `ops-amazon-rufus` 的 MCP-first 获取规则，包括 MCP 鉴权、bounded CLI fallback、remote-consent 授权偏好、登录态检查、Amazon 登录采集、Rufus 获取、错误恢复和报告路径输出。

题库维护见 `references/question-templates.md`。报告格式与拒答改写见 `references/rufus-report-formatting.md`。

## 术语约定

面向用户和 Agent 的流程统一称为“亚马逊 Rufus 登录态”，不要把它描述为普通 Cookie。后端接口和工具名仍保留 `platform-cookie` / OPS 平台 Cookie 命名；其 `content` 实际承载亚马逊 Rufus 登录态，当前规范直接保存浏览器 `/rufus/cl/streaming` cURL 命令态。

## MCP 工具

| 工具 | 用途 |
|------|------|
| `auth_is_authenticated` | 检查当前 MCP 会话是否已登录 |
| `auth_mcp_login` | 当前 MCP 会话未登录时完成一步登录 |
| `auth_check_token` | 检查指定系统 JWT 有效期 |
| `auth_token_refresh` | 刷新指定系统 JWT |
| `amazon_rufus_remote_consent_status` | 读取国家站点远程授权偏好 |
| `amazon_rufus_remote_consent_set` | 保存允许或拒绝远程授权偏好 |
| `amazon_rufus_login_status` | 读取 Rufus 获取前的亚马逊 Rufus 登录态脱敏摘要 |
| `amazon_rufus_watch_login` | 打开或连接 Chrome，等待用户登录并保存亚马逊 Rufus 登录态和 Rufus streaming 请求种子 |
| `amazon_rufus_logout` | 清理已保存 Rufus 状态和工具管理的 Chrome profile |
| `amazon_rufus_get` | 使用 MCP 后端 headless 链路获取 Rufus 回答并写入报告 |
| `amazon_rufus_platform_cookie_save` | 排障/初始化时通过 OPS 平台 Cookie 接口保存亚马逊 Rufus 登录态 content，响应不回显 content |
| `amazon_rufus_platform_cookie_get` | 排障/初始化时读取 OPS 平台 Cookie 接口 content 摘要，默认不返回 content |
| `amazon_rufus_curl_save` | 排障/初始化时保存浏览器 cURL 原文状态，响应不回显 raw cURL |

Rufus 主路径优先使用 auth 与 `amazon_rufus_remote_consent_*`、`amazon_rufus_login_status`、`amazon_rufus_watch_login`、`amazon_rufus_logout`、`amazon_rufus_get`。`amazon_rufus_platform_cookie_save`、`amazon_rufus_platform_cookie_get`、`amazon_rufus_curl_save` 只在用户明确要求排障、迁移或初始化 Rufus 状态时使用。

## 排障/初始化 MCP 工具

保存亚马逊 Rufus 登录态到 OPS 平台 Cookie 接口 content：

```text
amazon_rufus_platform_cookie_save(platform="amazon", country="US", content="<streaming-curl>")
```

成功响应只展示 `platform`、`country`、`status`、`message`、`content_length`，不得回显 content。

读取 OPS 平台 Cookie 接口 content 摘要：

```text
amazon_rufus_platform_cookie_get(platform="amazon", country="US")
```

默认只返回 `platform`、`country`、`status`、`message`、`content_length`、`has_content`。只有用户明确要求排障读取完整 content 时，才允许：

```text
amazon_rufus_platform_cookie_get(platform="amazon", country="US", include_content=true)
```

即使返回完整 content，也不得写入报告、最终回复、feedback 或普通日志。

保存浏览器 cURL 原文状态：

```text
amazon_rufus_curl_save(asin="B0TEST1234", country="US", raw_curl="<browser-curl>")
```

成功响应只展示国家、ASIN、保存状态、cookie/header 数量和请求模板摘要标记，不得回显 raw cURL、cookie、headers、payload、`storage_state` 或请求种子。

## CLI fallback 白名单

只有以下两种情况允许 CLI fallback：

1. 必需 MCP Tool 不可用。
2. 用户拒绝保存并复用该站点亚马逊 Rufus 登录态。

其他错误不允许 CLI fallback。

CLI fallback 只允许使用以下脱敏入口：

```text
opscli amazon-rufus login-status <COUNTRY> --pretty
opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty
opscli amazon-rufus get-backend <ASIN> <COUNTRY> --skills-dir ".agents/skills"
opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题>"
opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题1>" -q "<问题2>"
```

在本项目内运行时优先使用 `uv run opscli ...` 或 `.venv/Scripts/opscli.exe ...`。

## 获取前规则

1. 先确认 ASIN、国家站点和用户问题。
2. 检查必需 MCP Tool。缺少任一必需工具时，进入 CLI fallback，原因是 `mcp_tools_unavailable`。
3. 调用 `auth_is_authenticated()` 检查 MCP 会话。
4. 未登录时调用 `auth_mcp_login()`；随后调用 `auth_check_token(system="ops")`。
5. Token 失效时调用 `auth_token_refresh(system="ops")`；刷新失败再调用 `auth_mcp_login()`，仍失败则停止。
6. 调用 `amazon_rufus_remote_consent_status(country)`，读取该站点远程授权偏好。
7. 状态为 `unknown` 或 `invalid` 时，必须先询问用户是否允许保存该站点亚马逊 Rufus 登录状态。用户明确回复后，用 `amazon_rufus_remote_consent_set(country, allowed=true)` 或 `amazon_rufus_remote_consent_set(country, allowed=false)` 保存偏好。
8. 状态为 `denied` 时进入 CLI fallback，原因是用户拒绝保存并复用该站点亚马逊 Rufus 登录态。
9. 状态为 `allowed` 时，调用 `amazon_rufus_login_status(country)`。
10. 如果 `amazon_rufus_login_status` 返回 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401，且 `watch_login_attempted=false`，设置 `watch_login_attempted=true` 后调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`；本分支不允许 CLI fallback。
11. 如果 `can_get_backend=false` 或 `status=missing/invalid`，说明没有可用亚马逊 Rufus 登录态；仅当 `watch_login_attempted=false` 时，设置 `watch_login_attempted=true` 并调用 `amazon_rufus_watch_login(asin, country, close_browser=true)` 完成登录采集并关闭本次由工具启动的调试浏览器。
12. 登录采集成功后，再次调用 `amazon_rufus_login_status(country)` 确认可用。
13. 调用 `amazon_rufus_get` 获取 Rufus 回答。
14. 每次 Skill 调用开始时记录 `login_recovery_attempted=false`，用于限制本轮最多触发一次登录恢复。
15. 每次 Skill 调用开始时记录 `watch_login_attempted=false`，用于限制同一次 Skill 调用最多触发一次 `watch_login`。
16. 每次 Skill 调用开始时记录 `answer_rewrite_attempts_by_question={}`，用于按问题分别限制回答质量重试；每个问题最多 10 次。

## 远程授权偏好

读取授权偏好：

```text
amazon_rufus_remote_consent_status(country="US")
```

当返回 `unknown` 或 `invalid` 时，使用以下询问文案：

```text
本次 Rufus 获取需要亚马逊 Rufus 登录态。是否允许当前 MCP/headless 链路保存并复用该站点的亚马逊 Rufus 登录状态？

说明：
- 保存的亚马逊 Rufus 登录态仅供当前 MCP 用户和当前 Agent 隔离凭证使用，不会写入报告或对话回复。
- 亚马逊 Rufus 登录态相当于已登录会话，请使用独立、干净的 Amazon 账号。
- 不建议在该 Amazon 账号中绑定信用卡或其他支付方式。
- 如果拒绝，本次将改用本机 opscli CLI 获取 Rufus 报告；CLI 仍不会在回复或报告中展示 cookie、localStorage、storage_state、headers、payload 或请求种子。

请明确回复“允许”或“拒绝”。
```

保存允许：

```text
amazon_rufus_remote_consent_set(country="US", allowed=true)
```

保存拒绝：

```text
amazon_rufus_remote_consent_set(country="US", allowed=false)
```

`remote-consent` 只保存授权偏好，不保存亚马逊 Rufus 登录态、cookie、localStorage、`storage_state`、headers、payload 或请求种子。HTTP/SSE MCP 模式下，该偏好按当前 API Key + Agent 名称隔离。

## 获取前亚马逊 Rufus 登录态检查

发起 Rufus 获取前，必须先检查 OPS 平台 Cookie 接口 content 中是否已有可用亚马逊 Rufus 登录态：

```text
amazon_rufus_login_status(country="US")
```

判断规则：

- `can_get_backend=true`：已有可用于 Rufus 后端/headless 获取的亚马逊 Rufus 登录态，继续调用 `amazon_rufus_get`。
- `can_get_backend=false` 或 `status=missing/invalid`：没有可用亚马逊 Rufus 登录态，且 `watch_login_attempted=false` 时先执行 MCP 登录采集。
- OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401：且 `watch_login_attempted=false` 时执行 `amazon_rufus_watch_login(asin, country, close_browser=true)`；本分支不允许 CLI fallback。

`amazon_rufus_login_status` 只输出 `status`、`has_login_state`、`can_get_backend`、`session_cookie_count`、`has_streaming_request` 等脱敏摘要。不要让 Agent 读取或展示 OPS 平台 Cookie 接口 content 原文。

`can_get_backend=true` 只表示 OPS 平台 Cookie 接口 content 内的亚马逊 Rufus 登录态存在可解析的浏览器 cURL 命令态。旧 `curl_data` 或仅 `storage_state` 的 content 不再作为可用后端凭证，遇到 `status=invalid` 时仅在 `watch_login_attempted=false` 时重新执行 `amazon_rufus_watch_login(asin, country, close_browser=true)`。

## watch_login 单次触发约束

`watch_login` 是监听亚马逊 Rufus 登录态并捕获 Rufus streaming 请求种子的阻塞入口，不是通用重试动作。同一次 Skill 调用最多触发一次 `watch_login`；MCP `amazon_rufus_watch_login` 和 CLI `opscli amazon-rufus watch-login` 都计入。

本状态只存在于当前 Skill 调用内：

```text
watch_login_attempted=false
```

任何分支准备调用 `amazon_rufus_watch_login` 或 CLI `opscli amazon-rufus watch-login` 前，必须先检查 `watch_login_attempted=false`，并在调用前立即设置：

```text
watch_login_attempted=true
```

如果 `watch_login_attempted=true`，不得再次调用 `amazon_rufus_watch_login`，不得改走 CLI `watch-login`，也不得先 `amazon_rufus_logout` 后重新登录；直接返回最新错误并说明本次 Skill 调用已触发过登录监听。该状态不得写入 Skill 目录、报告、`output/` 或 feedback。

## 超时预算

`amazon_rufus_get` 默认 `timeout_seconds=180`。该值是内部 Rufus 获取的单题预算：headless 捕获使用该值，每个 Rufus streaming 请求也单独使用该值；多题模式会逐题请求，内部总等待上限约随问题数累加。

同步 MCP Router 或调用宿主可能存在约 60 秒外层请求上限。内部每题 180 秒不能覆盖外层截断；如果宿主提前返回超时，应保留已确认的问题来源，等待后续异步 job/polling 能力，不要把 `timeout_seconds` 继续调大当作根因修复。

## 问题来源选择

当用户已经给出一个明确 Rufus 问题时，优先使用单题模式：

```text
amazon_rufus_get(asin="B0TEST1234", country="US", question="这个商品适合送礼吗？")
```

当用户已经给出多个明确 Rufus 问题时，使用多题临时问题模式：

```text
amazon_rufus_get(
  asin="B0TEST1234",
  country="US",
  questions=["这个商品适合送礼吗？", "差评主要集中在哪些方面？"]
)
```

多题临时问题在同一个 Rufus 对话中获取，不拆成多个独立对话；回答质量重试也必须保留这一批问题的完整上下文。

当用户只提供 ASIN 和国家，或要求“默认报告”“完整分析”“跑题库”时，使用默认题库模式：

```text
amazon_rufus_get(asin="B0TEST1234", country="US", skills_dir=".agents/skills")
```

临时问题模式传入后会跳过默认题库。不要把多个问题拼成一个长字符串，也不要为了多个临时问题改用默认题库。

CLI fallback 中必须保持相同问题来源：单题传一次 `-q`，多题重复 `-q`，默认题库传 `--skills-dir ".agents/skills"`。

## 回答质量判断与问题重写重试

每次 `amazon_rufus_get` 或 CLI `get-backend` 成功后，Agent 必须读取本次 `report_path` 做回答质量判断。本判断只使用本次报告，不读取历史 ASIN 报告，不使用 IDE 打开的旧文件。多问题获取属于同一个 Rufus 对话，判断和重试都按题目逐项处理，但重新请求时保持完整问题列表。

### 不合格判断

以下任一情况视为回答不合格，需要改写问题并重新请求 Rufus：

1. `answer_count=0`、报告为空、题目下没有实际答案。
2. Rufus 明确拒答、提示重试、表示无法回答，或只返回错误性文本。
3. 回答没有覆盖问题意图。例如问题询问差评、风险、评价、适配人群、广告投放、对比、场景判断或优化建议，但答案只描述商品详情、规格参数或基础卖点。
4. 多题场景中某一题答案串题、漏题，或回答内容明显属于另一道题。

成功但 `answer_count=0` 不再按正常 0 答案报告直接结束；必须进入本节的回答质量判断与问题重写重试流程。

### 子 agent 改写规则

1. 只把未达到 10 次上限的不合格题目交给子 agent 改写，合格题目保留原文。
2. 开启一个子 agent，并使用固定提示词：

```text
重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。
```

3. 子 agent 只接收待改写问题文本，不接收 cookie、headers、payload、`storage_state`、cURL 命令、请求种子、OPS 平台 Cookie 接口 content 或亚马逊 Rufus 登录态。
4. 子 agent 输出必须保持问题数量一致、语义不变、总字数不超过 200。若输出为空、数量不一致或明显改变语义，本轮不请求 Rufus，先要求子 agent 修正一次；仍不合格时停止回答质量重试。

### 重新请求规则

1. 将改写后的题目替换回原位置，形成完整问题列表。
2. 按改写后的完整问题来源重新调用 `amazon_rufus_get` 或 CLI `get-backend`。
3. 单题继续传 `question`；多题或默认题库重试时传完整 `questions` 列表，继续在同一个 Rufus 对话语义下处理本批问题。
4. 不得把多个问题拼成一个长字符串，不得因为重试改跑默认题库。
5. 保持原 ASIN、国家站点和已取得的亚马逊 Rufus 登录态，不得因为问题改写触发 `amazon_rufus_logout`。
6. `answer_rewrite_attempts_by_question` 按问题分别记录次数；每完成一次 Rufus 重新请求，只增加本轮被改写题目的计数，每个问题最多 10 次。
7. 回答质量重试与登录恢复相互独立，不得重置 `login_recovery_attempted` 或 `watch_login_attempted`，不得扩大 CLI fallback 范围。
8. 某题达到 10 次后仍不合格时停止重试该题，其他不合格题目仍可按各自上限继续；最终回复只展示最新一次 `report_path` 并说明对应题目已达到回答质量重试上限。

## MCP 登录采集入口

当亚马逊 Rufus 登录态缺失、平台 Cookie 鉴权错误、401，或 allowed 路径中的 MCP 默认链路返回三类登录态相关错误时，使用 MCP 登录采集入口。进入该入口前必须确认 `watch_login_attempted=false`，并在调用前设置为 `watch_login_attempted=true`。

监听登录页并把亚马逊 Rufus 登录态保存到 OPS 平台 Cookie 接口 content：

```text
amazon_rufus_watch_login(asin="B0TEST1234", country="US", close_browser=true)
```

如果自动发现 Chrome 失败，再询问用户 Chrome 可执行文件路径，并传入 `chrome_path`：

```text
amazon_rufus_watch_login(
  asin="B0TEST1234",
  country="US",
  close_browser=true,
  chrome_path="C:/Program Files/Google/Chrome/Application/chrome.exe"
)
```

`amazon_rufus_watch_login` 是阻塞工具：它会打开 Amazon 页面供用户登录，工具内部持续监听页面登录状态和 `/rufus/cl/streaming` 请求。用户无需在 Agent 会话中额外回复“已登录”；工具捕获成功后会自动把 `/rufus/cl/streaming` 浏览器 cURL 命令态直接保存为 OPS 平台 Cookie 接口 content。

旧 `browser-state-<COUNTRY>.bin`、`browser-state-<COUNTRY>.json` 和 `.browser-state-key` 不再作为默认读写源；如只有本地旧状态，需要重新执行 MCP 登录采集写入 OPS 平台 Cookie 接口 content。

登录完成判定满足任一条件即可：

1. 读取 `#nav-tools` 容器文本，未出现 i18n 未登录提示。
2. 目标站点 Cookie name 存在 `sso-state-main` 或 `at-main`。

未登录提示词应覆盖当前支持站点和常见页面语言，包括 `sign in`、`signin`、`log in`、`login`、`identifícate`、`identificate`、`identificarse`、`iniciar sesión`、`登录`、`登入`、`サインイン`、`ログイン`、`anmelden`、`einloggen`、`connexion`、`se connecter`。`Hola`、`Hello`、`Hallo` 等问候词本身不能作为未登录提示。

MCP 后端只从 OPS 平台 Cookie 接口 content 中读取浏览器 cURL 命令态，并在服务层内部解析请求种子；Skill 不读取、不展示、不记录其中的敏感字段。

`amazon_rufus_watch_login` 只输出保存摘要，例如国家、ASIN、是否保存、是否检测到登录、cookie 数量、origin 数量、是否保存 streaming request。不要展示完整状态、cookie、localStorage、headers、payload、seed request、cURL 命令、完整请求或 upload payload。

保存完成后，重新按原问题来源调用 `amazon_rufus_get`。

## 三类 MCP 错误的登录采集恢复

以下错误在 allowed 路径中仅当 `login_recovery_attempted=false` 且 `watch_login_attempted=false` 时进入一次登录采集恢复：

```text
RUFUS_HEADLESS_REQUEST_ERROR
RUFUS_HEADLESS_CAPTURE_ERROR
RUFUS_SECRET_NOT_READY
```

OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 也只在 `watch_login_attempted=false` 时进入 `amazon_rufus_watch_login(asin, country, close_browser=true)`，但本分支不允许 CLI fallback，也不执行 `amazon_rufus_logout` 预清理。

`RUFUS_HEADLESS_REQUEST_ERROR` 的 message 可能是 `Rufus 请求失败: 403`。此时不要把 403 当作 MCP 服务不可用，也不要直接重复调用 `amazon_rufus_get`；按授权或页面上下文失效处理，进入一次登录采集恢复。

### 恢复状态

本状态只存在于当前 Skill 调用内：

```text
login_recovery_attempted=false
watch_login_attempted=false
```

首次进入登录采集恢复时立即设置：

```text
login_recovery_attempted=true
watch_login_attempted=true
```

该状态不得写入 Skill 目录、报告、`output/` 或 feedback。它只用于防止同一次 Skill 调用无限打开登录窗口。

### 恢复步骤

1. 保留原始 ASIN、国家站点、`question`、`questions` 和 `skills_dir`；仅当 `watch_login_attempted=false` 时继续恢复。
2. 先清理旧 Rufus 登录态：

```text
amazon_rufus_logout(country="US")
```

3. 成功后再执行登录页监听和 streaming seed 捕获：

```text
amazon_rufus_watch_login(asin="B0TEST1234", country="US", close_browser=true)
```

4. 登录采集工具会阻塞等待用户在打开的目标国家站点 Amazon 窗口完成登录，并自动打开目标 ASIN 商品页监听页面请求。
5. 捕获 `/rufus/cl/streaming` 后，工具自动把浏览器 cURL 命令态直接保存到 OPS 平台 Cookie 接口 content。
6. 登录采集成功后，按原问题来源重新调用 `amazon_rufus_get`；MCP 后端从保存的 cURL 命令态解析请求种子并请求 Rufus。

### 二次失败处理

如果登录采集恢复后仍返回任意错误、再次命中上述三类错误，或 `watch_login_attempted=true` 后又进入任意登录采集分支，不再触发第二次登录。建议提示：

```text
本次 Skill 调用已触发过一次 watch_login / MCP 登录采集恢复，仍未成功；为避免重复登录循环，不再打开第二次登录窗口。错误：<ERROR_CODE>: <message>
```

不要把多个问题拼成一个长字符串，不要在恢复路径改跑默认题库，不要输出 cookie、localStorage、`storage_state`、headers、seed request 或 upload payload。

## CLI fallback 子流程

CLI fallback 只由 `mcp_tools_unavailable` 或 `remote_consent_denied` 触发。

1. 检查登录态：

```text
opscli amazon-rufus login-status <COUNTRY> --pretty
```

2. 如果 `can_get_backend=false` 或状态为 `missing/invalid`，且 `watch_login_attempted=false`，设置 `watch_login_attempted=true` 后执行登录采集；如果 `watch_login_attempted=true`，直接返回错误，不再打开浏览器：

```text
opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty
```

3. 获取 Rufus 报告：

```text
opscli amazon-rufus get-backend <ASIN> <COUNTRY> --skills-dir ".agents/skills"
opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题>"
opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题1>" -q "<问题2>"
```

CLI fallback 不读取、不展示、不记录 cookie、localStorage、`storage_state`、headers、payload、seed request 或 upload payload。CLI fallback 失败时直接返回错误，不切回 MCP，也不扩大 fallback 范围。

## 输出要求

MCP 工具或 CLI 获取成功时返回 `report_path`。完整答案报告写入运行目录下的 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。

### 报告新鲜度约束

最终回复用户时只展示本次 `report_path`。如需正文，只读取本次工具返回的 `report_path` 指向的 Markdown 文件。

禁止仅凭 ASIN 在 `output/amazon-rufus/` 中读取任意 `<ASIN>-*.md` 历史报告，也不要使用 IDE 当前打开文件或上一轮对话遗留路径作为本次结果。

登录恢复或回答质量重试后重新调用 `amazon_rufus_get` 成功时，必须使用重试成功响应中的最新 `report_path` 覆盖旧路径；如果无法确认本次 `report_path`，直接报错，不用历史报告兜底。

除非用户明确要求排障，不输出：

- `seed_request`
- `upload_payload`
- headers
- cookie
- localStorage
- `storage_state`
- cURL 命令
- 完整原始 JSON
