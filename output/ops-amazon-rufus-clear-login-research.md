# ops-amazon-rufus 登录恢复增强 Research

## 背景

本轮需求不是单独新增 Rufus logout，而是优化 Rufus Skill 在 MCP 获取失败后的登录恢复链路：

1. 用户在 Amazon 登录后可能跳转到站点首页；CLI 需要识别“已登录”状态，自动打开原 ASIN 商品页，并继续拦截 `/rufus/cl/streaming`。
2. 当 `amazon_rufus_get` MCP 获取失败并需要进入当前登录恢复流程时，恢复前先执行清空登录命令，避免旧的本地状态或 opscli-owned Chrome profile 干扰重新授权。

## 本地代码证据

### MCP 默认链路

```text
opscli/mcp/tools/amazon_rufus.py
  -> amazon_rufus_get(...)
  -> RufusManager.get_backend(...)
  -> RufusBackendSecretProvider.load(country)
  -> RufusBrowserStateStore.load(country)
```

MCP 默认不打开可见浏览器，也不接收 cookie、headers、storage_state、payload template 等敏感入参。失败后只能由 Skill 编排 CLI 登录恢复。

### 当前登录恢复能力

```text
opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed
  -> RufusManager.watch_login(...)
  -> BrowserAttachService.watch_login_and_capture_seed_request(...)
```

`watch_login_and_capture_seed_request()` 已有核心闭环：

1. 连接或启动 CDP Chrome。
2. 打开目标国家站点首页 `marketplace_url`。
3. 监听已有页和新页的 request。
4. 循环检查 Amazon 登录态；满足 `#nav-tools` 内容判定或指定 Cookie key 判定任一条件时，打开目标商品页 `page_url`。
5. 在目标商品页继续捕获 `/rufus/cl/streaming` 请求。
6. 捕获首个 `/rufus/cl/streaming` 请求并保存本地加密状态。

因此需求 1 的实现方向不是新增第二套登录监听，而是把“登录后跳首页 -> 通过 `#nav-tools` 或登录 Cookie key 判定已登录 -> 自动打开商品页 -> 继续捕获 streaming”固化为 Skill 规则、架构说明和回归测试。

### 登录判断修正

当前代码读取以下 Amazon 顶部账号区域选择器：

```text
#nav-link-accountList-nav-line-1
#nav-link-accountList .nav-line-1
```

用户反馈在当前 Amazon 页面上未看到这些元素。该反馈合理：当前应读取 `#nav-tools` 容器文本，而不是固定读取账号区域子节点。

新的登录成功判定为两个独立条件，满足任一条件即可认为登录完成：

1. `#nav-tools` 内容判定：读取 `#nav-tools` 的可见文本，检查是否仍出现“登录/Sign in/ログイン/Anmelden/Connexion”等未登录提示。若 `#nav-tools` 存在且未出现未登录提示，视为登录成功。
2. Cookie key 判定：当前目标站点 Cookie 中存在 `sso-state-main` 或 `at-main` 任一 key，视为登录成功。

`#nav-tools` 文案判断必须做 i18n，至少覆盖当前支持站点 US、UK、DE、JP。Cookie key 判定优先使用 Cookie 名称，不读取或输出 Cookie 值。

### 当前缺口

`ops-amazon-rufus` Skill 文档当前描述为：

```text
MCP 三类错误 -> watch-login -> 重新调用 amazon_rufus_get
```

缺少恢复前置清理：

```text
MCP 三类错误 -> logout -> watch-login -> 重新调用 amazon_rufus_get
```

如果不先清理，可能出现两个问题：

1. `RufusBrowserStateStore` 中旧的 seed/cookie 被下一次 MCP 继续读取。
2. opscli-owned Chrome profile 保留旧 Amazon 登录态，`watch-login` 可能直接复用旧身份，不符合“重新登录恢复”的用户预期。

## 外部技术依据

Playwright 官方事件文档说明可用 `page.on("request", ...)` 监听页面网络请求，也可通过 `browser_context.on("page", ...)` 发现新页面；这与当前 “注册已有页 + 注册新页 + 捕获 request” 的方向一致。来源：https://playwright.dev/python/docs/events

Playwright 官方认证文档将 `storage_state` 作为保存和复用浏览器认证状态的标准机制；本项目用 `context.storage_state()` 保存 Amazon cookie/localStorage，后续 MCP/headless 复用该状态符合该模型。来源：https://playwright.dev/python/docs/auth

Playwright BrowserContext API 文档提供 `storage_state()` 能力，用于返回当前 context 的 cookies 与 origins 状态。来源：https://playwright.dev/python/docs/api/class-browsercontext

## 推荐方案

### 方案 A：仅改 Skill 编排与文档

流程：

```text
amazon_rufus_get 失败
  -> login_recovery_attempted=false 时进入恢复
  -> opscli amazon-rufus logout <COUNTRY> --pretty
  -> opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed
  -> 原参数重试 amazon_rufus_get
```

优点：改动最小，不新增 MCP 破坏性工具，不把清理能力暴露到 MCP 默认工具面。

缺点：依赖 Agent 严格按 Skill 文档执行；需要同步模板版和安装版 Skill 文档。

### 方案 B：在 `watch-login` 内部自动清理

流程：

```text
watch-login --clear-before-login
```

优点：调用者更不容易漏掉清理步骤。

缺点：`watch-login` 当前职责是监听和捕获，内置清理会扩大命令职责；默认自动删 profile 属于破坏性文件操作，排障风险更高。

### 方案 C：新增 MCP 恢复工具

流程：

```text
amazon_rufus_recover_login(...)
```

优点：MCP 层可以一键恢复。

缺点：MCP 工具面会新增本地清理能力和可见浏览器流程，破坏现有“获取工具不暴露 CDP/敏感状态”的边界。

## 结论

采用方案 A。

原因：

1. KISS：只调整 Skill 编排规则，复用现有 `logout` 和 `watch-login`。
2. YAGNI：不新增 MCP 工具、不新增新 CLI 参数、不做跨国家批量清理。
3. DRY：清理仍由 `RufusManager.logout()`、`RufusBrowserStateStore.delete()` 和 `BrowserAttachService.clear_owned_profile()` 负责。
4. SOLID：Skill 只负责编排；CLI/service 继续负责具体清理和捕获。

## 风险与约束

1. `logout` 默认会删除 opscli-owned Chrome profile；若 Chrome 正在使用该 profile，可能失败。失败时不应继续假装进入“干净登录”，应提示用户关闭对应调试 Chrome 后重试。
2. `logout --no-browser-profile` 只能清理 MCP 后端状态，不能保证可见 Chrome 是干净登录；除非用户明确要求排障，不作为默认恢复路径。
3. 登录检测不能依赖 `#nav-link-accountList-nav-line-1` 或 `#nav-link-accountList .nav-line-1`。应改为读取 `#nav-tools` 内容并结合 i18n 未登录提示，同时检查 `sso-state-main` / `at-main` Cookie key；两类条件满足任一即可进入商品页捕获。
4. 捕获成功后的输出仍只能展示脱敏摘要和 `report_path`，不得泄露 cookie、headers、payload、storage_state 或 seed request。
