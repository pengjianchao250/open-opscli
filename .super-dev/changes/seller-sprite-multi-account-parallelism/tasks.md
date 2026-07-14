# Tasks: SellerSprite 多账号并行与故障接替

## Account Pool

- [x] 以 TDD 增加 `SellerSpriteAccountProvider.list_accounts()`。
- [x] 以 TDD 增加工作/备用/unavailable 账号池。
- [x] 覆盖 0～6 账号分配、顺序、密码变化恢复和备用接替。

## Queue and Audit

- [x] 迁移任务表的 task kind、账号键、generation 和 failover 字段。
- [x] 增加账号级 generic claim 与 Listing Analysis 隔离领取。
- [x] 增加 finish/fail/failover generation CAS。
- [x] 增加账号事件表和脱敏事件 Recorder。
- [x] 覆盖登录失败日志、审计字段和审计写入降级。

## Scheduler and Sessions

- [x] 最多启动 4 个账号隔离的 generic 工作槽。
- [x] 保留一个独立 Listing Analysis 串行消费槽。
- [x] 实现明确认证失败后的账号刷新和备用接替。
- [x] 备用耗尽时失败当前任务并关闭故障槽。
- [x] 关闭失效账号 browser/API 会话并从 registry 移除。
- [x] 保持现有 ownership、quota、状态和导出兼容。

## Verification

- [x] 定期运行单文件测试完成 red-green 循环。
- [x] 运行 `pytest tests/seller_sprite -v`（现有 debug CLI 注册缺失导致 2 项无关失败，其余 133 项通过）。
- [x] 运行相关 MCP SellerSprite 测试。
- [x] 运行全量测试（被现有重复测试模块名及 `tests/query/test_manager.py` 缩进错误阻断，已记录）。
- [x] 更新 `docs/change-log-pending.md`。
- [x] 执行 Standards/Spec 双轴代码审查并修复问题。
- [x] 提交当前分支。
