# Rufus MCP 获取流程

## 适用范围

本文描述 `ops-amazon-rufus` 的 Rufus 获取与 MCP 工具调用规则，包括默认后端/headless 获取、问题来源选择、错误处理和报告路径输出。

题库维护见 `references/question-templates.md`。报告格式与拒答改写见 `references/rufus-report-formatting.md`。

## MCP 工具

| 工具 | 用途 |
|------|------|
| `amazon_rufus_get` | 默认使用 MCP 后端 headless 链路获取 Rufus 回答并写入报告 |

## 获取前规则

1. 先确认 ASIN、国家站点和用户问题。
2. 默认直接使用 `amazon_rufus_get`；该工具不打开可见浏览器页。
3. 如果当前宿主未暴露 `amazon_rufus_get`，改用 opscli 正式 CLI 的本机 Chrome CDP 入口，不在 Skill 目录创建或执行 Rufus 获取脚本。
4. 每次 Skill 调用开始时记录 `login_recovery_attempted=false`，用于限制本轮最多触发一次登录恢复。
5. 如果 `amazon_rufus_get` 返回 `RUFUS_HEADLESS_REQUEST_ERROR`、`RUFUS_HEADLESS_CAPTURE_ERROR` 或 `RUFUS_SECRET_NOT_READY`，且 `login_recovery_attempted=false`，进入一次 CDP 登录态刷新。
6. 登录态刷新必须先执行 `opscli amazon-rufus logout <COUNTRY> --pretty` 清理旧状态；`logout` 成功后再执行 `watch-login` 监听登录页并保存本地明文状态（敏感）与 streaming seed，再按原问题来源重新调用 `amazon_rufus_get`。
7. 如果本轮已触发过登录态刷新，或保存后重新调用 `amazon_rufus_get` 仍失败，不再打开第二次登录窗口，直接报错。
8. 如果成功但 `answer_count=0`，按正常 0 答案报告处理，不推断为登录恢复。

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

当用户只提供 ASIN 和国家，或要求“默认报告”“完整分析”“跑题库”时，使用默认题库模式：

```text
amazon_rufus_get(asin="B0TEST1234", country="US", skills_dir=".agents/skills")
```

临时问题模式传入后会跳过默认题库。不要把多个问题拼成一个长字符串，也不要为了多个临时问题改用默认题库。

## opscli 登录页监听入口

当 MCP 默认链路返回三类登录态相关错误时，先用 opscli 清理旧 Rufus 登录态，再打开或连接目标国家站点登录窗口，实时检测用户是否完成登录，并捕获目标 ASIN 商品页的 `/rufus/cl/streaming` 请求种子。保存完成后继续调用 `amazon_rufus_get`；不要把 CDP 参数、cookie、headers、payload、完整请求或 `storage_state` 暴露给 MCP 入参。

恢复前清理旧状态：

```powershell
opscli amazon-rufus logout <COUNTRY> --pretty
```

`logout` 成功后再执行 `watch-login`。如果 `logout` 因 opscli-owned Chrome profile 被占用失败，不要自动降级到 `--no-browser-profile`；应提示用户关闭对应调试 Chrome 后重试，避免继续复用旧登录态。

监听登录页并保存本地明文状态（敏感）：

```powershell
opscli amazon-rufus watch-login B0TEST1234 US --launch-if-needed
```

如果自动发现 Chrome 失败，再询问用户 Chrome 可执行文件路径，并追加 `--chrome-path`：

```powershell
opscli amazon-rufus watch-login B0TEST1234 US --launch-if-needed --chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

`watch-login` 是阻塞命令：它会打开 Amazon 页面供用户登录，命令内部持续监听页面登录状态和 `/rufus/cl/streaming` 请求。用户无需在 Agent 会话中额外回复“已登录”；命令捕获成功后会自动保存当前 CDP profile 的登录态和请求种子到本地明文状态（敏感）。

旧 `.bin` 加密状态和 `.browser-state-key` 不再读取或迁移；如本地只有旧状态，需要重新执行 `watch-login` 生成 `browser-state-<COUNTRY>.json`。

`watch-login` 的登录完成判定满足任一条件即可：

1. 读取 `#nav-tools` 容器文本，未出现 i18n 未登录提示。
2. 目标站点 Cookie name 存在 `sso-state-main` 或 `at-main`。

未登录提示词应覆盖当前支持站点和常见页面语言，包括 `sign in`、`signin`、`log in`、`login`、`identifícate`、`identificate`、`identificarse`、`iniciar sesión`、`登录`、`登入`、`サインイン`、`ログイン`、`anmelden`、`einloggen`、`connexion`、`se connecter`。`Hola`、`Hello`、`Hallo` 等问候词本身不能作为未登录提示。

请求种子只允许存在于本地明文状态（敏感）内；MCP 后端会优先读取该结构请求 Rufus，Skill 不读取、不展示、不记录其中的敏感字段。

`watch-login` 只输出保存摘要，例如国家、ASIN、是否保存、是否检测到登录、cookie 数量、origin 数量、是否保存 streaming request。不要展示完整 JSON 状态、cookie、localStorage、headers、payload、seed request、完整请求或 upload payload。

保存完成后，重新按原问题来源调用 `amazon_rufus_get`：

默认题库模式：

```text
amazon_rufus_get(asin="B0TEST1234", country="US", skills_dir=".agents/skills")
```

单题临时问题：

```text
amazon_rufus_get(asin="B0TEST1234", country="US", question="这个商品适合送礼吗？")
```

多题临时问题：

```text
amazon_rufus_get(
  asin="B0TEST1234",
  country="US",
  questions=["这个商品适合送礼吗？", "差评主要集中在哪些方面？"]
)
```

## opscli 兼容获取入口

如果当前宿主没有暴露 `amazon_rufus_get`，可改用正式 CLI 的本机 Chrome CDP 获取入口；MCP 默认链路仍保持后端/headless 获取，不把 CDP 参数暴露给 MCP。

默认题库模式：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --launch-if-needed
```

单题临时问题：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" -q "这个商品适合送礼吗？"
```

多题临时问题：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" -q "这个商品适合送礼吗？" -q "差评主要集中在哪些方面？"
```

显式指定 Chrome 可执行文件：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --launch-if-needed --chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

CLI 成功时只提取报告文件路径作为最终输出；不要展示完整 JSON、seed request、headers、cookie、localStorage、`storage_state` 或 upload payload。

## Rufus 上传接口配置

Rufus 获取链路默认只构造内部 `upload_payload`，不会主动发送上传接口。CLI 只有显式传入 `--submit-upload` 时才会调用 Rufus 上传接口；MCP 默认不上传。

上传 path 固定在 opscli 代码中：

```http
POST /v1/rufus/upload
```

前缀域名/base URL 复用 opscli 的 ops 系统地址配置：

```ini
# ~/.config/opscli/config.ini
[systems]
ops_url = https://ops.api.xenkee.com/api
```

也可在项目 `.env` 中覆盖：

```text
OPSCLI_OPS_URL=http://127.0.0.1:8000/api
```

实际上传地址为 `{ops_url}/v1/rufus/upload`。

显式上传示例：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --submit-upload
```

上传请求由 opscli 自动附带 ops 登录态；不要把 cookie、headers、payload 或完整请求材料交给 Skill 或 MCP 参数。

## 三类 MCP 错误的登录态刷新

以下错误统一进入一次 CDP 登录态刷新：

```text
RUFUS_HEADLESS_REQUEST_ERROR
RUFUS_HEADLESS_CAPTURE_ERROR
RUFUS_SECRET_NOT_READY
```

`RUFUS_HEADLESS_REQUEST_ERROR` 的 message 可能是 `Rufus 请求失败: 403`。此时不要把 403 当作 MCP 服务不可用，也不要直接重复调用 `amazon_rufus_get`；按授权或页面上下文失效处理，进入一次登录态刷新。

### 登录态刷新状态

本状态只存在于当前 Skill 调用内：

```text
login_recovery_attempted=false
```

首次进入登录态刷新时立即设置：

```text
login_recovery_attempted=true
```

该状态不得写入 Skill 目录、报告、`output/` 或 feedback。它只用于防止同一次 Skill 调用无限打开登录窗口。

### 登录态刷新步骤

1. 保留原始 ASIN、国家站点、`question`、`questions` 和 `skills_dir`。
2. 先清理旧 Rufus 登录态：

```powershell
opscli amazon-rufus logout <COUNTRY> --pretty
```

3. `logout` 成功后再执行登录页监听和 streaming seed 捕获：

```powershell
opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed
```

4. `watch-login` 会阻塞等待用户在打开的目标国家站点 Amazon 窗口完成登录，并自动打开目标 ASIN 商品页监听页面请求。
5. 捕获 `/rufus/cl/streaming` 后，CLI 自动保存本地明文状态（敏感）和内部请求种子。
6. `watch-login` 成功后，按原问题来源重新调用 `amazon_rufus_get`；MCP 后端优先使用保存的请求种子请求 Rufus。

默认题库模式：

```text
amazon_rufus_get(asin="B0TEST1234", country="US", skills_dir=".agents/skills")
```

单题临时问题：

```text
amazon_rufus_get(asin="B0TEST1234", country="US", question="这个商品适合送礼吗？")
```

多题临时问题：

```text
amazon_rufus_get(
  asin="B0TEST1234",
  country="US",
  questions=["这个商品适合送礼吗？", "差评主要集中在哪些方面？"]
)
```

如果自动发现 Chrome 失败，再询问用户 Chrome 可执行文件路径，并在 `watch-login` 中复用：

```powershell
opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed --chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

### 二次失败处理

如果登录态刷新后仍返回任意错误，或者再次命中上述三类错误，不再触发第二次登录。建议提示：

```text
本次 Skill 调用已触发过一次登录态刷新，仍未成功；为避免重复登录循环，不再打开第二次登录窗口。错误：<ERROR_CODE>: <message>
```

不要把多个问题拼成一个长字符串，不要在恢复路径改跑默认题库，不要输出 cookie、localStorage、`storage_state`、headers、seed request 或 upload payload。

## 输出要求

MCP 工具成功时返回 `report_path`。完整答案报告写入运行目录下的 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。

### 报告新鲜度约束

最终回复用户时只展示本次 `report_path`。如需正文，只读取本次工具返回的 `report_path` 指向的 Markdown 文件。

禁止仅凭 ASIN 在 `output/amazon-rufus/` 中读取任意 `<ASIN>-*.md` 历史报告，也不要使用 IDE 当前打开文件或上一轮对话遗留路径作为本次结果。

登录恢复后重新调用 `amazon_rufus_get` 成功时，必须使用重试成功响应中的最新 `report_path` 覆盖旧路径；如果无法确认本次 `report_path`，直接报错，不用历史报告兜底。

仅当当前宿主没有暴露 `amazon_rufus_get`、必须使用 CLI 兼容入口时，优先从本次 CLI 输出中提取报告路径。若本次 CLI 输出未包含路径，才允许按文件名时间戳和 mtime 选择同 ASIN 最新报告；无法唯一确认时必须停止。

除非用户明确要求排障，不输出：

- `seed_request`
- `upload_payload`
- headers
- cookie
- localStorage
- `storage_state`
- 完整原始 JSON
