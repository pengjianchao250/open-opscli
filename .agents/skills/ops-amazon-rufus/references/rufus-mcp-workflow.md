# Rufus MCP-first 获取流程

## 适用范围

本文描述 `ops-amazon-rufus` 的 MCP-first 获取规则，包括 MCP 鉴权、bounded CLI fallback、remote-consent 授权偏好、登录态检查、Amazon 登录采集、Rufus 获取、错误恢复和报告路径与地址输出。

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

## 流程入口

获取顺序、CLI fallback 白名单和授权分流见 [SKILL.md 主流程](../SKILL.md#主流程)。本文补充工具细节；所有登录操作统一执行[登录采集入口](#登录采集入口)，调用来源只说明当前 MCP/CLI 路径和是否要求预清理，不自行执行登录或注销。

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
- 登录态过期、`can_get_backend=false` 或 `status=missing/invalid`：没有可用亚马逊 Rufus 登录态，执行[登录采集入口](#登录采集入口)，沿用 MCP 路径，不要求预清理。
- OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401：执行[登录采集入口](#登录采集入口)，沿用 MCP 路径，不要求预清理；本分支不允许 CLI fallback。

`amazon_rufus_login_status` 只输出 `status`、`has_login_state`、`can_get_backend`、`session_cookie_count`、`has_streaming_request` 等脱敏摘要。不要让 Agent 读取或展示 OPS 平台 Cookie 接口 content 原文。

`can_get_backend=true` 只表示 OPS 平台 Cookie 接口 content 内的亚马逊 Rufus 登录态存在可解析的浏览器 cURL 命令态。旧 `curl_data` 或仅 `storage_state` 的 content 不再作为可用后端凭证，按上述 `status=invalid` 分支处理。

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

每次 `amazon_rufus_get` 或 CLI `get-backend` 成功后，Agent 必须读取本次 `report_path` 做回答质量判断，并保留同次返回的 `report_url`。本判断只使用本次报告，不读取历史 ASIN 报告，不使用 IDE 打开的旧文件。多问题获取属于同一个 Rufus 对话，判断和重试都按题目逐项处理，但重新请求时保持完整问题列表。

### 不合格判断

以下任一情况视为回答不合格，需要改写问题并重新请求 Rufus：

1. `answer_count=0`、报告为空、题目下没有实际答案。
2. Rufus 明确拒答、提示重试、表示无法回答，或只返回错误性文本。
3. 只要答案或总结中出现以下拒答句式，也必须视为拒答而不是有效结果：`我无法完成您的请求`、`我不能提供以下服务`、`超出了我的服务范围`、`I can't complete your request`、`I cannot complete your request`、`I can't provide`、`I cannot provide`、`outside my scope`。
4. 回答没有覆盖问题意图。例如问题询问差评、风险、评价、适配人群、广告投放、对比、场景判断或优化建议，但答案只描述商品详情、规格参数或基础卖点。
5. 多题场景中某一题答案串题、漏题，或回答内容明显属于另一道题。

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
8. 某题达到 10 次后仍不合格时停止重试该题，其他不合格题目仍可按各自上限继续；最终回复只展示最新一次成功调用的 `report_url`，并说明对应题目已达到回答质量重试上限。

## 登录采集入口

本节统一处理登录态过期、缺失、无效和获取失败后的重新登录。保留原 ASIN、国家、问题来源及当前 MCP/CLI 路径；来源只说明是否要求预清理，本节决定实际登录方式，完成后返回来源流程。

1. 检查本次调用的 `watch_login_attempted`。同一次 Skill 调用最多触发一次 `watch_login`，包括 MCP、CLI 和交给用户执行的电脑端登录。如果 `watch_login_attempted=true`，不得再次调用 `amazon_rufus_watch_login`，也不得切换 CLI 登录、先注销再登录或重复要求用户登录，直接返回最新错误。
2. 检查当前 Agent 执行环境的系统，读取环境信息，必要时 Windows 用 PowerShell 查询系统、macOS/Linux 用 `uname -s`。无法确认时询问用户，不启动浏览器或清理状态。
3. Windows 或 macOS（Darwin）进入本机登录分支；Linux 按本 Skill 约定视为 AI 助手环境，进入用户电脑端登录分支。

任何分支准备调用 `amazon_rufus_watch_login`、执行 CLI 登录或向用户发出电脑端登录命令前，必须先检查 `watch_login_attempted=false`，并设置 `watch_login_attempted=true`；需要预清理时在注销前设置。该状态只存在于本次 Skill 调用内，不写入文件或反馈，回答质量重试不得重置它。

### Windows/macOS：本机登录

沿用来源流程选定的 MCP/CLI 路径：

- **MCP 路径**：仅在来源要求预清理时调用 `amazon_rufus_logout(country)`，清理失败则停止；成功或无需清理时，调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`，打开或连接本机 Chrome CDP 调试浏览器。示例：

```text
amazon_rufus_watch_login(asin="B0TEST1234", country="US", close_browser=true)
```

- **CLI fallback 路径**：执行 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty`，使用当前任务的 ASIN 和国家，不新增注销动作。

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

旧 `browser-state-<COUNTRY>.bin`、`browser-state-<COUNTRY>.json` 和 `.browser-state-key` 不再作为默认读写源；只有本地旧状态时，也通过本节对应系统的登录分支重新保存状态。

登录完成判定满足任一条件即可：

1. 读取 `#nav-tools` 容器文本，未出现 i18n 未登录提示。
2. 目标站点 Cookie name 存在 `sso-state-main` 或 `at-main`。

未登录提示词应覆盖当前支持站点和常见页面语言，包括 `sign in`、`signin`、`log in`、`login`、`identifícate`、`identificate`、`identificarse`、`iniciar sesión`、`登录`、`登入`、`サインイン`、`ログイン`、`anmelden`、`einloggen`、`connexion`、`se connecter`。`Hola`、`Hello`、`Hallo` 等问候词本身不能作为未登录提示。

MCP 后端只从 OPS 平台 Cookie 接口 content 中读取浏览器 cURL 命令态，并在服务层内部解析请求种子；Skill 不读取、不展示、不记录其中的敏感字段。

`amazon_rufus_watch_login` 只输出保存摘要，例如国家、ASIN、是否保存、是否检测到登录、cookie 数量、origin 数量、是否保存 streaming request。不要展示完整状态、cookie、localStorage、headers、payload、seed request、cURL 命令、完整请求或 upload payload。

### Linux：用户在电脑上登录

1. 暂停获取，向用户提供一行命令，使用当前任务的 ASIN 和国家。下方 ASIN 和 US 仅为示例：

```text
当前亚马逊 Rufus 登录态已失效或不可用。当前运行在 Linux AI 助手环境，请在你自己的 Windows 或 Mac 电脑终端运行：

opscli amazon-rufus watch-login B0CSN6FR1W US --close-browser --pretty

请在打开的浏览器中登录亚马逊，等待命令提示采集并保存成功后，再回复“已完成”。不需要发送密码、验证码或登录态内容。
```

2. 用户电脑需已安装 opscli 和 Chrome，并使用与助手相同的 OPS 账号；OPS 未登录时先运行 `opscli auth login`，再执行上述亚马逊登录命令。
3. 等待用户确认，不在 Linux 调用 MCP/CLI 登录、执行 `amazon_rufus_logout`、轮询或继续获取，即使来源要求预清理也不注销。电脑端登录不改变远程授权偏好，也不新增 Agent 自动执行 CLI fallback 的白名单。

### 登录后复查

本机采集成功或用户确认电脑端登录完成后，沿用来源路径复查同一国家站点：

- MCP 路径调用 `amazon_rufus_login_status(country)`。
- CLI 路径执行 `opscli amazon-rufus login-status <COUNTRY> --pretty`。

仅在 `can_get_backend=true` 时返回来源流程继续获取或重试，保留原 ASIN、国家和问题来源。仍不可用或检查失败时返回实际错误，不重复登录、不索取 Cookie 或 cURL；等待用户期间只返回登录提示，不返回历史报告。

## 三类 MCP 错误的登录采集恢复

以下错误在 allowed 路径中仅当 `login_recovery_attempted=false` 且 `watch_login_attempted=false` 时进入一次登录采集恢复：

```text
RUFUS_HEADLESS_REQUEST_ERROR
RUFUS_HEADLESS_CAPTURE_ERROR
RUFUS_SECRET_NOT_READY
```

OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 执行[登录采集入口](#登录采集入口)，沿用 MCP 路径，不要求预清理；本分支不允许 CLI fallback。

`RUFUS_HEADLESS_REQUEST_ERROR` 的 message 可能是 `Rufus 请求失败: 403`。此时不要把 403 当作 MCP 服务不可用，也不要直接重复调用 `amazon_rufus_get`；按授权或页面上下文失效处理，进入一次登录采集恢复。

### 恢复步骤

1. 保留原始 ASIN、国家站点、`question`、`questions` 和 `skills_dir`。本次 `login_recovery_attempted` 或 `watch_login_attempted` 已为 true 时，返回最新错误，不重复恢复。
2. 设置 `login_recovery_attempted=true`，执行[登录采集入口](#登录采集入口)，沿用 MCP 路径并要求预清理。来源不直接注销，实际操作由登录入口决定。
3. 入口确认登录态可用后，按原问题来源重新调用 `amazon_rufus_get`；再次失败则返回最新错误，不重新登录、不切换 CLI，也不使用历史报告。

`login_recovery_attempted` 只存在于当前 Skill 调用内，不写入文件或反馈，不因问题改写而重置。

## CLI fallback 子流程

CLI fallback 只由 `mcp_tools_unavailable` 或 `remote_consent_denied` 触发。具体步骤见 [SKILL.md 的 CLI fallback 子流程](../SKILL.md#cli-fallback-子流程)；需要登录时执行[登录采集入口](#登录采集入口)，沿用 CLI 路径，不要求预清理。

## 输出要求

MCP 工具或 CLI 获取成功时返回同一次调用生成的 `report_path` 和 `report_url`。完整答案报告写入运行目录下的 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS-<UUID>.md`，UUID 用于隔离同一 ASIN 的并发请求，随后上传并返回远程地址。

### 报告新鲜度约束

最终回复用户时固定使用 `Rufus 报告：<report_url>`。本地 `report_path` 只用于读取正文和回答质量判断，不向用户展示。

禁止仅凭 ASIN 在 `output/amazon-rufus/` 中读取任意 `<ASIN>-*.md` 历史报告，也不要使用 IDE 当前打开文件或上一轮对话遗留路径作为本次结果。

登录恢复或回答质量重试后重新调用 `amazon_rufus_get` 或 CLI `get-backend` 成功时，必须使用最新响应中的 `report_path` 和 `report_url` 成对替换旧值，不得混用不同调用的路径和 URL。

当前调用或重试失败时直接返回最新错误，不得使用历史 `report_path`、历史 `report_url` 或上一轮成功结果兜底；上传失败也属于本次获取失败。

除非用户明确要求排障，不输出：

- `seed_request`
- `upload_payload`
- headers
- cookie
- localStorage
- `storage_state`
- cURL 命令
- 完整原始 JSON
