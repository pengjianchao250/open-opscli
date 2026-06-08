# amazon-rufus-per-question-timeout Proposal

## 背景

`amazon_rufus_get` MCP 工具当前默认 `timeout_seconds=90`。虽然 `RufusManager.get_backend()` 会继续把该值传给 headless 捕获和每次 Rufus streaming 请求，内部链路已经支持更长超时，但默认预算没有表达“每个问题 3 分钟”的业务要求。多问题场景下，Rufus streaming 应按问题逐个请求，每题独立使用 180 秒预算，总内部等待上限随问题数线性增加。

同时，MCP Router 或调用宿主可能存在约 60 秒外层请求上限。内部默认超时只能保证 opscli 代码链路按每题 180 秒执行，不能绕过同步 MCP 调用宿主的外层截断；外层长任务需要后续异步 job/polling 架构支持。

## 范围

1. 将 Rufus 获取默认超时统一为 180 秒。
2. 确保 MCP `amazon_rufus_get`、`amazon_rufus_get_remote`、CLI `amazon-rufus get` 和 `RufusManager` 获取入口共享同一默认值。
3. 增加测试证明默认值传入 headless 捕获和 Rufus streaming client。
4. 增加测试证明 `HeadlessRufusClient.query()` 在多题时对每次 `_post_rufus()` 使用同一个单题超时值。
5. 更新 Skill reference，明确同步 MCP 外层超时风险。

## 非目标

1. 不实现异步任务队列、job_id、轮询或报告后台生成。
2. 不修改 Rufus secret、cookie、storage_state 的敏感数据边界。
3. 不改变问题模板、拒答重试、报告格式或 CDP 兼容路径。
4. 不尝试绕过 MCP Router/宿主外层请求超时。

## 验收标准

1. 默认调用 `amazon_rufus_get` 时传给 `RufusManager.get_backend()` 的 `timeout_seconds` 为 180。
2. 默认调用 `RufusManager.get_backend()` 时，headless 捕获和 streaming client 都收到 `timeout_seconds=180`。
3. 多题 `HeadlessRufusClient.query()` 每一题的 `_post_rufus()` 调用都收到同一个 `timeout_seconds`。
4. CLI 与远程授权 Rufus 获取入口默认值同步为 180。
5. 文档明确：内部每题 180 秒不等于同步 MCP 外层请求可等待完整总时长。
