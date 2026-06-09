# amazon-rufus-headless-auto-install Tasks

## 1. 测试先行

- [x] 在 `tests/amazon_rufus/test_core.py` 中新增自动安装并重试成功的测试。
- [x] 新增自动安装失败时的错误包装测试。
- [x] 新增安装后重试仍失败且不继续循环的测试。
- [x] 运行新增测试，确认先失败。

## 2. 实现

- [x] 在 `opscli/amazon_rufus/services/headless_capture.py` 中识别 Playwright 浏览器缺失异常。
- [x] 使用 `sys.executable -m playwright install chromium` 执行一次安装。
- [x] 安装后重试一次 `playwright.chromium.launch(...)`。
- [x] 自动修复失败时返回稳定业务错误与手动安装提示。

## 3. 验证

- [x] 运行 `uv run pytest "tests/amazon_rufus/test_core.py" -q`。
- [x] 运行 `uv run pytest "tests/mcp/test_amazon_rufus_tools.py" "tests/amazon_rufus/test_core.py" -q`。
- [x] 汇总行为、测试结果和剩余风险。
