# 卖家精灵多账号并行与故障接替 Research

## 研究结论

当前瓶颈不在卖家精灵浏览器 worker，而在通用任务调度器和 SQLite 领取约束：`SellerSpriteTaskScheduler` 只有一个 `_runner_task`，`claim_next()` 又按整个 `seller_sprite` queue scope 限制只能存在一条 `running` 记录；同时 `SellerSpriteApiManager.run()` 总是调用 `account_provider.get_default()`。因此账号接口即使返回多个账号，运行时仍只会使用一个默认账号。

推荐采用“进程内账号池 + 每账号一个工作槽 + 冷备用接替 + SQLite 账号级唯一约束”。账号接口返回 5 个账号时，前 4 个建立独立工作会话，第 5 个保持冷备用；工作账号确认认证失效且同账号重登失败后，备用账号接替该槽。备用耗尽时，失败当前任务并关闭该工作槽，其他健康槽继续运行。

## 本地代码证据

### 账号来源

`opscli/seller_sprite/accounts.py` 已能从集成账号接口取得有序的完整账号集合，但公开业务入口只有 `get_default()` 和脱敏的 `list_public()`，缺少返回完整凭证对象列表的内部接口。

应增加：

```python
list_accounts(refresh: bool = False) -> list[SellerSpriteAccount]
```

该方法只负责有序取数和缓存，不承担健康状态、任务领取或备用选择。

### 调度器

`opscli/seller_sprite/services/task_scheduler.py` 当前：

- 只持有一个 `_runner_task`；
- 所有任务使用固定 `worker_key="default"`；
- `assigned_account` 来自配置默认账号，而不是实际执行账号；
- manager 未接收显式账号，仍会自行获取默认账号。

所以多账号并发应落在调度器工作槽，而不是在同一个 manager 内并发调用多个账号。

### 队列

`SellerSpriteTaskQueueStore.claim_next()` 当前查询包含“同一 queue scope 不得已有 running”的全局限制。这是单账号串行的主要数据库约束。多账号方案应改为“同一账号最多一条 running”，并保留 FIFO 选择最早 queued 通用任务。

### 会话隔离

`SellerSpriteBrowserRouteWorker` 已按 `(event_loop, account.name, account.username)` 缓存 worker，profile 目录也按账号身份散列，具备一账号一浏览器上下文的基础。缺口是失效账号关闭后还需从 worker registry 移除，避免旧 worker 被再次取回。

`SellerSpriteApiClient` 已有账号独立 Cookie 文件和 `switch_account()`，但多账号工作槽不应共享 client；应由会话 registry 按账号维护并明确关闭。

## 外部技术依据

### Playwright 独立会话

Playwright 官方说明 BrowserContext 用于运行多个相互独立的浏览器会话；关闭 BrowserContext 会同时关闭该 context 下的页面。这支持“一账号一 context、失效时只关闭对应 context”的隔离模型。

来源：[Playwright BrowserContext 官方文档](https://playwright.dev/python/docs/api/class-browsercontext)

### Python 3.10 并发任务

项目最低版本是 Python 3.10，不能依赖 Python 3.11 才引入的 `TaskGroup`。Python 3.10 官方文档支持使用 `asyncio.create_task()` 并发调度协程，并特别要求持有 Task 的强引用，防止后台任务在执行中被回收。因此调度器应显式保存最多 4 个 slot task，并在关闭时逐个等待结束。

来源：[Python 3.10 Coroutines and Tasks](https://docs.python.org/3.10/library/asyncio-task.html)

### SQLite 账号级唯一约束

SQLite 官方文档确认 UNIQUE partial index 可以只对满足 `WHERE` 条件的行强制唯一。这适合表达“同一账号在 running 子集里最多出现一次”：

```sql
CREATE UNIQUE INDEX uq_seller_sprite_running_account
ON seller_sprite_task_queue(queue_scope, assigned_account_key)
WHERE status = 'running' AND assigned_account_key IS NOT NULL;
```

`BEGIN IMMEDIATE` 会立即开启写事务，可让“检查账号空闲 -> 选择最早 queued -> 更新为 running”成为单个原子领取操作。

来源：[SQLite Partial Indexes](https://www.sqlite.org/partialindex.html)、[SQLite Transactions](https://www.sqlite.org/lang_transaction.html)

## 方案比较

### 方案 A：调度器账号池与独立工作槽（采用）

- 最多 4 个工作槽，每槽绑定一个账号和独立会话；
- 多余账号冷备用；
- 明确认定认证失败后按顺序接替；
- 数据库按账号约束 running；
- 适配现有单账号 worker/profile 设计。

优点是并发边界清晰、同账号仍串行、故障只影响一个槽。代价是需要队列 schema 迁移、代际 CAS 和 attempt 输出隔离。

### 方案 B：每个任务临时从账号列表随机选账号

改动较小，但无法稳定保留备用账号，难以关闭失效会话，也无法保证同账号只有一个 running 任务。不采用。

### 方案 C：单账号创建多个浏览器窗口

不能满足多账号独立会话要求，还会增加共享 Cookie/profile 的竞争和风控风险。不采用。

## 已锁定语义

本需求沿用已提交设计 `docs/superpowers/specs/2026-07-14-seller-sprite-multi-account-parallelism-design.md`：

| 账号总数 | 工作账号 | 冷备用 |
| ---: | ---: | ---: |
| 0 | 0 | 0 |
| 1 | 1 | 0 |
| 2 | 1 | 1 |
| 3 | 2 | 1 |
| 4 | 3 | 1 |
| 5 | 4 | 1 |
| 6 及以上 | 4 | 其余全部 |

即账号数大于 1 时始终先保留至少 1 个冷备用。备用接替后不强行再次腾出备用；例如 5 个账号可从 `4 工作 + 1 备用` 变成 `4 工作 + 0 备用`，下一次账号失效则关闭对应槽并降为 3 个工作会话。

## 风险

1. 当前 SQLite 只有 scope 级单 running 约束，必须迁移后才能安全开放并发。
2. failover 发生时旧执行者可能晚到写结果，必须用 `assignment_generation` 做 CAS，不能只依靠内存 task 状态。
3. 同一个任务换账号重放时可能产生混合输出，必须按 generation 写 `.attempts/`，仅提升当前代成功结果。
4. 只有明确认证失败可换账号；网络超时、5xx、解析和导出错误不应换账号重放。
5. 本期账号池只支持单服务进程；多进程共享同一 SQLite 队列需要另行设计 leader lease 和 fencing token。
