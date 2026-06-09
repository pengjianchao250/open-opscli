# ops-amazon-rufus 明文浏览器状态研究

## 背景

用户要求去掉 Rufus 本地 Amazon 登录态的加密，改为直接明文保存，核心目的有两个：

1. 登录态文件可以直接复制到其他机器或其他用户配置目录后复用。
2. MCP 获取 Rufus 失败后，恢复流程继续保持 `logout -> watch-login -> amazon_rufus_get`，重新捕获并保存最新状态。

当前实现位于 `opscli/amazon_rufus/services/browser_state_store.py`：

- 状态文件：`CONFIG_DIR/amazon-rufus/browser-state-<COUNTRY>.bin`
- 密钥文件：`CONFIG_DIR/amazon-rufus/.browser-state-key`
- 保存逻辑：`Crypto.encrypt(json.dumps(record))`
- 读取逻辑：`Crypto.decrypt(path.read_bytes())`
- 权限：写入后设置 owner read/write，即 `600`

## 外部资料结论

Playwright 官方认证文档说明，`storage_state` 会保存认证后的 cookies、localStorage，部分场景还包括 IndexedDB；这些状态可以被新 browser context 加载后直接进入已登录状态。因此 Rufus 保存的 `storage_state` 本质上就是可复用登录态快照。来源：https://playwright.dev/python/docs/auth

Playwright codegen 文档也明确 `auth.json` 会包含 cookies、localStorage 和 IndexedDB，并提醒只应本地使用，因为它包含敏感信息。来源：https://playwright.dev/python/docs/codegen

OWASP Session Management Cheat Sheet 把 session cookie / session id 视为可代表用户会话的敏感凭证。Rufus 本地状态中保存的 Amazon cookies 具备相同风险：文件泄露即可被他人尝试复用登录态。来源：https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html

## 本地代码观察

### 存储层

`RufusBrowserStateStore.save()` 当前加密保存完整 record：

- `country`
- `marketplace_origin`
- `captured_at`
- `storage_state`
- 可选 `curl_data`
- 可选 `streaming_url`
- 可选 `headers`
- 可选 `payload_template`
- 可选 `seed_request`

其中 `curl_data.cookies`、`storage_state.cookies` 和 `payload_template` 都是敏感字段。

### 读取层

`RufusBackendSecretProvider.load()` 从 store 读取 record 后：

- 优先使用 `curl_data.url/headers/cookies/payload_template`
- 没有 `curl_data` 时，从 `storage_state` 派生 Cookie header
- 不把 secret 暴露到 MCP 返回、报告或 feedback

### 输出层

`RufusManager.save_cookie()`、`save_curl()`、`watch_login()` 当前只返回摘要：

- `saved`
- `cookie_count`
- `origin_count`
- `streaming_request_saved`
- `has_payload_template`

这条输出脱敏边界必须保留。明文保存只改变磁盘文件内容，不改变 CLI/MCP 输出面。

## 登录态使用链路

Rufus 本地登录态不是单一命令使用，相关路径需要一起处理：

1. `opscli amazon-rufus save-state`：通过 CDP 捕获 Playwright `storage_state`，调用 `RufusManager.save_state()`，再写入 `RufusBrowserStateStore.save()`。
2. `opscli amazon-rufus watch-login`：用户登录后自动打开商品页，捕获 `storage_state` 和 `/rufus/cl/streaming` seed，调用 `RufusBrowserStateStore.save()`。
3. 底层调试入口 `opscli amazon-rufus cookie save`：把 stdin 传入的 Cookie header 转成最小 `storage_state`，调用 `RufusBrowserStateStore.save()`。
4. 底层调试入口 `opscli amazon-rufus curl save`：把 Copy-as-cURL 转成 `storage_state`、`curl_data` 和 `seed_request`，调用 `RufusBrowserStateStore.save()`。
5. `opscli amazon-rufus cookie status`：调用 `RufusBrowserStateStore.load()` 读取摘要，只返回脱敏状态。
6. MCP `amazon_rufus_get` 默认链路：`RufusManager.get_backend()` 调用 `RufusBackendSecretProvider.load()`，后者通过 `RufusBrowserStateStore.load()` 读取本地状态，再供 headless capture/client 使用。
7. `opscli amazon-rufus logout`：调用 `RufusBrowserStateStore.delete()` 清理本地状态，并可清理 opscli-owned Chrome profile。

因此新格式明文读写必须集中在 `RufusBrowserStateStore`，让 `RufusBackendSecretProvider`、`RufusManager`、CLI 和 MCP 继续依赖同一个存储抽象，避免每个入口自行处理状态文件路径。

## 需求取舍

### 采用明文 JSON

新文件建议使用：

```text
CONFIG_DIR/amazon-rufus/browser-state-<COUNTRY>.json
```

理由：

1. `.json` 明确表达文件可读、可复制、可审计。
2. 不再需要 `.browser-state-key`，复制单个国家文件即可复用。
3. 避免 `.bin` 文件名继续暗示加密或二进制格式。

### 不做旧密文兼容

按最新要求，代码不再处理 legacy `.bin` 密文：

1. `load(country)` 只读取 `browser-state-<COUNTRY>.json`。
2. `save(country)` 只写入 `browser-state-<COUNTRY>.json`。
3. `delete(country)` 只删除 `browser-state-<COUNTRY>.json`。
4. 不读取、解密、迁移或删除 `browser-state-<COUNTRY>.bin`。
5. 不读取、创建或删除 `.browser-state-key`。

如果用户本地只有旧 `.bin` 状态，新版本会视为没有可用 Rufus 状态，需要重新执行 `watch-login` 或 `save-state` 生成新的明文 JSON。

### 仍保留文件权限

即使明文保存，写入后仍设置 owner read/write：

```text
0600
```

这不是加密，只是降低同机其他账号读取风险。Windows 上权限语义可能弱化，但不影响主流程。

## 风险边界

明文状态文件泄露后，可能导致：

1. Amazon 登录态被复制复用。
2. Rufus streaming 请求 seed 被复用。
3. `curl_data.cookies`、`payload_template` 被直接读取。

必须继续禁止：

1. 在 MCP 参数中传入 cookie、headers、payload、storage_state。
2. 在 CLI/MCP 返回、报告、feedback 中输出 cookie、headers、payload、storage_state。
3. 把状态文件写入仓库、`output/` 或 `.agents/skills/`。
4. 在 Skill 文档中引导用户复制浏览器请求或粘贴 cookie。

## 研究结论

按用户目标，明文保存是可行的，但它是明确的安全降级。推荐最小实现：

1. `RufusBrowserStateStore` 移除 `Crypto` 依赖，不再加密保存，也不做旧密文迁移。
2. `save()` 写入 UTF-8 明文 JSON 文件。
3. `load()` 直接读取并解析 JSON。
4. 新文件名改为 `browser-state-<COUNTRY>.json`。
5. `load()` 在 `.json` 不存在时返回 `None`，不 fallback 到 `.bin`。
6. `save()`、`load()`、`delete()` 不处理 `.browser-state-key`。
7. CLI/MCP 输出脱敏不变。
8. Skill 文案从“本地加密状态”调整为“本地明文状态（敏感）”。
