# amazon-rufus-login-state-loop Proposal

## 背景

当前 `amazon_rufus_get` 默认通过后端/headless 链路读取本地加密 `storage_state`，再派生 Cookie header 请求 Amazon Rufus。但生产代码没有把用户完成 Amazon 登录后的浏览器状态保存到本地的入口，导致 `RufusBrowserStateStore.save()` 只有测试覆盖，默认 MCP 链路容易卡在 `RUFUS_SECRET_NOT_READY`。

## 目标

1. 补齐登录态闭环：未登录或登录态不可用时，用户完成目标国家站点 Amazon 登录后，CLI 能捕获并加密保存 Playwright `storage_state`。
2. 让 MCP 获取复用保存状态：`amazon_rufus_get` 不接收明文 cookie，由服务层读取本地状态并派生 Cookie header。
3. 统一用户指引：推荐 `init --launch-if-needed -> save-state -> amazon_rufus_get`，不再把 `get --new-chrome` 作为默认路径。
4. `init` 暴露 `--chrome-path`，补齐 Chrome 自动发现失败时的恢复入口。

## 非目标

1. 不处理默认题库为空。
2. 不处理 `answer_count=0` 或空报告。
3. 不处理 Rufus 题库升级接口环境切换。
4. 不处理发布配置中 `ops-amazon-rufus` 是否进入公开产物。
5. 不在 MCP schema 暴露 cookie、localStorage、`storage_state` 或 CDP 参数。

## 方案

新增 `opscli amazon-rufus save-state <COUNTRY>`：

```text
opscli amazon-rufus init US --launch-if-needed
用户完成 Amazon 登录
opscli amazon-rufus save-state US
amazon_rufus_get(...)
```

实现边界：

1. `BrowserAttachService` 增加 `capture_storage_state()`，连接 CDP Chrome 并返回 Playwright `context.storage_state()`。
2. `RufusManager` 增加 `save_state()`，解析国家站点并调用 `RufusBrowserStateStore.save()` 加密保存。
3. CLI 增加 `save-state` 命令，输出非敏感摘要。
4. CLI `init` 增加 `--chrome-path` 和 `--launch-if-needed/--no-launch-if-needed`。
5. 安装后指引、Skill 模板与已安装 Skill 文档同步为新流程。

## 验收

1. 测试证明 `save_state()` 会调用 store 保存 Playwright `storage_state`。
2. 测试证明 `save-state` CLI 输出不包含 cookie、localStorage、`storage_state` 明文。
3. 测试证明 `init --help` 暴露 `--chrome-path`。
4. 测试证明安装后指引不再推荐 `--new-chrome`，并包含 `save-state`。
5. Rufus 相关定向测试通过。
