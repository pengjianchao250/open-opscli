# Rufus 打开 Amazon 页面不打开控制台

## 背景

`opscli amazon-rufus watch-login` 会在 CDP 不可用时自动启动 opscli 自建 Rufus 调试 Chrome/Edge，并打开 Amazon 页面供用户登录。用户反馈打开 Amazon 页面时会自动打开控制台，影响登录和采集体验。

当前代码没有显式传入 `--auto-open-devtools-for-tabs`，但 opscli 复用固定 Chrome profile，旧 profile 中可能残留 DevTools 自动打开偏好，导致后续新页签继续打开控制台。

## 目标

1. opscli 自动启动 Rufus 调试 Chrome/Edge 时，不携带自动打开 DevTools 的启动参数。
2. 自动启动前清理 opscli 自建 Rufus profile 中的 DevTools 自动打开偏好。
3. 不删除 Chrome profile，不破坏 Amazon 登录态、Cookie、localStorage 或 Rufus seed request。
4. 不修改用户自己已经运行的 CDP Chrome。
5. 用单元测试固定行为，避免后续回归。

## 非目标

1. 不新增 CLI 参数。
2. 不关闭用户手动打开的 DevTools。
3. 不删除整个 Rufus Chrome profile。
4. 不修改 MCP `amazon_rufus_get` schema。
5. 不改 Rufus 题库、报告、登录态保存、问题重写或远程授权流程。

## 影响范围

- `opscli/amazon_rufus/services/browser.py`
- `tests/amazon_rufus/test_core.py`
- `docs/change-log-pending.md`

