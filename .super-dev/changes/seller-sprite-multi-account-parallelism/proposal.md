# Proposal: SellerSprite 多账号并行与故障接替

## Summary

将 SellerSprite 通用异步任务从单账号全局串行调度升级为进程内账号池调度：最多 4 个账号使用独立会话并行工作，账号数大于 1 时至少保留 1 个冷备用；工作账号明确认证失效后由备用账号接替，备用耗尽则关闭对应工作槽。

## Goals

1. 不同账号并行、同一账号串行。
2. 5 个账号形成 4 工作 + 1 冷备用。
3. 认证失败时有限重登、刷新和备用接替。
4. 无备用时只关闭故障槽，其他健康槽继续。
5. 使用 SQLite 账号级唯一约束与 generation CAS 防止晚到覆盖。
6. 登录失败同时写脱敏结构化日志和 SQLite 审计。
7. 保持现有 MCP ownership、quota、状态和导出接口兼容。

## Non-Goals

1. 不允许同账号多窗口并发。
2. Listing Analysis 不进入通用多账号池。
3. 不实现多服务进程共享账号池。
4. 不记录或持久化账号密码、Cookie、Token 和完整用户名。

## Public Test Seams

1. `SellerSpriteAccountProvider.list_accounts()`。
2. `SellerSpriteTaskQueueStore` 的账号级 claim、CAS 和迁移接口。
3. `SellerSpriteTaskScheduler.enqueue/start/close/job_status`。
4. browser session registry 的公开关闭入口。

## References

- `output/seller-sprite-multi-account-parallelism-research.md`
- `output/seller-sprite-multi-account-parallelism-prd.md`
- `output/seller-sprite-multi-account-parallelism-architecture.md`
- `output/seller-sprite-multi-account-parallelism-uiux.md`
- `docs/superpowers/specs/2026-07-14-seller-sprite-multi-account-parallelism-design.md`
