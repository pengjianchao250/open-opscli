# Rufus 打开 Amazon 页面不打开控制台 - Research

## 背景

用户要求 Rufus Skill 在打开 Amazon 页面时不要打开控制台。结合当前实现，该需求主要指 `opscli amazon-rufus watch-login` 或相关登录采集流程自动启动本机 Chrome/Edge 后，用户看到 Amazon 页面同时弹出 DevTools/Console 面板。

本轮处于 Super Dev research 阶段，只做事实核查与方案收敛，不修改代码。

## 本地实现事实

当前打开 Amazon 页面的主链路：

```text
opscli amazon-rufus watch-login
  -> RufusManager.watch_login
  -> BrowserAttachService.watch_login_and_capture_seed_request
  -> _ensure_cdp_ready
  -> _start_new_chrome
  -> playwright.chromium.connect_over_cdp
  -> context.new_page / page.goto(Amazon)
```

关键文件：

- `opscli/amazon_rufus/commands/cli.py`
- `opscli/amazon_rufus/services/manager.py`
- `opscli/amazon_rufus/services/browser.py`
- `tests/amazon_rufus/test_core.py`

`_start_new_chrome()` 当前启动参数包括：

```text
--remote-debugging-port=<port>
--user-data-dir=<profile_dir>
--no-first-run
--no-default-browser-check
```

当前代码没有显式传入：

```text
--auto-open-devtools-for-tabs
```

已有测试 `test_browser_start_new_chrome_does_not_auto_open_devtools` 只断言启动参数中不包含该 flag，但没有覆盖已有 profile 中保存的 DevTools 自动打开偏好。

## 可能原因

### 原因一：历史调试参数

如果用户此前手动用 `--auto-open-devtools-for-tabs` 启动过相同 profile，或外部命令复用同一 CDP profile，Chrome 可能继续表现为新页签自动打开 DevTools。

### 原因二：Profile 偏好残留

opscli 复用固定 profile：

```text
~/.opscli/chrome-profiles/amazon-rufus-<port>
```

Chrome 的 DevTools 偏好会写入 profile 下的偏好文件。即使本次启动参数不包含自动打开 DevTools 的 flag，旧 profile 偏好仍可能影响新打开的 Amazon 页面。

### 原因三：连接的是用户已有 CDP Chrome

当 `launch_if_needed=True` 且 `cdp_url` 已可用时，opscli 不会启动新 Chrome，而是直接连接现有 CDP。若现有浏览器本身处于 DevTools 自动打开状态，opscli 不应强行修改用户的日常浏览器配置。

## 外部资料核验

Playwright Python 文档说明 `connect_over_cdp` 用于通过 Chrome DevTools Protocol 连接已有 Chromium 浏览器，并可访问默认 browser context；这符合当前 Rufus watch-login 的实现方式。参考：https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp

Playwright 文档还说明持久化 browser profile 会保存 cookies、local storage 等浏览器状态，且不建议复用用户默认 profile；当前 opscli 使用独立 `user-data-dir` 的方向是正确的。参考：https://playwright.dev/python/docs/api/class-browsertype

Chrome 官方 remote debugging 安全变更要求 remote debugging 配合非默认 `--user-data-dir` 使用，支持继续使用 opscli 专用 profile。参考：https://developer.chrome.com/blog/remote-debugging-port

Chromium switch 列表包含 `--auto-open-devtools-for-tabs`，该 flag 会导致每个 tab 自动打开 DevTools；本需求应确保 opscli 自建 Chrome 不携带该 flag，并清理自建 profile 的相关偏好。参考：https://peter.sh/experiments/chromium-command-line-switches/#auto-open-devtools-for-tabs

## 方案判断

推荐采用“只治理 opscli 自建 Rufus profile”的最小方案：

1. `_start_new_chrome()` 启动前清理 opscli Rufus profile 中的 DevTools 自动打开偏好。
2. 启动参数继续不包含 `--auto-open-devtools-for-tabs`。
3. 不修改用户已有 CDP Chrome 的偏好，避免影响用户自己的浏览器。
4. 增加单元测试覆盖 profile 偏好清理，而不仅是参数断言。
5. 不新增 CLI 参数，不要求用户手动清 profile。

## 风险与边界

1. 不删除整个 profile，否则会丢失用户刚采集或维护的 Amazon 登录态。
2. 只改 DevTools 相关偏好键，其他 cookies、localStorage、seed request 状态不得触碰。
3. 如果用户主动连接一个已经打开 DevTools 的外部 Chrome，opscli 不应关闭其 DevTools。
4. 该变更只影响可见登录采集体验，不影响 MCP `amazon_rufus_get` 后端/headless 默认路径。

