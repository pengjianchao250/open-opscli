# Tasks

## 1. RED 测试

- [x] 增加测试：`_start_new_chrome()` 启动前会清理 opscli Rufus profile 中的 DevTools 自动打开偏好。
- [x] 增加测试：偏好清理不会删除无关字段。
- [x] 增加测试：偏好文件为非法 JSON 时不阻断 Chrome 启动。
- [x] 运行定向测试，确认新增测试在当前实现下失败。

## 2. GREEN 实现

- [x] 在 `BrowserAttachService` 中新增私有方法，清理 profile 的 DevTools 自动打开偏好。
- [x] 在 `_start_new_chrome()` 计算并创建 profile 后、调用 `subprocess.Popen()` 前执行清理。
- [x] 保持启动参数不包含 `--auto-open-devtools-for-tabs`。
- [x] 清理失败时保持宽容，不阻断浏览器启动。

## 3. 验证与记录

- [x] 运行 `uv run pytest tests/amazon_rufus/test_core.py -k "devtools or start_new_chrome" -v`。
- [x] 运行 `uv run python -m py_compile opscli/amazon_rufus/services/browser.py`。
- [x] 更新 `docs/change-log-pending.md`。
- [x] 检查 `git diff`，确认没有无关改动。
