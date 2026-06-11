# ops-amazon-rufus 登录恢复增强 PRD

## 需求概述

优化 `ops-amazon-rufus` Skill 在 MCP 获取 Rufus 失败后的恢复流程。失败恢复必须先清空当前国家站点的本地登录态，再引导用户完成 Amazon 登录；如果登录完成后 Amazon 跳回首页，CLI 应自动识别已登录状态，打开目标 ASIN 商品页，并继续捕获 `/rufus/cl/streaming` 请求。

## 目标

1. MCP 三类登录态相关错误进入恢复前，先执行本地清空登录命令。
2. `watch-login` 支持用户登录后停留或跳转到 Amazon 首页的场景。
3. 登录成功后自动打开原 ASIN 商品页，并继续拦截 Rufus streaming 请求。
4. 登录恢复仍限制为每次 Skill 调用最多一次。
5. 恢复成功后按原 ASIN、国家、问题来源重试 `amazon_rufus_get`。
6. 整个流程不展示 cookie、headers、payload、storage_state、seed request 或本地敏感文件内容。

## 非目标

1. 不新增 MCP logout 或 MCP recover 工具。
2. 不在 `watch-login` 中默认新增隐式清理参数。
3. 不清理用户默认 Chrome profile。
4. 不清理 opscli auth、ops JWT、MCP API key 或 CredentialStore。
5. 不实现 `--all` 国家批量清理。
6. 不新增图形界面。

## 用户故事

### US-1 MCP 失败后干净登录恢复

作为 Agent 使用者，当 `amazon_rufus_get` 返回 `RUFUS_HEADLESS_REQUEST_ERROR`、`RUFUS_HEADLESS_CAPTURE_ERROR` 或 `RUFUS_SECRET_NOT_READY` 时，我希望 Skill 先清理旧登录态，再打开登录窗口，避免旧状态反复失败。

期望流程：

```text
opscli amazon-rufus logout US --pretty
opscli amazon-rufus watch-login B0TEST1234 US --launch-if-needed
amazon_rufus_get(asin="B0TEST1234", country="US", ...)
```

### US-2 登录后跳转首页仍能继续

作为用户，我在 Amazon 登录完成后被跳转到站点首页，而不是商品页。此时 CLI 应通过 `#nav-tools` 内容或 `sso-state-main` / `at-main` Cookie key 判定登录成功，然后自动打开 `https://www.amazon.com/dp/<ASIN>`，继续监听并保存 Rufus streaming 请求。

### US-3 恢复失败不无限开窗口

作为用户，如果清理和登录恢复后再次失败，我希望 Agent 明确告诉我本轮已恢复过一次，不再重复打开第二个登录窗口。

## 功能需求

### FR-1 触发错误范围

以下 MCP 错误进入一次登录恢复：

```text
RUFUS_HEADLESS_REQUEST_ERROR
RUFUS_HEADLESS_CAPTURE_ERROR
RUFUS_SECRET_NOT_READY
```

`RUFUS_HEADLESS_REQUEST_ERROR` 中的 `403` 应按登录态或页面上下文失效处理，不直接重复调用 MCP。

### FR-2 恢复前置清理

当 `login_recovery_attempted=false` 且命中 FR-1 错误时，Skill 必须先执行：

```powershell
opscli amazon-rufus logout <COUNTRY> --pretty
```

要求：

1. 执行前保留原始 ASIN、国家、`question`、`questions`、`skills_dir`。
2. `logout` 成功后再执行 `watch-login`。
3. `logout` 输出只用于判断成功与摘要，不展示敏感字段。
4. 如果 `logout` 因 Chrome profile 被占用失败，停止恢复并提示用户关闭对应调试 Chrome 后重试；不要继续用非干净 profile 恢复。

### FR-3 首页登录成功判定

`watch-login` 必须覆盖以下场景：

1. 用户在首页点击登录并完成登录。
2. Amazon 登录后跳回首页。
3. 用户本来已经在目标国家站点登录。

判定规则：

1. 必须限定在原国家站点的 CDP context。
2. 不把任意 Amazon cookie 直接当作已登录凭据。
3. 不把 `#nav-link-accountList-nav-line-1`、`#nav-link-accountList .nav-line-1` 等固定 DOM selector 作为判断依据。
4. 读取 `#nav-tools` 容器文本，检查是否仍存在未登录提示。若 `#nav-tools` 存在且未出现未登录提示，视为登录成功。
5. 检查目标站点 Cookie 名称；若存在 `sso-state-main` 或 `at-main` 任一 key，视为登录成功。
6. 第 4 点和第 5 点满足任一即可判定登录成功。
7. `#nav-tools` 未登录提示词必须做 i18n，至少覆盖当前支持站点 US、UK、DE、JP。

建议未登录提示词包含但不限于：

```text
sign in
signin
log in
login
identifícate
identificate
identificarse
iniciar sesión
登录
登入
サインイン
ログイン
anmelden
einloggen
connexion
se connecter
```

### FR-4 自动打开商品页并继续捕获

判定登录成功后，`watch-login` 必须自动打开原 ASIN 商品页：

```text
build_product_url(<ASIN>, <COUNTRY>)
```

随后继续监听并捕获首个 `/rufus/cl/streaming` 请求。捕获成功后保存：

1. `storage_state`
2. 脱敏 headers
3. payload template
4. seed request 摘要

这些内容只能进入本地加密状态，不得进入 MCP 入参、报告正文或最终回复。

### FR-5 恢复后重试

`watch-login` 成功后，按原问题来源重试 `amazon_rufus_get`：

1. 单题：继续传 `question`。
2. 多题：继续传 `questions`。
3. 默认题库：继续传 `skills_dir=".agents/skills"`。

不能把多个问题拼成一个长字符串，也不能在恢复路径擅自切换为默认题库。

### FR-6 二次失败处理

如果本轮已经设置 `login_recovery_attempted=true`，或恢复后重试仍失败：

1. 不再执行第二次 `logout`。
2. 不再打开第二次登录窗口。
3. 返回原始错误 code 与脱敏 message。
4. 明确说明本轮已执行过一次登录恢复。

### FR-7 Skill 文档同步

本次确认后需要同步修改：

1. `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
2. `opscli/skills/templates/ops-amazon-rufus/references/rufus-mcp-workflow.md`
3. `.agents/skills/ops-amazon-rufus/SKILL.md`
4. `.agents/skills/ops-amazon-rufus/references/rufus-mcp-workflow.md`

模板版是内置安装来源，`.agents` 版是当前工作区安装态；两者必须保持同一流程规则。

## 验收标准

1. 文档明确 MCP 失败恢复顺序为 `logout -> watch-login -> amazon_rufus_get retry`。
2. 文档明确 `watch-login` 支持登录后跳首页，并自动打开商品页继续捕获 streaming。
3. 测试覆盖 `RufusManager.watch_login()` 传入原 ASIN、国家和商品页 URL。
4. 测试覆盖 `BrowserAttachService.watch_login_and_capture_seed_request()` 在固定账号导航 selector 不存在时，仍可通过 `#nav-tools` 内容或 `sso-state-main` / `at-main` Cookie key 判定登录成功并打开商品页。
5. 测试覆盖 `#nav-tools` 文案 i18n：US/UK/DE/JP 未登录提示应被识别为未登录。
6. Skill 文档和 reference 中不出现 cookie、headers、payload、storage_state、seed request 明文输出指引。
7. 不新增 MCP destructive 工具。
8. 如果只改 Skill 编排文档，不应改动 Rufus 获取核心请求协议。

## 体验原则

1. KISS：恢复路径只增加一个前置 `logout`，不重写登录捕获。
2. YAGNI：不新增 `recover` 命令、不做 `--all`。
3. DRY：复用现有 `logout` 和 `watch-login`。
4. SOLID：Skill 负责编排，CLI/service 负责清理与捕获，MCP 只负责获取报告。
