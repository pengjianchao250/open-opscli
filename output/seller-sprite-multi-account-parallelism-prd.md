# 卖家精灵多账号并行与故障接替 PRD

## 需求概述

当卖家精灵集成账号接口返回多个账号时，通用异步任务应使用账号隔离的独立会话并行执行。最多运行 4 个工作会话，并在账号数大于 1 时保留至少 1 个冷备用账号。工作账号确认失效后，由备用账号接替；没有备用账号时，当前任务失败并关闭对应工作会话，其他健康会话继续处理队列。

## 目标

1. 不同账号最多 4 路并行，同一账号保持串行。
2. 5 个账号形成 4 个工作账号和 1 个冷备用账号。
3. 冷备用在接替前不创建 client、浏览器 context 或登录态。
4. 工作账号首次登录失败，或 session expired 后同账号重登失败时，触发备用接替。
5. 备用耗尽时只关闭故障槽，不停止整个调度器。
6. 账号接口刷新失败时，已有健康会话继续运行；若从未成功取得账号，任务保持 queued。
7. 保持现有 MCP ownership、quota、CLI remote adapter、状态查询、导出和人工队列恢复兼容。

## 非目标

1. 不让同一账号并行运行多个任务。
2. 不让 Listing Analysis submit/status/result 进入本次多账号池。
3. 不实现多个服务进程共享账号池。
4. 不持久化账号凭证、账号池快照或健康状态。
5. 不因网络超时、5xx、参数、解析、导出或文件错误切换账号重放。
6. 不新增 Web UI 或普通用户可见的账号管理面板。

## 功能需求

### FR-1 账号池初始化

账号必须保持接口返回顺序。工作账号数量为：

```python
working_count = 0 if account_count == 0 else min(4, max(1, account_count - 1))
```

账号数为 1 时允许 `1 工作 + 0 备用`；账号数大于 1 时至少保留 1 个备用；超过 5 个账号时，最多仍只有 4 个工作账号。

### FR-2 独立工作会话

每个工作账号绑定独立的：

- 调度消费协程；
- API client/Cookie 状态；
- browser-route worker；
- Playwright persistent context/profile；
- worker key 和安全账号标识。

同一账号不得同时领取第二个任务。

### FR-3 账号接口刷新

调度器在以下时机刷新账号：

1. 首次需要工作账号；
2. 达到 `account_cache_ttl_seconds`；
3. 工作账号认证失败时强制刷新一次。

刷新必须由进程内异步锁串行化。刷新失败不能关闭已有健康会话。

### FR-4 认证故障判定

只有以下故障进入 failover：

1. 业务请求发送前的首次登录失败；
2. 明确的登录页、401/403 或 `ERR_GLOBAL_SESSION_EXPIRED`；
3. browser-route 在发送业务请求前确认未登录；
4. session expired 后原账号重登一次仍失败。

普通网络错误、5xx、解析、导出、上传、OPS/MCP 认证或 ownership 错误不得切换账号。

### FR-5 备用接替

故障发生后：

1. 将当前凭证版本标记 unavailable；
2. 强制刷新账号接口；
3. 同身份密码已更新时，优先尝试一次新凭证；
4. 否则按备用池顺序选择下一个账号；
5. 原子改绑任务并增加 `assignment_generation`、`failover_count`；
6. 新账号登录成功后，从新的 attempt 目录重跑任务；
7. 每个账号在同一任务中最多执行一次完整 attempt。

### FR-6 无备用账号

全部候选耗尽或不存在备用时：

1. 当前任务和对应 MCP run 标记 failed；
2. 记录 `account_failover_exhausted`；
3. 关闭并移除该账号会话；
4. 关闭对应工作槽；
5. 不取消其他健康槽的任务。

后续账号刷新发现新账号或 unavailable 账号密码变化时，可以补足空槽。

### FR-7 队列一致性

通用任务领取必须：

- 只领取 `task_kind='generic'`；
- 使用 `BEGIN IMMEDIATE` 原子领取最早 queued 任务；
- 写入实际 `assigned_account_key`、安全账号名称和唯一 worker key；
- 通过部分唯一索引保证每个账号最多一条 running；
- 所有完成、失败、MCP 状态同步和 failover 改绑都使用账号键与 generation 做 CAS。

### FR-8 输出隔离

每次 attempt 写入：

```text
<job-root>/.attempts/<assignment-generation>/
```

只有当前 generation 成功后才能提升到 job root。旧执行者、失败账号和失败 attempt 不得覆盖最终输出。

### FR-9 安全与审计

账号登录失败必须同时写入结构化运行日志和 SQLite 审计表，事件名固定为 `account_login_failed`。同账号重登失败使用 `account_relogin_failed`，备用账号接替登录失败仍使用 `account_login_failed`，并通过 `login_stage='failover'` 区分。

每条登录失败记录至少包含：

- `created_at`；
- `event_type`；
- `account_key`、安全账号名称和脱敏用户名；
- `job_id`、`worker_key` 和 `assignment_generation`；
- `execution_mode`；
- `login_stage`：`initial | relogin | refreshed_credential | failover`；
- 结构化 `error_code` 和脱敏、限长的 `error_summary`；
- `duration_ms`；
- `failover_count` 以及失败后是否进入账号刷新或备用接替。

运行日志必须先写，SQLite 审计随后写入。审计写入失败时记录 `account_audit_persistence_failed`，但不得覆盖账号登录的原始错误，也不得阻塞其他健康工作槽。

只记录账号登录与故障事件，不记录每个正常任务或每个 API 请求。日志、SQLite、状态响应不得包含密码、Cookie、JWT、API Key、完整用户名、登录表单、原始登录响应或完整请求头。

## 对外体验

现有调用方式不变：

- `seller_sprite_run` 仍立即入队；
- `seller_sprite_job_status` / `seller_sprite_jobs_status` 仍查询同一 job；
- `seller_sprite_export` 仍读取最终结果；
- 普通状态如显示账号，只显示安全账号名称。

并发和接替对调用者透明；只有最终无可用账号时任务才进入 failed。

## 验收标准

1. 0～6 个账号产生规定的工作/备用数量。
2. 5 个账号、至少 4 个 queued 任务时，4 个不同账号可同时进入 running。
3. 同一账号在任意时刻最多一条 running。
4. 备用账号接替前没有创建活动会话。
5. 工作账号明确认证失效时，备用账号可以接替同一任务。
6. 第一次故障可由第 5 个账号接替并保持 4 个工作槽；第二次故障且无备用时，只关闭该槽并降为 3 个工作槽。
7. 无账号或首次账号接口失败时，任务保持 queued，不被错误标记 failed。
8. 账号接口刷新失败不影响已有健康槽完成任务。
9. 普通错误不触发 failover。
10. 旧 generation 不能覆盖新 generation 的任务、MCP 状态或输出文件。
11. Listing Analysis 不被 generic worker 领取。
12. 每次首次登录、重登和备用接替登录失败都产生可关联 job/slot/generation 的结构化日志及 SQLite 审计记录。
13. 登录失败日志不包含密码、Cookie、Token、完整用户名或原始登录响应。
14. SQLite 审计写入失败不会覆盖任务主错误，其他健康工作槽仍继续执行。
15. 全部 seller_sprite 测试、全量测试、类型/导入检查通过。

## TDD 公共测试缝

确认后按以下公共边界测试，不直接测试私有实现：

1. `SellerSpriteAccountProvider.list_accounts()`：有序返回完整账号列表并支持 refresh。
2. `SellerSpriteTaskQueueStore`：账号级原子 claim、CAS finish/fail/failover、legacy schema 迁移。
3. `SellerSpriteTaskScheduler`：通过公开 `enqueue/start/close/job_status` 观察并行、接替和槽关闭。
4. browser session registry：通过公开获取/关闭入口验证按账号隔离和关闭后移除。
