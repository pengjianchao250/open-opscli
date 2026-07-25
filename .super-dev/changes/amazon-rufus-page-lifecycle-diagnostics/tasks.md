# Tasks

## 1. RED 测试

- [x] 添加测试：开启 `OPS_RUFUS_DEBUG_PAGES=1` 时，`watch_login_and_capture_seed_request()` 记录 page 创建和关闭事件。
- [x] 添加测试：诊断日志中的 URL 不包含 query，避免泄露敏感参数。
- [x] 添加测试：`wait_for_timeout()` 抛出页面关闭异常时，返回稳定 `SeedRequestNotCapturedError`。
- [x] 运行定向测试，确认新测试在当前实现下失败。

## 2. GREEN 实现

- [x] 在 `BrowserAttachService` 内增加环境变量控制的页面生命周期诊断。
- [x] 为 opscli 自己创建的 `login_page` 和 `product_page` 标记来源。
- [x] 捕获页面关闭类异常并转换为 `SeedRequestNotCapturedError`。
- [x] 保持默认输出安静，未开启环境变量时不输出诊断日志。

## 3. 验证

- [x] 运行新增定向测试。
- [x] 运行 `tests/amazon_rufus/test_core.py` 中 Rufus 相关回归。
- [x] 编译检查 `opscli/amazon_rufus/services/browser.py`。
