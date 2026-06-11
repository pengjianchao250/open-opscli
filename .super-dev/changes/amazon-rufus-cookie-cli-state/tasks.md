# amazon-rufus-cookie-cli-state Tasks

- [x] 1. 写失败测试
  - [x] 1.1 覆盖 `RufusCookieParser` 解析 Amazon Cookie header。
  - [x] 1.2 覆盖 `RufusManager.save_cookie()` 加密保存状态且结果脱敏。
  - [x] 1.3 覆盖 `RufusManager.cookie_status()` 读取状态摘要。
  - [x] 1.4 覆盖 CLI `cookie save --from-stdin` 与 `cookie status`。
  - [x] 1.5 覆盖 `RufusBackendSecretProvider` 读取 cookie mock 状态。
  - [x] 1.6 覆盖 MCP schema 仍排除 cookie/CDP 参数。
  - [x] 1.7 覆盖 Skill 文档不包含明文 cookie 示例且包含 CLI cookie mock 流程。

- [x] 2. 实现 CLI cookie mock 状态能力
  - [x] 2.1 新增 `RufusCookieParser`。
  - [x] 2.2 `RufusManager` 新增 `save_cookie()` 与 `cookie_status()`。
  - [x] 2.3 CLI 新增 `amazon-rufus cookie save/status` 子命令。
  - [x] 2.4 确保 CLI 输出 GBK 兼容且不泄露敏感字段。

- [x] 3. 同步 Skill 与文档
  - [x] 3.1 更新模板 Skill `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md`。
  - [x] 3.2 同步 `.agents/skills/ops-amazon-rufus` 副本。
  - [x] 3.3 追加 `docs/change-log-pending.md`。

- [ ] 4. 验证与真实流程
  - [x] 4.1 运行 Rufus/Skill/MCP 定向测试。
  - [x] 4.2 使用 `opscli skills install ops-amazon-rufus --force --skills-dir ".agents/skills"` 安装 Skill。
  - [x] 4.3 用用户提供的 cookie 通过 CLI mock 保存本地状态。
  - [x] 4.4 开启子 agent，按固定提示词真实调用 `$ops-amazon-rufus`。
  - [ ] 4.5 检查报告路径、答案数量和敏感字段过滤。（阻塞：当前 Amazon 页面显示未登录，等待用户完成登录后继续 `save-state US` 与 MCP 重试。）

- [x] 5. 登录页监听与 streaming 请求种子捕获
  - [x] 5.1 更新架构文档，明确 CLI 监听登录页、自动检测登录完成、捕获 `/rufus/cl/streaming` 的边界。
  - [x] 5.2 写失败测试：状态存储支持加密保存 streaming seed，provider 可读取脱敏后的内部请求材料。
  - [x] 5.3 写失败测试：`RufusManager.watch_login()` 调用浏览器监听并保存 storage_state 与 seed。
  - [x] 5.4 写失败测试：CLI `watch-login` 输出脱敏摘要，不输出 cookie、headers、payload 或 storage_state。
  - [x] 5.5 实现 `BrowserAttachService.watch_login_and_capture_seed_request()`，连接 CDP、监听页面请求、登录完成后打开商品页。
  - [x] 5.6 实现 `RufusManager.watch_login()` 与 CLI `opscli amazon-rufus watch-login <ASIN> <COUNTRY>`。
  - [x] 5.7 同步 Skill/README/reference，把登录恢复主路径切到 `watch-login -> amazon_rufus_get`。
  - [x] 5.8 运行定向测试、重新安装 Skill，并执行可行的 CLI smoke。

- [x] 6. 保存 curl_data 并让 MCP 后端优先复用
  - [x] 6.1 参考 `extension/python/app/contexts/rufus/application/account_runner.py`，把本地加密状态结构对齐 `ParsedCurlRufusRequest.to_dict()`。
  - [x] 6.2 写失败测试：保存 streaming seed 时写入 `curl_data.url/headers/cookies/payload_template`。
  - [x] 6.3 写失败测试：provider 优先从 `curl_data` 读取 cookies/header/payload，而不是仅从 storage_state 派生。
  - [x] 6.4 写失败测试：MCP 后端同 ASIN seed 复用路径把 `curl_data` 传给 Rufus 请求 client。
  - [x] 6.5 实现 `RufusBrowserStateStore` 保存 normalized curl_data。
  - [x] 6.6 实现 `RufusBackendSecretProvider` 优先读取 curl_data，兼容旧字段。
  - [x] 6.7 同步 Skill/README/reference 文档，说明保存的是加密 curl_data，不输出完整 curl。
  - [x] 6.8 运行 Rufus/MCP/Skill 回归、安装 Skill、扫描敏感信息。

- [x] 7. 平台 Cookie content 远端读写 CLI
  - [x] 7.1 RED：Transport POST/GET 测试，确认保存只发送 `platform/country/content`，读取只按 `platform` 查询。
  - [x] 7.2 RED：Browser state store 测试，确认完整 Rufus record 可通过远端 `content` 往返并被 provider 读取。
  - [x] 7.3 RED：CLI 测试，确认 `platform-cookie save/get <PLATFORM> <COUNTRY>` 参数透传和 JSON 输出。
  - [x] 7.4 GREEN：实现 `RufusTransportClient.save_platform_cookie()` / `get_platform_cookie()`。
  - [x] 7.5 GREEN：实现 `RufusBrowserStateStore` 远端 content 适配、`RufusManager.save_platform_cookie()` / `get_platform_cookie()` 和 CLI 子命令。
  - [x] 7.6 同步 Skill 模板、`.agents` 副本、Super Dev 文档和待归档变更记录。
  - [x] 7.7 运行 Rufus/Skill/MCP 定向回归和必要 CLI help 冒烟。

- [x] 8. 默认状态读写替换本地 browser-state JSON
  - [x] 8.1 RED：新增默认 `RufusManager.save_cookie()` / `cookie_status()` 测试，确认只调用线上平台 Cookie content，不创建 `browser-state-<COUNTRY>.json`。
  - [x] 8.2 RED：新增默认 `RufusManager.get_backend()` 测试，确认从线上 content 恢复 `seed_request` 和 cookie。
  - [x] 8.3 GREEN：默认 `RufusManager` 和独立 `RufusBackendSecretProvider` 创建注入 `RufusTransportClient` 的线上 store。
  - [x] 8.4 保留显式 `RufusBrowserStateStore(base_dir=...)` 本地 JSON fallback，并将相关测试命名为 `local_fallback`。
  - [x] 8.5 文档：同步 Skill/README/reference 与架构/PRD，删除默认流程依赖 `browser-state-<COUNTRY>.json` 的描述。
