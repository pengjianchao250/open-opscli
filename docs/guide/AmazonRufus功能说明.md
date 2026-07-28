# Amazon Rufus 功能说明

> 如果想先用图理解整体链路，请看 [AmazonRufus功能流程图.md](AmazonRufus功能流程图.md)。

本文面向项目内开发、维护和二次接入人员，说明 `opscli` 中 `amazon_rufus` 模块的整体能力、入口、调用链、状态存储和错误边界。内容基于当前仓库代码整理，主要对应：

- `opscli/cli.py`
- `opscli/amazon_rufus/commands/cli.py`
- `opscli/amazon_rufus/services/manager.py`
- `opscli/amazon_rufus/services/mcp_manager.py`
- `opscli/mcp/tools/amazon_rufus.py`
- `opscli/skills/templates/ops-amazon-rufus/`

## 1. 功能定位

`amazon_rufus` 用来围绕 Amazon 商品页的 Rufus 问答能力做自动化采集与报告输出。它不是一个单独的“抓取脚本”，而是一套完整能力，包含：

1. Amazon Rufus 登录态采集。
2. Rufus streaming 请求种子捕获与复用。
3. 基于 headless 链路的后端问答获取。
4. MCP Tool 的安全暴露与脱敏返回。
5. 默认题库读取、报告生成和上传 payload 构建。
6. 远程授权偏好与 OPS 平台 Cookie content 管理。

它的主要目标不是“复刻浏览器操作”，而是让 Agent 或 CLI 在不暴露敏感材料的前提下，稳定拿到某个 ASIN 的 Rufus 问答结果，并写入本地报告。

## 2. 适用范围

当前模块聚焦以下场景：

- 针对单个 ASIN 发起 Rufus 问答。
- 使用默认题库批量提问。
- 基于 Rufus 回答生成 Listing 诊断或分析报告。
- 通过 MCP 在 Agent 流程中调用 Rufus。
- 在 MCP 不可用或用户拒绝远程复用登录态时，使用 CLI fallback。

当前不负责以下能力：

- 广告分析、关键词分析、Keepa 或 SellerSprite 类能力。
- 直接把 Cookie、headers、payload 暴露给 Agent。
- 通用 Amazon 网页抓取。

## 3. 顶层入口

### 3.1 CLI 入口

顶层注册位于 `opscli/cli.py`：

```python
app.add_typer(amazon_rufus_app, name="amazon-rufus")
```

因此外部命令入口是：

```text
opscli amazon-rufus ...
```

实际命令实现位于 `opscli/amazon_rufus/commands/cli.py`。

### 3.2 MCP Tool 入口

MCP Tool 暴露位于 `opscli/mcp/tools/amazon_rufus.py`，当前注册的工具为：

- `amazon_rufus_remote_consent_status`
- `amazon_rufus_remote_consent_set`
- `amazon_rufus_login_status`
- `amazon_rufus_watch_login`
- `amazon_rufus_logout`
- `amazon_rufus_get`
- `amazon_rufus_platform_cookie_save`
- `amazon_rufus_platform_cookie_get`
- `amazon_rufus_curl_save`

这里没有暴露 `init`、`save-state`、`get()` 这类更底层或偏本地的能力。MCP 只保留面向 Agent 的安全入口。

### 3.3 Skill 入口

Skill 模板位于 `opscli/skills/templates/ops-amazon-rufus/`。它本身不实现采集逻辑，只负责：

- 题库数据提供。
- Agent 编排规则。
- MCP-first / CLI fallback 的流程约束。
- 登录恢复与敏感信息边界说明。

因此职责划分是：

- `opscli/amazon_rufus/`：真正执行业务逻辑。
- `opscli/mcp/tools/amazon_rufus.py`：把业务逻辑包装成 MCP Tool。
- `ops-amazon-rufus` Skill：告诉 Agent 什么时候调哪个 Tool。

## 4. 核心能力总览

从代码结构看，`amazon_rufus` 主要由以下几块组成：

| 模块 | 主要职责 |
| --- | --- |
| `commands/cli.py` | CLI 命令面 |
| `services/manager.py` | 总编排入口，协调题库、登录态、headless 获取、平台 Cookie |
| `services/mcp_manager.py` | MCP 返回脱敏、安全字段过滤、报告写入 |
| `services/browser.py` | 通过 Chrome CDP 打开页面、监听登录、捕获 streaming 请求 |
| `services/browser_state_store.py` | Rufus 状态读写，默认走 OPS 平台 Cookie content |
| `services/backend_secret.py` | 从已保存状态恢复后端请求凭证 |
| `services/headless_capture.py` | headless 打开商品页并捕获 `/rufus/cl/streaming` |
| `services/headless_client.py` | 基于 seed、Cookie 和 payload 模板逐题请求 Rufus |
| `services/question_bank.py` | 读取默认题库 |
| `services/answer_report_writer.py` | 生成 `output/amazon-rufus/*.md` 报告 |
| `transport/client.py` | 与 OPS 后端的 `/v1/platform-cookies`、`/v1/rufus/upload` 通信 |

## 5. 真实主链路

### 5.1 默认获取链路

当前对外的正式主链路是 `get_backend()`，无论从 MCP 还是 CLI 调用，最终都会走到这条路径：

```text
amazon_rufus_get / opscli amazon-rufus get-backend
  -> RufusManager.get_backend()
  -> RufusBackendSecretProvider.load(country)
  -> RufusBrowserStateStore.load(country)
  -> 读取 OPS 平台 Cookie content
  -> 解析为 streaming cURL 与 seed
  -> 必要时用 headless 重新捕获 seed
  -> HeadlessRufusClient.query()
  -> AnswerReportWriter.write()
```

这条链路的特点：

- 对外不要求用户传 Cookie。
- 状态优先从远端平台 Cookie content 读取。
- 真正发起 Rufus 请求的是 headless HTTP / streaming 链路。
- 最终输出的是报告路径，不是原始请求材料。

### 5.2 登录态采集链路

当还没有可用的亚马逊 Rufus 登录态时，主入口不是 `init`，而是 `watch-login`：

```text
amazon_rufus_watch_login / opscli amazon-rufus watch-login
  -> BrowserAttachService.watch_login_and_capture_seed_request()
  -> 打开或连接本地 Chrome CDP
  -> 等待用户登录 Amazon
  -> 打开商品页
  -> 监听 /rufus/cl/streaming
  -> 捕获 storage_state + seed_request
  -> RufusBrowserStateStore.save()
```

保存时会构造一个内部 record，但默认远端只把 `content` 保存为单行 `curl ...` 命令态。读取时再恢复为内部 record 结构。

### 5.3 报告输出链路

成功获取后，报告统一写到：

```text
output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md
```

报告写入器是 `AnswerReportWriter`，格式化器是 `AnswerReportFormatter`。MCP 成功返回时只返回本次 `report_path` 及摘要字段，不会回传完整答案上下文中的敏感请求材料。

## 6. CLI 命令说明

当前 `opscli amazon-rufus` 命令可以分为三类。

### 6.1 主流程命令

- `get-backend <ASIN> <COUNTRY>`
  - 正式获取入口。
  - 支持 `-q/--question` 多次传入。
  - 不传问题时会走默认题库。
  - 可选 `--upload-payload` 和 `--submit-upload`。

- `watch-login <ASIN> <COUNTRY>`
  - 登录采集入口。
  - 自动监听登录完成并抓取 streaming seed。
  - `--close-browser` 用于采集结束后关闭本次由工具启动的调试浏览器。

- `login-status <COUNTRY>`
  - 检查当前国家站点的亚马逊 Rufus 登录态是否可用于 `get-backend`。
  - 返回 `status`、`can_get_backend`、`session_cookie_count` 等脱敏摘要。

- `logout <COUNTRY>`
  - 清理当前国家站点的 Rufus 状态。
  - 可选清理 opscli 自己创建的 Chrome profile。

### 6.2 授权偏好命令

- `remote-consent status <COUNTRY>`
  - 查看某站点是否允许 MCP/headless 链路复用该站点的亚马逊 Rufus 登录态。

- `remote-consent set <COUNTRY> --allow/--deny`
  - 保存远程授权偏好。

### 6.3 初始化/排障命令

- `init <COUNTRY>`
  - 只打开 Amazon 站点，供人工登录。
  - 更接近底层 CDP 辅助入口。

- `save-state <COUNTRY>`
  - 从当前 CDP 浏览器显式抓取 `storage_state` 并保存。

- `cookie save/status`
  - 用于显式写入或检查 Cookie 形式状态。

- `curl save`
  - 从浏览器 Copy-as-cURL 保存 streaming 请求状态。

- `platform-cookie save/get`
  - 直接操作 OPS 平台 Cookie 接口中的远端 content。
  - 属于排障或迁移工具，不是默认业务主流程。

## 7. MCP 工具职责

MCP 层通过 `RufusMcpManager` 做两件事：

1. 绑定当前 MCP 请求的认证上下文和凭证目录。
2. 对响应做 allowlist 过滤，避免敏感字段穿透。

比如 `amazon_rufus_get` 最终只返回：

- `report_path`
- `asin`
- `country`
- `question_count`
- `answer_count`
- `next_action`

不会返回：

- `content`
- `curl`
- `cookie`
- `headers`
- `payload_template`
- `seed_request`
- `upload_payload`

这层是整个模块安全边界的关键。

## 8. 状态与文件存储

### 8.1 默认远端状态源

默认情况下，`RufusBrowserStateStore` 会注入 `RufusTransportClient`，因此状态读写优先走 OPS 平台 Cookie 接口：

- POST `/v1/platform-cookies`
- GET `/v1/platform-cookies?platform=amazon`

当前约定：

- `platform` 默认是 `amazon`
- `country` 为两位国家代码
- `content` 默认保存为 streaming cURL 命令态

### 8.2 本地 fallback 文件

只有显式本地模式下，才会写到：

```text
CONFIG_DIR/amazon-rufus/browser-state-<COUNTRY>.json
```

也就是：

```text
~/.config/opscli/amazon-rufus/browser-state-<COUNTRY>.json
```

这个文件不是当前默认主路径，主要用于测试或显式本地 fallback。

### 8.3 远程授权偏好文件

远程授权偏好保存在：

```text
CONFIG_DIR/amazon-rufus/remote-consent.json
```

它只保存是否允许远程复用登录态，不保存 Cookie、payload 或 cURL 原文。

### 8.4 题库文件

默认题库读取路径是：

```text
.agents/skills/ops-amazon-rufus/data/question_templates.json
```

也可以通过 `--skills-dir` 或 MCP 的 `skills_dir` 指定其他 skill 根目录。

### 8.5 报告文件

Rufus 报告输出到：

```text
output/amazon-rufus/
```

注意：本次调用只能以返回的 `report_path` 为准，不能仅凭 ASIN 去读取历史报告。

## 9. 支持的国家站点

当前固定映射定义在 `runtime/country_map.py`，只支持：

- `US` -> `https://www.amazon.com`
- `UK` -> `https://www.amazon.co.uk`
- `DE` -> `https://www.amazon.de`
- `JP` -> `https://www.amazon.co.jp`

传入其他国家会抛出 `UNSUPPORTED_MARKETPLACE`。

## 10. 题库与问题来源

问题来源有三种：

1. 显式单题 `question`
2. 显式多题 `questions`
3. 默认题库

解析规则在 `RufusManager._resolve_questions()`：

- `question` 与 `questions` 不能同时传。
- `questions` 中任一空字符串会报错。
- 两者都不传时，读取 `QuestionBankService.load_templates()`。

因此默认题库不可用时，`get-backend` 与 `amazon_rufus_get` 都可能报 `QUESTION_BANK_NOT_READY`。

## 11. 敏感信息边界

`amazon_rufus` 模块对敏感信息控制非常严格。以下内容不应出现在普通 MCP 返回、CLI 成功返回、报告或常规日志中：

- OPS JWT
- session ID
- Cookie header
- 平台 Cookie `content` 原文
- 原始 cURL 文本
- `storage_state`
- `request_headers`
- `payload_template`
- `seed_request`
- `upload_payload`

敏感字段主要在以下位置被拦截：

- `RufusMcpManager._SENSITIVE_KEYS`
- `RufusMcpManager._assert_no_sensitive_keys()`
- CLI 里通过 `stdin` 读取 Cookie / cURL / content，避免进入 shell history

## 12. 关键错误码

常见错误及含义如下：

| 错误码 | 含义 |
| --- | --- |
| `QUESTION_BANK_NOT_READY` | 默认题库未安装或未升级 |
| `INVALID_QUESTION` | 问题参数不合法 |
| `INVALID_RUFUS_COOKIE` | Cookie 输入不合法 |
| `INVALID_RUFUS_CURL` | cURL 输入不合法 |
| `INVALID_RUFUS_PLATFORM` | platform/country/content 参数不合法 |
| `INVALID_RUFUS_BROWSER_STATE` | 本地或远端状态结构不合法 |
| `CHROME_CDP_UNAVAILABLE` | Chrome CDP 无法连接或无法启动 |
| `SEED_REQUEST_NOT_CAPTURED` | 没抓到 `/rufus/cl/streaming` |
| `RUFUS_SECRET_NOT_READY` | 还没有可用的后端请求凭证 |
| `RUFUS_HEADLESS_CAPTURE_ERROR` | headless 打开商品页并捕获 seed 失败 |
| `RUFUS_HEADLESS_REQUEST_ERROR` | headless 请求 Rufus SSE 失败 |
| `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` | OPS 平台 Cookie API 401，代表 OPS/MCP 鉴权失败，不等于 Amazon 登录态失效 |
| `RUFUS_REMOTE_HTTP_ERROR` | 远端 HTTP 层错误 |
| `RUFUS_REMOTE_BUSINESS_ERROR` | 远端业务错误 |
| `RUFUS_BAD_REMOTE_JSON` | 远端返回不是合法 JSON |

其中最容易误解的是：

- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`
  - 这是 OPS 鉴权问题。
  - 不是 Amazon Rufus 登录态缺失。

- `RUFUS_SECRET_NOT_READY`
  - 说明本地/远端还没有一份可用的 Rufus 状态。
  - 通常需要先走 `watch-login`。

## 13. 当前推荐使用方式

### 13.1 对 Agent / MCP 来说

推荐顺序：

```text
amazon_rufus_remote_consent_status
  -> amazon_rufus_login_status
  -> 必要时 amazon_rufus_watch_login
  -> amazon_rufus_get
```

### 13.2 对 CLI 来说

推荐顺序：

```text
opscli amazon-rufus login-status US --pretty
opscli amazon-rufus watch-login B0TEST1234 US --close-browser --pretty
opscli amazon-rufus get-backend B0TEST1234 US --skills-dir ".agents/skills"
```

### 13.3 不建议直接作为默认主流程使用的入口

以下命令更适合人工初始化、迁移或排障：

- `init`
- `save-state`
- `cookie save`
- `curl save`
- `platform-cookie save/get`

## 14. 如何运行 `amazon_rufus`

本节给出从本地环境、登录态准备到正式获取报告的完整操作流程。真实 Rufus 获取会依赖 OPS 登录态、Amazon Rufus 登录态、浏览器和网络环境；如果只做代码验证，请优先看第 15 节的离线测试。

### 14.1 本地开发环境准备

在项目根目录执行：

```powershell
cd F:\workspace\open-opscli
```

推荐使用项目内 `uv` 环境运行命令：

```powershell
uv run opscli --version
uv run opscli amazon-rufus --help
```

如果当前环境没有安装开发依赖或 Amazon 浏览器依赖，先安装：

```powershell
$env:SKIP_CYTHON = "1"
uv pip install -e ".[dev,amazon]"
uv run python -m playwright install chromium
```

如果不使用 `uv`，也可以使用当前虚拟环境中的命令：

```powershell
.\.venv\Scripts\opscli.exe amazon-rufus --help
```

### 14.2 推荐运行流程：MCP / Agent

Agent 默认应走 MCP-first 流程。逻辑顺序是：

```text
auth_is_authenticated / auth_mcp_login
  -> auth_check_token / auth_token_refresh
  -> amazon_rufus_remote_consent_status(country)
  -> 必要时 amazon_rufus_remote_consent_set(country, allowed=true)
  -> amazon_rufus_login_status(country)
  -> 必要时 amazon_rufus_watch_login(asin, country, close_browser=true)
  -> amazon_rufus_get(asin, country, question/questions/skills_dir)
  -> 读取本次返回的 report_path
```

单题示例：

```text
amazon_rufus_get(
  asin="B0TEST1234",
  country="US",
  question="这个商品适合送礼吗？"
)
```

多题示例：

```text
amazon_rufus_get(
  asin="B0TEST1234",
  country="US",
  questions=[
    "这是什么商品？",
    "这个商品评价如何？"
  ]
)
```

默认题库示例：

```text
amazon_rufus_get(
  asin="B0TEST1234",
  country="US",
  skills_dir=".agents/skills"
)
```

MCP 成功返回后，只使用本次响应里的 `report_path`。不要按 ASIN 去 `output/amazon-rufus/` 目录中挑历史报告。

### 14.3 推荐运行流程：CLI fallback

CLI fallback 只建议在 MCP Tool 不可用，或用户拒绝 MCP/headless 复用亚马逊 Rufus 登录态时使用。

第一步，检查登录态：

```powershell
uv run opscli amazon-rufus login-status US --pretty
```

如果返回 `can_get_backend=false`，执行登录采集：

```powershell
uv run opscli amazon-rufus watch-login B0TEST1234 US --close-browser --pretty
```

采集过程会打开或复用 Chrome。用户需要在浏览器里完成 Amazon 登录，并进入商品页触发 Rufus 请求。采集成功后再次检查：

```powershell
uv run opscli amazon-rufus login-status US --pretty
```

然后按问题来源获取报告。

单题：

```powershell
uv run opscli amazon-rufus get-backend B0TEST1234 US -q "这个商品适合送礼吗？"
```

多题：

```powershell
uv run opscli amazon-rufus get-backend B0TEST1234 US -q "这是什么商品？" -q "这个商品评价如何？"
```

默认题库：

```powershell
uv run opscli amazon-rufus get-backend B0TEST1234 US --skills-dir ".agents/skills"
```

如果需要构造上传 payload：

```powershell
uv run opscli amazon-rufus get-backend B0TEST1234 US -q "这个商品适合送礼吗？" --upload-payload
```

如果需要显式提交到后端上传接口：

```powershell
uv run opscli amazon-rufus get-backend B0TEST1234 US -q "这个商品适合送礼吗？" --submit-upload
```

注意：`--submit-upload` 会真实调用 OPS 后端 `/v1/rufus/upload`。仅调试本地报告时不要加这个参数。

### 14.4 登录态清理和重新采集

当登录态失效、国家站点切换、或需要清理工具管理的 Chrome profile 时，可以执行：

```powershell
uv run opscli amazon-rufus logout US --pretty
```

如需保留浏览器 profile，只清理 Rufus 状态：

```powershell
uv run opscli amazon-rufus logout US --no-browser-profile --pretty
```

清理后重新执行：

```powershell
uv run opscli amazon-rufus watch-login B0TEST1234 US --close-browser --pretty
uv run opscli amazon-rufus get-backend B0TEST1234 US -q "这个商品适合送礼吗？"
```

### 14.5 远程授权偏好

查看当前国家站点是否允许 MCP/headless 复用亚马逊 Rufus 登录态：

```powershell
uv run opscli amazon-rufus remote-consent status US --pretty
```

允许：

```powershell
uv run opscli amazon-rufus remote-consent set US --allow --pretty
```

拒绝：

```powershell
uv run opscli amazon-rufus remote-consent set US --deny --pretty
```

`remote-consent` 只保存授权偏好，不保存 Cookie、headers、payload、cURL 或请求种子。

### 14.6 报告检查

成功后报告写入：

```text
output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md
```

检查时只读取本次命令或 MCP 响应返回的路径。例如：

```powershell
Get-Content -LiteralPath "output\amazon-rufus\B0TEST1234-20260622-120000.md" -Encoding UTF8
```

不要使用“最新文件”或“同 ASIN 历史文件”替代本次返回的 `report_path`，否则可能读到上一轮结果。

### 14.7 排障入口

以下命令用于迁移、初始化或深度排障，不是默认业务主流程：

```powershell
uv run opscli amazon-rufus init US --pretty
uv run opscli amazon-rufus save-state US --pretty
uv run opscli amazon-rufus cookie status US --pretty
uv run opscli amazon-rufus platform-cookie get amazon US --pretty
```

写入敏感内容时必须走 stdin，避免进入 shell history：

```powershell
Get-Content .\rufus-content.txt -Raw | uv run opscli amazon-rufus platform-cookie save amazon US --from-stdin --pretty
Get-Content .\rufus-curl.txt -Raw | uv run opscli amazon-rufus curl save B0TEST1234 US --from-stdin --pretty
```

这些文件如果包含真实登录态或 cURL 原文，不应提交到仓库，也不应贴到普通文档、issue、日志或 feedback 中。

## 15. 如何测试 `amazon_rufus`

测试分为三层：离线单元测试、MCP/Skill 契约测试、真实链路验证。日常开发优先跑前两层；真实链路验证只在需要确认浏览器、登录态、OPS 后端和 Amazon Rufus 可用时执行。

### 15.1 离线单元测试

覆盖 `amazon_rufus` 核心逻辑、题库解析、状态存储、报告格式化、CLI 参数、headless 客户端 mock 等：

```powershell
uv run pytest tests/amazon_rufus/test_core.py -q
```

覆盖远端传输客户端，包括 `/v1/rufus/upload`、平台 Cookie 接口、远端错误解析：

```powershell
uv run pytest tests/amazon_rufus/test_transport.py -q
```

覆盖 MCP-facing manager 的脱敏响应和报告写入：

```powershell
uv run pytest tests/amazon_rufus/test_mcp_manager.py -q
```

### 15.2 MCP Tool 测试

覆盖 `amazon_rufus_get`、登录态工具、远程授权工具等 MCP Tool 包装层：

```powershell
uv run pytest tests/mcp/test_amazon_rufus_tools.py -q
```

如果改了 MCP 工具注册或 schema，也建议跑：

```powershell
uv run pytest tests/mcp/test_tools.py -q
```

### 15.3 Skill 文档和升级契约测试

如果改了 `opscli/skills/templates/ops-amazon-rufus/` 或 Agent 编排规则，运行：

```powershell
uv run pytest tests/skills/test_ops_amazon_rufus_updater.py -q
uv run pytest tests/skills/test_cli.py -q
```

这些测试会检查 Skill 模板是否仍包含正确 MCP 工具名、CLI fallback 指引、敏感字段边界和升级输出。

### 15.4 模块回归组合

修改 `opscli/amazon_rufus/`、`opscli/mcp/tools/amazon_rufus.py` 或 Skill 模板后，推荐组合：

```powershell
uv run pytest tests/amazon_rufus/test_core.py tests/amazon_rufus/test_transport.py tests/amazon_rufus/test_mcp_manager.py tests/mcp/test_amazon_rufus_tools.py tests/skills/test_ops_amazon_rufus_updater.py -q
```

如果只是改本文档，通常不需要跑完整测试；可以做 Markdown 内容检查和关键命令片段检查即可。

### 15.5 CLI help 冒烟测试

这类命令不会触发真实 Amazon/Rufus 网络请求，适合作为本地快速检查：

```powershell
uv run opscli amazon-rufus --help
uv run opscli amazon-rufus get-backend --help
uv run opscli amazon-rufus watch-login --help
uv run opscli amazon-rufus remote-consent --help
```

如果只想避免顶层 update check 等副作用，可以使用 Typer runner 写定向测试，或直接运行已有 `tests/amazon_rufus/test_core.py` 中的 CLI help 用例。

### 15.6 真实链路验证

真实链路验证会访问 OPS 后端、启动或连接浏览器，并请求 Amazon Rufus。执行前确认：

- 当前用户已完成 `opscli auth` 登录。
- 目标国家站点支持，当前仅 `US`、`UK`、`DE`、`JP`。
- 已安装 Playwright Chromium。
- 使用独立、干净的 Amazon 账号完成 Rufus 登录态采集。
- 不在命令行、日志、报告或反馈中泄露 Cookie、headers、payload、cURL 原文。

推荐真实验证流程：

```powershell
uv run opscli amazon-rufus login-status US --pretty
uv run opscli amazon-rufus watch-login B0TEST1234 US --close-browser --pretty
uv run opscli amazon-rufus login-status US --pretty
uv run opscli amazon-rufus get-backend B0TEST1234 US -q "这个商品适合送礼吗？"
```

验证点：

- `login-status` 返回 `can_get_backend=true`。
- `watch-login` 返回 `streaming_request_saved=true` 或等价保存摘要。
- `get-backend` 写入 `output/amazon-rufus/<ASIN>-*.md`。
- 报告内容来自本次返回路径。
- CLI/MCP 输出中没有 Cookie、headers、payload、seed、cURL 或 `upload_payload` 原文。

### 15.7 失败处理

如果真实 `opscli amazon-rufus ...` 命令失败，应先按错误码判断：

- `RUFUS_SECRET_NOT_READY`：通常需要重新 `watch-login`。
- `RUFUS_HEADLESS_CAPTURE_ERROR`：检查浏览器、商品页、登录态和 Playwright。
- `RUFUS_HEADLESS_REQUEST_ERROR`：检查 Rufus 请求是否被拒绝、登录态是否失效。
- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`：这是 OPS 鉴权问题，不是 Amazon 登录态问题。
- `QUESTION_BANK_NOT_READY`：安装或升级 `ops-amazon-rufus` Skill，或临时用 `-q` 指定问题。

在本项目内，任何 `opscli` CLI 命令失败都需要按 `ops-feedback` 规则提交结构化反馈；反馈内容只能包含脱敏摘要，不能包含 Cookie、headers、payload、cURL、seed 或平台 Cookie content 原文。

## 16. 一句话理解整体结构

如果只记一件事，可以这样理解：

`amazon_rufus` 的正式业务主链是“先准备一份可复用的亚马逊 Rufus 登录态，再通过 headless 流程复用它向 `/rufus/cl/streaming` 连续提问，最后把答案写成本次报告并只暴露脱敏结果”。
