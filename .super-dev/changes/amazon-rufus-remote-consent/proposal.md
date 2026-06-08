# amazon-rufus-remote-consent Proposal

## 背景

`opscli amazon-rufus get` 当前在 Amazon 未登录时进入本机登录中断续跑。现在用户要求在未登录场景先询问是否同意远程获取 Rufus 数据：同意后打开 Amazon 页面、捕获 cookie/localStorage 并保存到本地，再调用已经存在的 Rufus 获取方法；不同意时保持现有本机流程。

## 范围

1. 新增 Amazon 浏览器状态捕获与本地保存能力，状态来源使用 Playwright `storage_state()`。
2. 新增 remote 获取编排入口，读取/保存的状态转为已有 headless Rufus 获取链路可用的 Cookie header。
3. CLI 在 `RUFUS_LOGIN_REQUIRED` 或 `SEED_REQUEST_NOT_CAPTURED` 时提示远程获取授权；用户不同意时返回现有错误并提示本机可能卡顿。
4. 更新 `ops-amazon-rufus` Skill/README 文档和变更记录。

## 非目标

1. 不接入真实账号池。
2. 不实现 Amazon 信用卡绑定状态校验。
3. 不把 cookie/localStorage 输出到报告、stdout 或错误 JSON。
4. 不替换已有本机 Chrome/CDP 默认流程。

## 验收标准

1. 用户同意远程获取时，会保存包含 cookies 和 origins/localStorage 的本地状态。
2. 远程获取调用已有 Rufus 获取链路，生成与当前报告 formatter 兼容的数据结构。
3. 用户不同意时不保存状态、不调用远程获取，并提示本机流程可能卡顿。
4. 现有 Amazon Rufus 测试继续通过。
