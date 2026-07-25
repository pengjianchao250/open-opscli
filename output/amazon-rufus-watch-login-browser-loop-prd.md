# Amazon Rufus watch-login 浏览器关闭异常修复 PRD

## 问题

`opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser` 在监听 Amazon 登录和 Rufus streaming 请求时，可能出现：浏览器打开后保留一个空白页和一个 Amazon 页面，Amazon 页面停留，但另一个页签反复打开后关闭。

另有错误场景会返回底层 Playwright 错误：

```text
Page.wait_for_timeout: Target page, context or browser has been closed
```

该错误不可读，也会让用户误以为工具在主动循环关闭浏览器。

## 目标

1. 先抓取反复打开/关闭页签的创建来源、关闭事件和 URL 摘要。
2. 页面、上下文或浏览器被关闭时，CLI 返回稳定、脱敏、可理解的 Rufus 错误。
3. `watch-login` 不再对已关闭的 `active_page` 调用 `wait_for_timeout()`。
4. `--close-browser` 只保留“本次由 opscli 自动启动的调试浏览器退出后关闭”的语义，不扩大关闭范围。
5. 保持现有登录采集与 streaming request 保存流程不变。

## 非目标

1. 不重构整个 Rufus 浏览器控制层。
2. 不改变 MCP/CLI 参数契约。
3. 不新增多次自动登录监听。
4. 不输出 cookie、headers、payload、storage_state 或 cURL 原文。

## 验收标准

1. 开启诊断时，能记录 page 创建与关闭事件，不输出 cookie、headers、payload 或登录态。
2. 模拟 `active_page.wait_for_timeout()` 抛出页面关闭异常时，测试应失败于当前实现，修复后通过。
3. CLI 错误不再暴露裸 `RuntimeError`。
4. 成功捕获 `/rufus/cl/streaming` 的既有测试继续通过。
5. `--close-browser` 关闭时序测试继续通过。
