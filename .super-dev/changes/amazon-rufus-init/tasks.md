# amazon-rufus-init Tasks

## 实现任务

- [x] 在 `BrowserAttachService` 中新增打开国家站点登录窗口的方法。
- [x] 在 `RufusManager` 中新增 `init(country, cdp_url)` 编排方法。
- [x] 在 `commands/cli.py` 中新增 `init` 子命令与稳定错误输出。
- [x] 补充 `amazon_rufus` 针对性单元测试。
- [x] 运行 `tests/amazon_rufus/test_core.py` 验证。

## 质量约束

- 复用现有 Chrome 启动参数，避免重复常量。
- `init` 不依赖题库、seed 捕获、replay 或上传 payload。
- 代码注释保持中文且简洁。
- 成功输出只包含 `请在新窗口中登录亚马逊`。
