# ops-amazon-rufus 使用说明

`ops-amazon-rufus` 提供 Amazon Rufus 默认问题模板库，并作为 Agent 使用 Rufus MCP 工具链的入口索引。Rufus 运行期以 MCP Tool 优先编排，只有明确白名单场景允许 CLI fallback。Rufus 获取 Python 文件归属 `opscli/mcp/tools/amazon_rufus.py` 和 `opscli/amazon_rufus/`；本 Skill 不包含获取脚本。

## 术语约定

- 面向用户和 Agent 的流程统一称为“亚马逊 Rufus 登录态”，不要把它描述为普通 Cookie。
- 后端接口和工具名仍保留 `platform-cookie` / OPS 平台 Cookie 命名；其 `content` 实际承载亚马逊 Rufus 登录态，当前规范直接保存浏览器 `/rufus/cl/streaming` cURL 命令态。

## 目录结构

```text
ops-amazon-rufus/
├── SKILL.md
├── README.md
├── data/
│   ├── VERSION.json
│   └── question_templates.json
└── references/
    ├── question-templates.md
    ├── rufus-mcp-workflow.md
    └── rufus-report-formatting.md
```

## MCP-first 运行约束

1. Skill 运行期优先调用 MCP Tool。
2. 必需 MCP Tool：`auth_is_authenticated`、`auth_mcp_login`、`auth_check_token`、`auth_token_refresh`、`amazon_rufus_remote_consent_status`、`amazon_rufus_remote_consent_set`、`amazon_rufus_login_status`、`amazon_rufus_watch_login`、`amazon_rufus_logout`、`amazon_rufus_get`。
3. 排障/初始化 MCP Tool：`amazon_rufus_platform_cookie_save`、`amazon_rufus_platform_cookie_get`、`amazon_rufus_curl_save`。这些工具不属于默认获取主流程，只在用户明确要求排障、迁移或初始化 Rufus 状态时使用。
4. 只有以下两种情况允许 CLI fallback：
   - 必需 MCP Tool 不可用。
   - 用户拒绝保存并复用该站点亚马逊 Rufus 登录态。
5. 其他错误不允许 CLI fallback。
6. 每次获取前先通过 `amazon_rufus_remote_consent_status(country)` 读取远程授权偏好。
7. 发起 Rufus 获取前先调用 `amazon_rufus_login_status(country)`；没有可用亚马逊 Rufus 登录态时，仅在 `watch_login_attempted=false` 时调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`。
8. OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 时，仅在 `watch_login_attempted=false` 时调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`；本分支不允许 CLI fallback。
9. 登录采集会打开或连接本机 Chrome CDP 调试浏览器；内部保存为浏览器 cURL 命令态，获取完成后不能输出 cookie、localStorage、`storage_state`、headers、payload、cURL 命令或请求种子。
10. 用户拒绝远程授权时进入 CLI fallback，不调用 `amazon_rufus_get`。
11. 旧 `curl_data` 或仅 `storage_state` 的 OPS 平台 Cookie 接口 content 不再作为可用亚马逊 Rufus 登录态；状态为 `invalid` 时需要重新执行登录采集。
12. 同一次 Skill 调用最多触发一次 `watch_login`；MCP `amazon_rufus_watch_login` 和 CLI `opscli amazon-rufus watch-login` 都计入。
13. Rufus 获取成功后必须执行回答质量判断；无回答、拒答、答非所问或复杂问题退化为商品详情时，开启一个子 agent 改写问题，并按改写后的完整问题来源重新调用 `amazon_rufus_get`；多问题保持在同一个 Rufus 对话中，每个问题最多 10 次。

## 整体调用链（三条）

Rufus Skill 的完整链路分为三条：Skill 编排链、MCP 后端获取链、CLI fallback 链。三条链路都必须保持相同的问题来源：单题使用单题，多题使用多题，未提供问题时使用默认题库。

### 1. Skill 编排链

```text
用户 Rufus / Listing 需求
  -> Agent 解析 ASIN、国家站点、问题来源
  -> 检查必需 MCP Tool
  -> MCP 鉴权和 ops Token 检查
  -> 读取 remote-consent 授权偏好
  -> 检查亚马逊 Rufus 登录态
  -> 必要时执行登录采集
  -> 调用 amazon_rufus_get
  -> 必要时执行回答质量判断和问题改写重试
  -> 必要时执行一次登录恢复
  -> 返回本次 report_path
```

节点说明：

1. 用户需求节点：用户提供 ASIN、国家站点和可选 Rufus 问题。
2. 参数解析节点：Agent 归一化 ASIN、国家站点和问题来源，并初始化 `login_recovery_attempted=false`、`watch_login_attempted=false`、`answer_rewrite_attempts_by_question={}`。
3. MCP Tool 检查节点：缺少必需 MCP Tool 时进入 CLI fallback；这是允许 CLI fallback 的白名单场景之一。
4. MCP 鉴权节点：依次调用 `auth_is_authenticated()`、必要时 `auth_mcp_login()`、`auth_check_token(system="ops")` 和必要时 `auth_token_refresh(system="ops")`。
5. 授权偏好节点：调用 `amazon_rufus_remote_consent_status(country)`；`unknown/invalid` 时询问用户允许或拒绝，随后调用 `amazon_rufus_remote_consent_set(...)` 保存偏好。
6. 登录态检查节点：`allowed` 时调用 `amazon_rufus_login_status(country)`；`can_get_backend=false` 或 `status=missing/invalid` 时进入登录采集。
7. 登录采集节点：任何分支准备调用 `amazon_rufus_watch_login` 前都必须检查 `watch_login_attempted=false`，并在调用前设置为 `watch_login_attempted=true`；工具打开或连接 Chrome，等待用户登录并捕获 `/rufus/cl/streaming`。
8. Rufus 获取节点：按原问题来源调用 `amazon_rufus_get`；成功后只使用本次返回的 `report_path`。
9. 回答质量判断节点：读取本次 `report_path`，对 `answer_count=0`、拒答、答非所问或复杂问题退化为商品详情的题目执行问题改写重试。
10. 子 agent 改写节点：固定提示词为 `重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。`，只改写未达到上限的不合格问题，使用 `answer_rewrite_attempts_by_question` 按问题分别记录，每个问题最多 10 次。
11. 登录恢复节点：`RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`RUFUS_HEADLESS_REQUEST_ERROR` 仅在 `login_recovery_attempted=false` 且 `watch_login_attempted=false` 时最多触发一次 `amazon_rufus_logout -> amazon_rufus_watch_login -> amazon_rufus_get`。
12. 输出节点：最终回复只展示本次 `report_path`，不得读取历史 ASIN 报告兜底。

### 2. MCP 后端获取链

```text
amazon_rufus_get
  -> RufusMcpManager.for_current_request(...)
  -> RufusMcpManager.get(...)
  -> RufusManager.get_backend(...)
  -> RufusBackendSecretProvider.load(country)
  -> RufusBrowserStateStore.load(country)
  -> 读取 OPS 平台 Cookie content
  -> 解析 streaming cURL
  -> 复用或捕获 streaming seed
  -> HeadlessRufusClient.query(...)
  -> AnswerReportWriter.write(...)
  -> MCP-safe 摘要响应
```

节点说明：

1. MCP 工具入口节点：`amazon_rufus_get` 接收 ASIN、国家、单题、多题或 `skills_dir`，不接收 cookie、headers、payload、`storage_state` 或 cURL 原文。
2. MCP Manager 节点：`RufusMcpManager.for_current_request(...)` 绑定当前 MCP 请求隔离凭证，`get(...)` 收敛参数并隐藏敏感字段。
3. Manager 获取节点：`RufusManager.get_backend(...)` 解析问题来源，准备后端/headless 获取。
4. 凭证读取节点：`RufusBackendSecretProvider.load(country)` 读取可用亚马逊 Rufus 登录态。
5. 远端状态读取节点：`RufusBrowserStateStore.load(country)` 默认通过 `RufusTransportClient.get_platform_cookie(platform="amazon")` 读取 `/v1/platform-cookies` 的 `content`。
6. content 解析节点：新格式 `content` 直接是 `curl ...`；读取端会包装为内部 `record["curl"]`。历史 JSON record 只有存在新 `curl` 字段时才可继续使用；旧 `curl_data` 或仅 `storage_state` 不再作为可用凭证。
7. cURL 解析节点：`RufusCurlParser` 从 cURL 命令解析 streaming URL、headers、Cookie header 和 payload template；如果没有历史 `seed_request` 摘要，服务层从 payload 的 `pageContext` 和 streaming URL 的 `tabId` 合成内部 seed。
8. seed 选择节点：同 ASIN、同国家且可复用时使用保存的 streaming seed；否则用 headless 链路重新捕获 `/rufus/cl/streaming`。
9. Rufus 请求节点：`HeadlessRufusClient.query(...)` 按问题逐题请求 Rufus SSE 并解析答案。
10. 报告写入节点：`AnswerReportWriter.write(...)` 写入 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。
11. MCP 安全响应节点：只返回本次 `report_path` 和脱敏摘要，不返回 content、cookie、headers、payload、seed request、upload payload 或 cURL 命令。

### 3. CLI fallback 链

```text
CLI fallback 触发
  -> opscli amazon-rufus login-status <COUNTRY> --pretty
  -> 必要时 opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty
  -> opscli amazon-rufus get-backend <ASIN> <COUNTRY> ...
  -> RufusManager.get_backend(...)
  -> 写入报告
  -> 返回本次 report_path
```

节点说明：

1. fallback 触发节点：只允许两类触发原因：必需 MCP Tool 不可用，或用户拒绝保存并复用该站点亚马逊 Rufus 登录态。
2. CLI 登录态检查节点：先执行 `opscli amazon-rufus login-status <COUNTRY> --pretty`，读取脱敏可用性摘要。
3. CLI 登录采集节点：`can_get_backend=false` 或状态为 `missing/invalid` 时执行 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty`。
4. CLI 获取节点：按原问题来源执行 `get-backend`；单题传一次 `-q`，多题重复 `-q`，默认题库传 `--skills-dir ".agents/skills"`。
5. 共享服务节点：CLI `get-backend` 仍复用 `RufusManager.get_backend(...)`、`RufusBackendSecretProvider`、headless client 和报告写入逻辑。
6. 输出节点：CLI fallback 成功后只返回本次报告路径；失败时直接返回错误，不切回 MCP，也不扩大 fallback 范围。

## CLI fallback 指令

CLI fallback 只允许出现在“必需 MCP Tool 不可用”或“用户拒绝保存并复用该站点亚马逊 Rufus 登录态”两个场景。

```text
opscli amazon-rufus login-status <COUNTRY> --pretty
opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser --pretty
opscli amazon-rufus get-backend <ASIN> <COUNTRY> --skills-dir ".agents/skills"
opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题>"
opscli amazon-rufus get-backend <ASIN> <COUNTRY> -q "<问题1>" -q "<问题2>"
```

在本项目内运行时优先使用 `uv run opscli ...` 或 `.venv/Scripts/opscli.exe ...`。

## 典型工作流

1. Agent 解析 ASIN、国家站点和问题来源。
2. 检查必需 MCP Tool；不可用时进入 CLI fallback。
3. 调用 `auth_is_authenticated()`；未登录时调用 `auth_mcp_login()`。
4. 调用 `auth_check_token(system="ops")`；Token 失效时调用 `auth_token_refresh(system="ops")`。
5. 调用 `amazon_rufus_remote_consent_status(country)`。
6. 状态为 `unknown/invalid` 时询问用户是否允许 MCP/headless 复用亚马逊 Rufus 登录态；允许则调用 `amazon_rufus_remote_consent_set(country, allowed=true)`，拒绝则调用 `amazon_rufus_remote_consent_set(country, allowed=false)` 并进入 CLI fallback。
7. 状态为 `denied` 时进入 CLI fallback。
8. 状态为 `allowed` 时，调用 `amazon_rufus_login_status(country)`。
9. 如果亚马逊 Rufus 登录态缺失，且 `watch_login_attempted=false`，设置为 true 后调用 `amazon_rufus_watch_login(asin, country, close_browser=true)` 完成登录采集，再次检查登录态。
10. 如果返回 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401，且 `watch_login_attempted=false`，设置为 true 后调用 `amazon_rufus_watch_login(asin, country, close_browser=true)`，采集后按原问题来源调用 `amazon_rufus_get`。
11. 调用 `amazon_rufus_get` 获取 Rufus 回答并写入报告。
12. 读取本次 `report_path` 做回答质量判断；如果 `answer_count=0`、拒答、答非所问，或问题不止商品详情但回答只是商品详情，开启子 agent 改写不合格问题。
13. 子 agent 固定提示词为：`重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。`
14. 用改写结果替换原问题位置，按完整问题列表重新请求 Rufus；使用 `answer_rewrite_attempts_by_question` 按问题分别记录，每个问题最多 10 次，多问题仍保持同一个 Rufus 对话。
15. 如果命中 `RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR` 或 `RUFUS_HEADLESS_REQUEST_ERROR`，本次 Skill 调用尚未触发登录恢复且 `watch_login_attempted=false` 时，按 `amazon_rufus_logout -> amazon_rufus_watch_login -> amazon_rufus_get` 恢复一次。
16. 如果 `watch_login_attempted=true`，不得再次调用 `amazon_rufus_watch_login`；每次 Skill 调用最多触发一次登录恢复，恢复后仍失败时直接报错，不再重复打开登录窗口。
17. 其他错误不允许 CLI fallback。

## References

- `references/rufus-mcp-workflow.md`：Rufus MCP-first 获取、bounded CLI fallback、remote-consent 分流、登录态检查、通用登录采集恢复、问题来源选择和错误处理。
- `references/question-templates.md`：默认题库接口、数据文件格式和同步规则。
- `references/rufus-report-formatting.md`：答案报告格式、拒答改写和敏感字段隐藏规则。

## 安全边界

所有返回用户或写入报告的内容不得包含：

- OPS JWT
- session ID
- 亚马逊 Rufus 登录态中的 Cookie header
- 平台 Cookie 接口 `content` 原文
- headers
- payload
- `storage_state`
- cURL 命令
- seed request
- upload payload

排障/初始化工具额外约束：

- `amazon_rufus_platform_cookie_save` 不回显 content。
- `amazon_rufus_platform_cookie_get` 默认不返回 content；只有用户明确要求排障读取完整 content 时才允许 `include_content=true`。
- `amazon_rufus_curl_save` 不回显 raw cURL。
- 即使排障工具返回完整 content，也不得写入报告、最终回复、feedback 或普通日志。

## 报告新鲜度

最终回复只允许使用本次 `amazon_rufus_get` 或 CLI `get-backend` 返回的 `report_path`。不得返回历史 ASIN 报告，不得按 ASIN 在 `output/amazon-rufus/` 中自行挑选旧报告作为本次结果。

## 文件边界

禁止在 Skill 目录新增 Rufus 获取脚本：

```text
ops-amazon-rufus/scripts/get_rufus.py
ops-amazon-rufus/scripts/rufus.py
ops-amazon-rufus/scripts/headless_rufus.py
```

所有获取 Rufus、读取后端授权材料、请求 Amazon Rufus 的 Python 代码必须位于 `opscli/amazon_rufus/` 或 `opscli/mcp/tools/amazon_rufus.py`。

## 示例触发

```text
$ops-amazon-rufus 帮我分析美国站, B0B1MLVMY5 这个商品的信息，要问 1. 这是什么商品 2. 这个商品评价如何？
opscli skills install ops-amazon-rufus --skills-dir ".agents/skills" --force
uv run opscli-mcp --transport both --port 8765
B0B1MLVMY5
```
