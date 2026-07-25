# Amazon Rufus watch-login 浏览器反复打开/关闭问题诊断

## 背景

用户反馈：执行 Rufus 登录采集时，工具会打开浏览器，先出现一个空白页，再打开 Amazon 页面；Amazon 页面会停留，但随后另一个页面似乎反复打开后关闭。补充说明后确认：现象不是整个浏览器反复关闭。

此前曾观察到类似错误：

```text
Page.wait_for_timeout: Target page, context or browser has been closed
```

本次仅做代码阅读、内存替身复现和原因定位；未运行会打开真实浏览器的命令，未修改业务代码。

## 事实链

### CLI 调用链

1. `opscli amazon-rufus watch-login` 入口在 `opscli/amazon_rufus/commands/cli.py`。
2. CLI 入口调用 `RufusManager.watch_login(...)`。
3. `RufusManager.watch_login(...)` 标准化 ASIN、国家站点并构造商品页 URL。
4. 实际浏览器控制在 `BrowserAttachService.watch_login_and_capture_seed_request(...)`。
5. 循环等待逻辑最终调用 `_wait_page_or_sleep(active_page, ...)`。

关键文件：

- `E:/code/work/open-opscli/opscli/amazon_rufus/commands/cli.py:157`
- `E:/code/work/open-opscli/opscli/amazon_rufus/services/manager.py:127`
- `E:/code/work/open-opscli/opscli/amazon_rufus/services/browser.py:99`

### watch-login 内部页面行为

`watch_login_and_capture_seed_request()` 内部只会：

1. `_start_new_chrome()` 启动 Chrome/Edge 时不传 URL，因此浏览器自身会出现一个空白初始页。
2. 创建一个 Amazon 登录/首页页签：`browser.py:177`
3. 在检测到登录后创建一个商品页页签：`browser.py:202`
4. 用 `product_page_opened` 防止同一次调用内重复创建商品页：`browser.py:201`
5. 在循环末尾等待当前 `active_page`：`browser.py:210`

因此，从该函数本身看，“同一次 watch-login 内无限打开商品页”不成立。

### 可见页签反复打开/关闭的排查结果

按 Python 源码静态检查，`watch-login` 直接链路里没有循环执行 `context.new_page()` 后再 `page.close()` 的代码。

存在 `new_page()` 后关闭 page 的链路有两类：

1. `BrowserAttachService.capture_seed_request()`：旧 CDP 可见捕获链路，创建一个可见 page，但当前 `amazon-rufus get-backend` 和 MCP `amazon_rufus_get` 默认不走这条路径。
2. `HeadlessRufusCaptureService._capture_seed_request_with_page_retry()`：headless 捕获链路，最多重开页面 3 次并关闭 page，但它使用 `headless=True`，正常不应该在用户可见浏览器中出现页签。

因此，用户描述的“Amazon 页停留，另一个页签反复打开又关闭”目前不能直接归因于 `watch-login` Python 代码主动循环关闭页签。更可能的方向是：

- Amazon 页面脚本或登录流程自己打开并关闭辅助页签。
- 外层 Agent/脚本多次调用 `watch-login` 或旧 CDP 可见捕获链路。
- 共享 `http://127.0.0.1:9222` 的另一个进程同时操作同一浏览器上下文。
- 当前页面事件没有日志，导致我们无法知道反复打开/关闭的页签 URL 和 opener。

### close-browser 的真实作用

`--close-browser` 只在函数退出的 `finally` 中生效：

- `browser.py:212`
- `browser.py:321`

并且只在 `launched_by_service=True` 时关闭本次由 opscli 自动启动的调试浏览器。它不是循环体里的关闭动作。

### 受控复现

使用内存替身模拟 Playwright 页面关闭，不启动 Chrome、不访问 Amazon：

```text
RuntimeError
Page.wait_for_timeout: Target page, context or browser has been closed
```

这证明当前代码会把 Playwright 的页面关闭异常原样冒泡到 CLI，CLI 再包装为泛化 `RUFUS_ERROR`，而不是转换成受控的 Rufus 业务错误。

## 根因判断

修正后的判断：`active_page` 被关闭仍是一个真实代码缺口，但它解释的是 `Page.wait_for_timeout: Target page... closed` 这类错误，不足以解释“另一个可见页签反复打开并关闭”。

关键代码：

```python
self._wait_page_or_sleep(active_page, min(self._remaining_ms(deadline_at), 1000))
```

`_wait_page_or_sleep()` 当前实现：

```python
wait_for_timeout = getattr(page, "wait_for_timeout", None)
if callable(wait_for_timeout):
    wait_for_timeout(max(int(timeout_ms), 1))
    return
time.sleep(max(int(timeout_ms), 1) / 1000)
```

已确认的问题点：

1. 没有检查 `page is None`。
2. 没有检查 `page.is_closed()`。
3. 没有识别 `Target page, context or browser has been closed`。
4. 关闭错误会中断 `watch-login`，随后 `finally` 因 `--close-browser` 可能关闭整个由 opscli 启动的浏览器。

尚未确认的问题点：

1. 反复开关的页签到底是什么 URL。
2. 页签由 opscli 的 `context.new_page()` 创建，还是由 Amazon 页面脚本、浏览器或外部进程创建。
3. 页签关闭是页面自关、用户/浏览器关闭，还是 Playwright/外部进程关闭。

## 可能诱因

### 诱因一：当前页被外部关闭

可能来自：

- 用户手动关闭页面或浏览器。
- Amazon 登录流程跳转时关闭/替换当前页。
- 另一个共享同一 `cdp_url` 的进程关闭了调试浏览器。
- 系统或浏览器策略终止页面。

### 诱因二：登录检测偏激进

登录检测逻辑：

- `browser.py:459`
- `browser.py:473`

当前把 `sso-state-main` 或 `at-main` 视为登录 Cookie。若某些未完全登录状态下也存在这些 Cookie，工具可能过早打开商品页，随后长期等待 `/rufus/cl/streaming`。这一点需要真实浏览器状态验证，静态分析暂列为次要诱因。

### 诱因三：另一个链路的 headless 页面重试造成“反复打开”观感

`get-backend` 的 headless 捕获有明确页面重开重试：

- `opscli/amazon_rufus/services/headless_capture.py:119`
- `opscli/amazon_rufus/services/headless_capture.py:204`

它会在同一上下文内最多重开商品页 3 次，每次 finally 关闭页面。但由于它是 `headless=True`，正常不应表现为用户可见浏览器页签反复打开/关闭。若用户能看见页签，则应优先排查旧 CDP 可见捕获链路或浏览器页面事件。

## 下一步诊断建议

先不要直接修复业务逻辑。应先在 `BrowserAttachService.watch_login_and_capture_seed_request()` 中加临时或受环境变量控制的页面生命周期诊断：

1. 监听 `context.on("page", ...)`，记录新页签创建时间、初始 URL。
2. 对每个 page 监听 `page.on("close", ...)`，记录关闭时最后 URL。
3. 在 opscli 自己调用 `context.new_page()` 前后记录来源标签，例如 `login_page`、`product_page`。
4. 日志默认不输出敏感信息，只输出 page id、URL host/path、时间和来源。

有了这组证据后，才能判断是：

- opscli 自己重复创建页签；
- Amazon 页面脚本打开/关闭辅助页签；
- 外层多次调用；
- 或共享 CDP 的其他进程干扰。

## 测试缺口

已有测试覆盖：

- 成功捕获 streaming request。
- `--close-browser` 在 Playwright 生命周期内关闭浏览器。
- CLI/MCP 参数透传。

缺失测试：

- `active_page.wait_for_timeout()` 抛出 `Target page, context or browser has been closed` 时，应转换成受控 `SeedRequestNotCapturedError` 或专门的 Rufus 错误。
- `active_page.is_closed()` 为 true 时，应选择仍然打开的页面、重新创建页面或受控退出。
- 多个 `watch-login` 共享默认 `http://127.0.0.1:9222` 时，不应互相关闭正在使用的浏览器。

## 最小修复建议

建议先按最小原则修复，不扩大重构：

1. 在 `_wait_page_or_sleep()` 中识别关闭页面：
   - 若 `page is None`，直接 sleep。
   - 若 `page.is_closed()` 返回 true，直接 sleep 或向上返回“页面已关闭”状态。
   - 捕获 Playwright 关闭类异常，将其转为 `SeedRequestNotCapturedError`，错误信息说明“监听页面或浏览器已关闭，请重新执行 watch-login”。

2. 在主循环中维护有效 `active_page`：
   - 每轮从 `context.pages` 过滤未关闭页面。
   - 如果 `active_page` 已关闭，优先切换到最后一个仍然打开的页面。
   - 如果没有可用页面，受控退出，避免继续等待已关闭句柄。

3. 补一条 RED/GREEN 单测：
   - 模拟 `wait_for_timeout()` 抛出页面关闭异常。
   - 期望不是裸 `RuntimeError`，而是稳定 Rufus 错误码。

4. 如需进一步防止并发互相关闭：
   - 给 `watch-login` 增加 per-CDP profile lock。
   - 或使用每次调用独立 remote debugging port/profile。

## 结论

本次问题不是单纯的 `--close-browser` 误关循环。更准确地说：

1. `watch-login` 对 Playwright 页面/上下文被关闭的异常缺少受控处理，这是一个明确缺口。
2. 但用户补充的“Amazon 页停留，另一个页签反复打开并关闭”目前不能由 `watch-login` 静态代码直接解释。
3. 下一步应先增加页面生命周期诊断，抓到反复打开/关闭页签的 URL、创建来源和关闭来源，再决定修复点。

优先诊断点应放在 `BrowserAttachService.watch_login_and_capture_seed_request()` 的 `context.on("page")` 和 `page.on("close")`，而不是先改 CLI 入口或 Skill 文档。
