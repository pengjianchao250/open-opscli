# amazon-rufus-headless-auto-install Proposal

## 背景

`amazon_rufus_get_remote` 的 headless 分支会调用 Playwright 启动 Chromium。当前环境中 Playwright Python 包存在，但对应版本的 `chromium_headless_shell` 未安装时，用户只会看到 `RUFUS_HEADLESS_CAPTURE_ERROR: 无法启动 headless Chromium`。

用户已确认：该场景不新增 CLI/MCP 参数，默认自动修复一次。

## 目标

1. 当 Playwright 明确提示浏览器二进制缺失时，自动执行一次当前解释器下的 `python -m playwright install chromium`。
2. 安装完成后只重试一次 headless Chromium 启动。
3. 成功后继续原有 Rufus seed 捕获流程。
4. 自动安装失败或重试失败时，保留 `RUFUS_HEADLESS_CAPTURE_ERROR`，并给出可执行的手动安装提示。

## 非目标

1. 不新增 `auto_install_browser`、`install_browser_if_needed` 等公开参数。
2. 不对所有 Chromium 启动失败都安装浏览器。
3. 不改 Rufus 请求、SSE 解析、报告生成、远程授权和 storage_state 保存流程。
4. 不在 Skill 目录放置安装脚本或获取脚本。

## 设计约束

1. 只在 `HeadlessRufusCaptureService` 内部处理该运行环境缺失问题。
2. 安装命令必须使用 `sys.executable`，避免安装到错误 Python 环境。
3. 自动安装只触发一次；重试失败不得继续循环。
4. 错误消息不得包含 cookie、storage_state、headers、seed request 或 upload payload。

## 验收

1. 单元测试覆盖缺浏览器时自动安装并重试成功。
2. 单元测试覆盖自动安装失败时返回 `RUFUS_HEADLESS_CAPTURE_ERROR` 和手动安装提示。
3. 单元测试覆盖重试失败时不会第三次启动。
4. `tests/amazon_rufus/test_core.py` 和 `tests/mcp/test_amazon_rufus_tools.py` 通过。
