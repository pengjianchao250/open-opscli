# Rufus 打开 Amazon 页面不打开控制台 - PRD

## 背景

Rufus Skill 登录采集会打开 Amazon 页面供用户完成登录并捕获 `/rufus/cl/streaming` 请求。当前用户反馈打开 Amazon 页面时会同时打开控制台，影响登录和采集体验。

## 目标

1. opscli 自动启动 Rufus 调试 Chrome/Edge 时，不自动打开 DevTools/Console。
2. 已存在 opscli Rufus profile 时，也应尽量避免历史 DevTools 偏好导致新页面打开控制台。
3. 不破坏 Amazon 登录态、Rufus seed request 和本地加密状态。
4. 不影响用户自己手动打开并连接的 CDP Chrome。
5. 用单元测试固定行为，避免后续加入调试 flag 时回归。

## 非目标

1. 不关闭用户已经手动打开的 DevTools。
2. 不删除整个 Chrome profile。
3. 不改 MCP `amazon_rufus_get` schema。
4. 不新增 UI 或交互式开关。
5. 不改 Rufus 问题、报告、题库、远程授权和回答质量重试逻辑。

## 功能需求

### FR-1 启动参数禁止自动打开 DevTools

`BrowserAttachService._start_new_chrome()` 启动 Chrome/Edge 时不得包含：

```text
--auto-open-devtools-for-tabs
```

现有测试应继续保留。

### FR-2 启动前清理 opscli 自建 profile 的 DevTools 自动打开偏好

在 `_start_new_chrome()` 为当前 `cdp_url` 解析出 profile 目录后，启动前清理该 profile 中可能导致 DevTools 自动打开的偏好。

清理范围限定在：

```text
~/.opscli/chrome-profiles/amazon-rufus-<port>
```

不得处理用户默认 Chrome profile。

### FR-3 保留登录态与 Rufus 状态

清理逻辑不得删除：

1. Cookies
2. Local Storage
3. IndexedDB
4. 当前 profile 目录本身
5. Rufus 本地加密状态文件

### FR-4 外部 CDP 不强制修改

如果 `cdp_url` 已可用，`_ensure_cdp_ready()` 不会调用 `_start_new_chrome()`，因此不应修改该外部浏览器 profile。

### FR-5 错误处理保持宽容

清理 DevTools 偏好失败时，不应阻断 Rufus 登录采集。最多忽略该偏好清理失败，继续启动 Chrome，避免引入新失败点。

## 验收标准

1. 单元测试验证启动参数不包含 `--auto-open-devtools-for-tabs`。
2. 单元测试构造 profile 偏好文件，验证启动前会移除 DevTools 自动打开偏好。
3. 单元测试验证 cookies 或其他无关 profile 数据不会被删除。
4. 单元测试验证偏好文件不存在或 JSON 异常时不会导致启动失败。
5. `uv run pytest tests/amazon_rufus/test_core.py -k "devtools or start_new_chrome" -v` 通过。
6. 若可行，执行 `uv run opscli amazon-rufus watch-login <ASIN> US --no-launch-if-needed --pretty` 以外的无浏览器单元验证；不在自动测试中打开真实 Amazon 页面。

## 用户价值

用户在 Rufus 登录采集时只看到必要的 Amazon 页面，不再被控制台打断；同时保留现有登录态与采集稳定性。

