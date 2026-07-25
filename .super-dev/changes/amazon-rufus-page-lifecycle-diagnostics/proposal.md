# Amazon Rufus 页面生命周期诊断

## 背景

`amazon-rufus watch-login` 真实现象是：浏览器打开后保留空白页和 Amazon 页，Amazon 页停留，但另一个页签反复打开并关闭。静态代码无法证明该页签由 `watch-login` 主循环主动创建或关闭。

## 目标

1. 为 `BrowserAttachService.watch_login_and_capture_seed_request()` 增加受环境变量控制的页面生命周期诊断。
2. 记录 page 创建、关闭和 opscli 主动创建页签的来源标签，帮助确认反复打开/关闭页签的来源。
3. 日志脱敏，只输出 page id、来源、事件、URL 摘要和时间，不输出 cookie、headers、payload、storage_state 或 cURL。
4. 将 Playwright 页面关闭错误转成稳定 Rufus 错误，避免裸 `RuntimeError` 泄漏给 CLI/MCP。

## 非目标

1. 不改变 `amazon_rufus_get` / `get-backend` 主流程。
2. 不新增自动重开浏览器或重复 `watch-login`。
3. 不修改 CLI/MCP 参数契约。
4. 不处理真实 Amazon 页面逻辑结论，先用诊断日志确认来源。

## 影响范围

- `opscli/amazon_rufus/services/browser.py`
- `tests/amazon_rufus/test_core.py`

