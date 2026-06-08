# amazon-rufus-headless-page-retry Tasks

## 任务清单

1. [x] 在 `tests/amazon_rufus/test_core.py` 添加 headless 页面重开成功测试。
2. [x] 运行新增测试，确认失败原因是当前实现未重试页面。
3. [x] 在 `HeadlessRufusCaptureService` 中实现页面重开重试，最多 3 次。
4. [x] 追加 `docs/change-log-pending.md` 变更记录。
5. [x] 运行定向测试：`pytest tests/amazon_rufus/test_core.py -k "headless_capture" -v`。
6. [x] 运行 MCP Rufus 测试：`pytest tests/mcp/test_amazon_rufus_tools.py -v`。
7. [x] 检查 diff，确认无无关改动。
