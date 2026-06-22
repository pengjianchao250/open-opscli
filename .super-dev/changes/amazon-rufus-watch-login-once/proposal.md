# Amazon Rufus watch_login 单次触发与 DevTools 参数修复

## 背景

亚马逊 Rufus 登录态失效时，同一次 Skill 调用内的多个分支都可能调用 `amazon_rufus_watch_login`，造成浏览器页面反复打开和关闭。浏览器启动参数中还包含 `--auto-open-devtools-for-tabs`，会额外打开 DevTools 页签。

## 目标

1. 移除 Chrome/Edge 自动打开 DevTools 的启动参数。
2. 在 Skill 编排规范中新增 `watch_login_attempted=false` 状态。
3. 约束同一次 Skill 调用最多触发一次 `watch_login`，MCP 和 CLI 登录采集都计入。
4. 同步模板版 Skill、`.agents` 已安装副本、reference、README、Super Dev 文档和流程图。
5. 增加回归测试覆盖启动参数和文档契约。

## 非目标

1. 不新增全局进程锁。
2. 不改变 MCP Tool schema。
3. 不改变远程授权偏好、登录恢复错误码或 CLI fallback 白名单。
