# Tasks: SellerSprite 多账号并行与故障接替

## Account Pool

- [ ] 以 TDD 增加 `SellerSpriteAccountProvider.list_accounts()`。
- [ ] 以 TDD 增加工作/备用/unavailable 账号池。
- [ ] 覆盖 0～6 账号分配、顺序、密码变化恢复和备用接替。

## Queue and Audit

- [ ] 迁移任务表的 task kind、账号键、generation 和 failover 字段。
- [ ] 增加账号级 generic claim 与 Listing Analysis 隔离领取。
- [ ] 增加 finish/fail/failover generation CAS。
- [ ] 增加账号事件表和脱敏事件 Recorder。
- [ ] 覆盖登录失败日志、审计字段和审计写入降级。

## Scheduler and Sessions

- [ ] 最多启动 4 个账号隔离的 generic 工作槽。
- [ ] 保留一个独立 Listing Analysis 串行消费槽。
- [ ] 实现明确认证失败后的账号刷新和备用接替。
- [ ] 备用耗尽时失败当前任务并关闭故障槽。
- [ ] 关闭失效账号 browser/API 会话并从 registry 移除。
- [ ] 保持现有 ownership、quota、状态和导出兼容。

## Verification

- [ ] 定期运行单文件测试完成 red-green 循环。
- [ ] 运行 `pytest tests/seller_sprite -v`。
- [ ] 运行相关 MCP SellerSprite 测试。
- [ ] 运行全量测试。
- [ ] 更新 `docs/change-log-pending.md`。
- [ ] 执行 Standards/Spec 双轴代码审查并修复问题。
- [ ] 提交当前分支。
