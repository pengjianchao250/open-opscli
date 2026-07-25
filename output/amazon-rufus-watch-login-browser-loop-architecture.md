# Amazon Rufus watch-login 浏览器关闭异常修复架构

## 当前链路

```text
CLI watch-login
-> RufusManager.watch_login
-> BrowserAttachService.watch_login_and_capture_seed_request
-> while 循环监听页面 request
-> _wait_page_or_sleep(active_page)
```

## 已确认缺陷位置

`BrowserAttachService` 维护 `active_page`，但没有校验该页面是否仍可用：

- `active_page` 初始指向登录页。
- 登录检测成功后指向商品页。
- 每轮循环末尾直接等待 `active_page`。

当该页面被 Amazon 跳转流程、用户操作、外部进程或浏览器策略关闭时，`wait_for_timeout()` 抛出底层 Playwright 异常。

## 新现象的待确认点

用户补充的现象是：Amazon 页停留，另一个页签反复打开并关闭。这不能由当前 `watch-login` 静态代码直接解释，因为 `product_page_opened` 会阻止同一次调用内重复创建商品页。

需要先确认：

1. 反复打开的页签 URL。
2. 页签创建来源是 opscli、Amazon 页面脚本，还是外部共享 CDP 进程。
3. 页签关闭来源是页面自关、浏览器策略，还是 Playwright/外部进程。

## 诊断设计

### 页面生命周期事件

在 `BrowserAttachService.watch_login_and_capture_seed_request()` 内部增加受控诊断：

1. `context.on("page", handler)` 记录 page 创建。
2. `page.on("close", handler)` 记录 page 关闭。
3. opscli 自己创建页面时标记来源：`login_page`、`product_page`。
4. URL 输出做最小化，只保留 scheme、host、path，不输出 query、headers、payload。

### 开关方式

优先使用环境变量：

```text
OPS_RUFUS_DEBUG_PAGES=1
```

默认关闭，避免普通用户输出噪声。

## 修复设计草案

### 页面可用性检查

新增一个轻量内部方法，用于判断 page 是否可等待：

```text
_is_page_open(page) -> bool
```

逻辑：

1. `page is None` 返回 false。
2. 若存在 `page.is_closed()`，调用并取反。
3. 若检查方法自身失败，按不可用处理。

### active_page 恢复策略

在主循环等待前：

1. 从 `context.pages` 中筛选仍打开的页面。
2. 若 `active_page` 已关闭，切换到最后一个仍打开页面。
3. 若没有打开页面，抛出 `SeedRequestNotCapturedError`，提示监听页或浏览器已关闭。

### 等待异常归一化

`_wait_page_or_sleep()` 捕获关闭类异常，转换为 `SeedRequestNotCapturedError`。

识别文本：

- `Target page, context or browser has been closed`
- `Page.wait_for_timeout`

## 风险控制

1. 只改 `BrowserAttachService` 内部实现，不改变 CLI/MCP schema。
2. 不增加自动重开浏览器，避免违反同一次 Skill 调用最多触发一次 `watch-login` 的约束。
3. 测试用替身对象复现，不需要真实打开 Chrome。
4. 诊断日志必须脱敏，不输出 cookie、headers、payload、storage_state 或 cURL。
