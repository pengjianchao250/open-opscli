# SellerSprite 多账号并行任务设计

## 1. 背景

SellerSprite 通用任务当前通过 SQLite 队列执行，但队列层限制整个 `seller_sprite` scope 同时只能有一个 `running` 任务，任务管理器也总是获取默认账号。因此，即使账号接口返回多个账号、Browser Route 已按账号隔离 worker 和 profile，系统仍只能使用一个账号串行执行。

本设计让账号接口返回的多个 SellerSprite 账号组成进程内账号池，以独立会话并行执行通用异步任务，并保留冷备用账号在工作账号失效时接替。

## 2. 范围

### 2.1 目标

- 通用异步队列最多同时使用 4 个工作账号和 4 个独立工作会话。
- 同一工作账号串行执行，不同工作账号并行执行。
- 账号数大于 1 时，初始化时至少保留 1 个冷备用账号；超过 5 个账号时，多余账号全部进入备用池。
- 工作账号登录失败或会话失效且重登失败时，按账号接口顺序使用冷备用账号接替。
- 没有可用备用账号时，当前任务失败并关闭该工作槽；其他健康槽继续工作。
- 定期重新调用账号接口；账号失效时额外强制调用一次。
- 账号接口失败时记录错误，已建立的健康工作会话继续运行。
- 对账号登录结果和失败事件同时写结构化运行日志和 SQLite 审计记录。
- 保持现有 MCP ownership、quota、CLI adapter、状态查询和人工队列恢复能力兼容。

### 2.2 非目标

- Listing Analysis submit/status/result 保持现有执行方式，不使用本次多账号池，不自动切换账号，也不计入“最多 4 个通用工作会话”。
- 本次不改变 Listing Analysis 与通用任务之间现有的账号并发关系。
- 不记录正常任务分配、正常任务完成或每个分页/API 子请求。
- 不持久化账号接口返回的账号列表，不设计账号快照。
- 不持久化账号健康状态；服务重启后重新通过账号接口建立账号池。
- 不实现多服务进程共享账号池、leader lease、heartbeat 或自动崩溃恢复。
- 不在普通 MCP 响应中暴露完整用户名、密码、Cookie、Token 或内部审计信息。

### 2.3 会话生命周期补充

- browser-route 会话空闲 30 分钟后自动回收；
- browser-route 会话创建满 6 小时后，在任务完成边界轮换；
- 回收或轮换不删除持久 profile，不把健康账号标记为 unavailable；
- 运行中的会话不允许被空闲回收或定时轮换；
- scheduler 正常关闭时释放全部健康 browser-route 资源；
- 会话实际状态变化同时写结构化日志和 SQLite 账号事件表。

## 3. 运行约束

本版本只支持一个活动 SellerSprite 服务进程消费同一个 SQLite 队列。`get_task_scheduler()` 在同一进程、同一数据库中必须复用唯一的调度器运行时；账号池、工作槽和会话 registry 都由该运行时持有。

SQLite 事务仍用于防止消费协程重复领取，但不宣称多个服务进程可以安全共享浏览器会话池。未来若需要水平扩容，应另行设计 leader lease、slot ownership 和 fencing token。

账号池在该服务进程内共享，不按 MCP 用户拆分；任务 ownership 仍按现有逻辑隔离。

## 4. 账号池规则

### 4.1 初始化

账号始终通过现有集成账号接口获取，并保持接口返回顺序。工作账号目标数量为：

```python
working_count = 0 if account_count == 0 else min(4, max(1, account_count - 1))
```

| 接口返回账号数 | 工作账号 | 冷备用账号 |
| ---: | ---: | ---: |
| 0 | 0 | 0 |
| 1 | 1 | 0 |
| 2 | 1 | 1 |
| 3 | 2 | 1 |
| 4 | 3 | 1 |
| 5 | 4 | 1 |
| 6 及以上 | 4 | 其余全部 |

初次建立账号池时，前 `working_count` 个账号进入工作池，其余账号按原顺序进入备用池。

### 4.2 冷备用

冷备用账号只作为内存中的凭证对象存在：

- 不提前创建 API client；
- 不提前启动浏览器 context；
- 不提前登录；
- 接替时才创建独立会话并登录。

### 4.3 故障后的备用数量

“至少保留 1 个备用”是账号池正常初始化规则，不是故障后的持续不变量。

例如 5 个账号初始化为 4 工作 + 1 备用。一个工作账号失效后，备用账号接替，允许暂时变为 4 工作 + 0 备用。之后再有工作账号失效且没有新账号时，该槽关闭，并发数降为 3。

### 4.4 内存健康状态

账号状态仅存在于当前调度器进程内：

- `working`：已分配工作槽；
- `standby`：冷备用；
- `unavailable`：当前凭证已确认登录失败；
- `removed`：刷新后接口不再返回。

同一账号由 `name.strip().casefold()` 和 `username.strip().casefold()` 组成规范化身份。内部 `account_key` 为该规范化身份加固定 `seller_sprite` domain prefix 后计算的 SHA-256，只用于队列约束和审计关联，不包含密码。

账号池保留当前凭证对象用于比较：

- 刷新后账号身份和密码都未变化：保留原状态；
- 同一账号的密码变化：视为新凭证版本，允许重新登录；
- 新账号：按接口顺序补足空槽，剩余进入备用池；
- 账号消失：停止分配新任务，当前任务结束后关闭并移除会话。

这些状态不写 SQLite。服务重启后重新获取账号并重新验证。

## 5. 账号接口刷新

### 5.1 认证来源

账号接口继续使用现有认证链路，不新增服务账号：

- 由任务触发的刷新使用该任务队列行中保存的 `session_id/JWT`；
- 入队请求更新调度器内存中的最近可用认证上下文；
- 定时刷新使用最近可用认证上下文；若没有，则使用最早 queued/running 通用任务的认证上下文；
- 不把账号接口响应持久化为快照。

账号池共享建立在不同任务通过接口获取到同一 SellerSprite 账号集合的业务前提上。

### 5.2 刷新时机

- 调度器首次需要工作账号时调用；
- 按现有 `account_cache_ttl_seconds` 定时调用；
- 账号登录失败或重登失败时强制调用一次。

账号池用一个进程内异步锁串行刷新，避免重复调用。

### 5.3 接口失败

账号接口调用失败时：

- 写 `account_fetch_failed` 结构化运行日志和 SQLite 审计事件；
- 已建立的健康工作会话继续处理队列；
- 本次不新增工作账号，也不能使用尚未获取的备用账号；
- 下一个定时周期、任务入队或账号故障时再次调用；
- 若服务启动后尚未成功获取任何账号，任务保持 queued，调度器按刷新周期重试，不直接失败任务。

审计事件按刷新尝试记录，但刷新频率受 TTL 限制，避免紧循环写入。

如果实际执行的是 `opscli` 命令或 MCP Tool 且调用失败，仍遵守项目 `AGENTS.md` 的 `ops-feedback` 自动反馈规则。

## 6. 任务类型隔离

队列表新增非空字段：

```text
task_kind = generic | listing_analysis
```

赋值规则由规范化后的 scenario 强制决定：

- scenario 等于 `listing-analysis` 时只能写 `listing_analysis`；
- 其他允许场景写 `generic`；
- `seller_sprite_listing_analysis_submit` 写 `listing_analysis`；
- 隐藏兼容入口遇到任何大小写或首尾空白形式的 `listing-analysis`，规范化后也必须写 `listing_analysis`，不得伪装为 generic。

通用多账号 worker 只领取 `task_kind='generic'`。Listing Analysis 由现有单账号消费路径领取 `task_kind='listing_analysis'`，其 submit/status/result 行为不纳入本次多账号并发和 failover 契约。

FIFO 在 generic 子队列内保证。Listing Analysis 继续沿用现有顺序语义。

## 7. 模块边界

### 7.1 AccountProvider

扩展 `SellerSpriteAccountProvider`：

```python
list_accounts(refresh: bool = False) -> list[SellerSpriteAccount]
```

职责：

- 调用账号接口；
- 返回完整、有序账号列表；
- 只在内存中持有解密凭证；
- 公开摘要隐藏密码和完整用户名。

不负责任务领取、账号健康、failover 或会话关闭。

### 7.2 AccountPool

新增进程内账号池，负责：

- 建立工作账号和冷备用账号；
- 保留刷新后仍健康的工作账号；
- 记录当前进程内 unavailable 状态；
- 按接口顺序选择备用账号；
- 在账号新增、移除或密码变化时调整槽位。

### 7.3 TaskScheduler

调度器负责：

- 为每个通用工作账号运行一个消费协程，最多 4 个；
- 为每个空闲槽原子领取最早 generic queued 任务；
- 将实际账号显式传给 manager；
- 根据结构化登录/会话错误决定重登、接替或失败；
- 管理账号刷新和工作槽增减；
- 关闭失效、移除或停止使用的账号会话。

### 7.4 ApiManager

manager 的执行入口接受显式账号和 attempt 工作目录，不再自行调用 `get_default()`。

manager 负责：

- 使用指定账号；
- 区分首次登录失败、session expired、普通网络错误和业务错误；
- 同账号 session expired 后重登一次；
- 返回结构化失败阶段；
- 保持现有结果归一化和导出行为。

manager 不读取备用池，也不自行选择其他账号。

### 7.5 SessionRegistry

以 `account_key` 为键维护独立会话：

```python
await session_registry.close_account(account_key, purge_auth_state=False)
```

- `api-direct`：关闭该账号 client；
- `browser-route`：停止该账号 worker，关闭 page/context，并从 registry 移除；
- 账号登录失败、移除或密码变化时清理旧 Cookie 和旧 browser 认证状态；
- 调度器正常关闭时只关闭活动资源，不删除仍有效登录态；
- 清理失败记录 `account_session_close_failed`，但不覆盖任务原始错误。

Cookie/profile 路径继续位于 `CONFIG_DIR/seller_sprite`，文件名不得包含完整用户名。

会话 registry 额外维护 browser context 的创建时间、最后任务完成时间、累计任务数和当前状态。
默认空闲阈值为 1800 秒，默认最大生命周期为 21600 秒，均可通过 SellerSprite 环境变量覆盖。
回收器每分钟检查一次空闲会话，并在每条任务完成后检查最大生命周期：

- `busy`、内部队列非空或已被新任务预留的会话一律跳过；
- 空闲超时原因记为 `idle_timeout`；
- 最大生命周期原因记为 `max_lifetime`；
- scheduler 正常关闭记为 `scheduler_close`；
- 账号认证失败或退出工作池沿用对应业务原因；
- 先从 registry 移除，再关闭 context/playwright，防止关闭中的会话被再次取得；
- 下一任务重新创建会话，不触发 failover，也不增加任务 generation。

## 8. SQLite 队列变更

### 8.1 新字段

任务队列增加：

- `task_kind TEXT NOT NULL DEFAULT 'generic'`；
- `assigned_account_key TEXT`；
- `assignment_generation INTEGER NOT NULL DEFAULT 0`；
- `failover_count INTEGER NOT NULL DEFAULT 0`；
- `last_error_code TEXT`；
- `last_failed_account_key TEXT`；
- `retry_reason TEXT`。

### 8.2 确定约束

创建部分唯一索引：

```sql
CREATE UNIQUE INDEX uq_seller_sprite_running_account
ON seller_sprite_task_queue(queue_scope, assigned_account_key)
WHERE status = 'running' AND assigned_account_key IS NOT NULL;
```

所有新代码必须保证 running 通用任务的 `assigned_account_key` 非空。唯一索引冲突被视为本轮没有领取任务，调度循环重新选择，不退出。

### 8.3 Schema 迁移

迁移使用现有 `_ensure_schema()` 内的显式 schema version，并在单个事务中执行：

1. 增加带默认值的新列；
2. 遍历旧行并解析 `request_json`；
3. scenario 经 `strip().lower()` 后等于 `listing-analysis` 的行回填 `listing_analysis`，其余回填 `generic`；
4. `request_json` 无法解析或缺少 scenario 的 queued 行标记 failed，并写明确迁移错误；
5. 旧 running 行保持 running，但因无法证明实际账号，不创建伪造账号键；启动时检测到这类行时阻止自动消费，并要求使用现有 `requeue-running` 或人工 fail 命令处理；
6. 校验不存在重复的非空 running 账号键；
7. 创建部分唯一索引；
8. 更新 schema version 并提交。

任一步失败则整个迁移回滚，调度器拒绝启动并输出明确错误。测试覆盖 legacy queued、legacy Listing Analysis、malformed JSON 和 legacy running。

## 9. 原子任务领取

每个通用工作槽调用：

```python
claim_next_generic_for_account(
    queue_scope="seller_sprite",
    account_key=...,
    assigned_account=...,
    worker_key=...,
)
```

在一个 `BEGIN IMMEDIATE` 事务内：

1. 检查该 `account_key` 没有 running 任务；
2. 选择最早的 `task_kind='generic' AND status='queued'` 行；
3. 条件更新为 running；
4. 写入实际 `assigned_account_key`、安全账号名称和 `worker_key`；
5. 增加 `assignment_generation`；
6. 提交。

最多 4 个 generic 消费协程由进程内工作槽数量保证；同账号唯一索引提供数据库保护。

## 10. 代际隔离

每次 claim 或账号改绑都会增加 `assignment_generation`。执行者持有：

- `job_id`；
- `assigned_account_key`；
- `assignment_generation`。

以下操作必须使用这三个值及 `status='running'` 做 CAS：

- 标记任务成功；
- 标记任务失败；
- 同步 MCP run 成功/失败；
- 将成功 attempt 文件提升到 job root；
- 从失败账号改绑备用账号。

人工恢复 running 任务时：

- 状态改回 queued；
- 清空账号和 worker 字段；
- 增加 `assignment_generation`。

旧执行者 CAS 失败后必须丢弃结果，不能覆盖新一代任务或 MCP 状态。

## 11. 登录与接替状态机

### 11.1 工作账号首次登录失败

业务请求尚未发送时，工作账号首次登录失败：

1. 记录 `account_login_failed`；
2. 将该账号当前凭证在内存中标记 unavailable；
3. 强制调用账号接口一次；
4. 若同一账号密码发生变化，优先用新密码登录一次；
5. 否则按备用池顺序选择账号；
6. 无可用备用时失败当前任务并关闭槽。

首次登录失败不消耗 session expired 后的重登次数。

### 11.2 Session expired

任务执行中检测到明确的 session expired 响应：

1. 记录 `account_session_expired`；
2. 使用原账号重登一次；
3. 成功则记录 `account_relogin_succeeded`，并重试当前请求一次；
4. 失败则记录 `account_relogin_failed`，将当前凭证在内存标记 unavailable；
5. 强制调用账号接口；
6. 若该账号密码已更新，优先用新密码登录一次；
7. 否则关闭并清理旧会话，进入备用接替。

每条失败链最多尝试一个刷新后的新密码版本，避免循环刷新。

### 11.3 备用接替

任务从失败账号 X 改绑候选 Y 时，在 `BEGIN IMMEDIATE` 中：

1. 校验任务仍为 running；
2. 校验当前账号和 generation 仍等于执行者持有值；
3. 校验 Y 没有 running 任务；
4. 更新 `assigned_account_key` 和安全账号名称；
5. 增加 `assignment_generation` 和 `failover_count`；
6. 写失败账号和错误字段；
7. 提交并返回新 generation。

事务提交后才创建 Y 会话：

- Y 登录成功：记录 `account_login_succeeded`，事件元数据标记 `reason='failover'`；
- Y 登录失败：记录失败、标记 unavailable、关闭会话，再使用同一 CAS 协议改绑下一个候选；
- CAS 或唯一索引冲突：重新读取任务，不覆盖其他结果；
- 全部候选耗尽：用当前 generation CAS 标记任务和 MCP run failed，记录 `account_failover_exhausted`，关闭该槽。

### 11.4 接替后的任务次数

每个账号在同一任务中最多执行一次完整 attempt。备用账号成功登录后的 attempt 再次发生明确认证错误时：

- 将该账号标记 unavailable；
- 若仍有本任务尚未尝试的健康备用账号，继续按第 11.3 节的 CAS 协议接替；
- 同一账号不得被当前任务重复选择；
- 所有可用备用账号均已尝试或不存在时，当前任务失败并关闭该槽。

普通网络错误、5xx 或其他结果不确定错误仍按第 12 节直接失败，不继续切换账号。有限账号集合和“每账号每任务最多一次”共同保证接替不会无限循环。

## 12. 重放和输出隔离

通用 SellerSprite 场景均为数据查询操作。以下明确认证失败可安全重试：

- 首次登录失败，业务请求尚未发送；
- SellerSprite 明确返回登录页、401/403 或 `ERR_GLOBAL_SESSION_EXPIRED`，表示业务请求未通过认证；
- Browser Route 在提交业务请求前确认页面未登录。

以下情况不触发换账号重放：

- 网络超时或连接中断，无法确认请求是否到达；
- SellerSprite 5xx；
- 参数、解析、导出或文件系统错误；
- OPS/MCP 认证或 ownership 错误；
- Listing Analysis；
- 任何无法确认远端结果的错误。

每个 attempt 写入：

```text
<job-root>/.attempts/<assignment-generation>/
```

只有当前 generation 的成功 attempt 才能通过 CAS 原子提升 `params.json`、`raw.json`、`result.json` 和 export 到现有 job root。失败 attempt 不与后续结果混合。

## 13. 刷新后的槽位协调

- 健康工作账号仍存在且密码未变化：保留会话；
- 密码变化：当前任务结束后关闭并清理旧会话，再使用新凭证；
- 账号从接口移除：不再分配新任务，当前任务结束后关闭并清理；
- 新账号：按接口顺序补足空缺工作槽，剩余进入备用池；
- unavailable 账号密码未变化：保持 unavailable；
- unavailable 账号密码变化：恢复可用；
- 接口返回账号减少导致目标工作数下降：多余健康槽在当前任务结束后按接口逆序转为冷备用。

接口调用失败不改变当前内存账号池，不关闭现有健康会话。

## 14. 日志与 SQLite 审计

### 14.1 记录粒度

按已确认的“仅登录与失败”粒度记录：

- `account_fetch_failed`；
- `account_login_succeeded`；
- `account_login_failed`；
- `account_session_expired`；
- `account_relogin_succeeded`；
- `account_relogin_failed`；
- `account_failover_exhausted`；
- `account_session_close_failed`。
- `account_session_state_changed`。

不记录正常任务分配、正常任务完成、API 子请求或正常会话关闭。备用接替成功合并到 `account_login_succeeded` 的白名单元数据，不增加“正常使用”事件。

用户要求会话生命周期可观测后，browser-route 会话的实际状态变化作为例外记录。状态事件只记录
`previous_state/state/reason/session_age_seconds/idle_seconds/task_count` 白名单元数据；相同状态不得重复写入。

每次登录失败均必须记录，不做按账号或错误码去重：

- 首次登录失败：`account_login_failed`，`login_stage='initial'`；
- 同账号重登失败：`account_relogin_failed`，`login_stage='relogin'`；
- 刷新后新密码登录失败：`account_login_failed`，`login_stage='refreshed_credential'`；
- 备用账号接替登录失败：`account_login_failed`，`login_stage='failover'`。

每条失败事件必须能通过 `job_id + worker_key + assignment_generation` 关联到具体任务、工作槽和执行代际，并记录 `failover_count` 与白名单 `next_action`，方便还原后续是刷新账号、尝试备用还是关闭槽。

### 14.2 审计表

新增 `seller_sprite_account_events`：

- `id INTEGER PRIMARY KEY`；
- `created_at TEXT NOT NULL`；
- `event_type TEXT NOT NULL`；
- `account_key TEXT`；
- `account_name TEXT`；
- `masked_username TEXT`；
- `job_id TEXT`；
- `worker_key TEXT`；
- `assignment_generation INTEGER`；
- `execution_mode TEXT`；
- `login_stage TEXT`；
- `error_code TEXT`；
- `error_summary TEXT`；
- `replacement_account_key TEXT`；
- `duration_ms INTEGER`；
- `failover_count INTEGER`；
- `next_action TEXT`；
- `metadata_json TEXT`。

账号接口失败不是单账号事件，因此账号字段允许为空。索引：

- `created_at`；
- `(account_key, created_at)`；
- `(job_id, created_at)`；
- `(event_type, created_at)`。

SQLite 事件永久保留，不自动清理。运行日志保留和轮转沿用现有部署平台策略。

### 14.3 脱敏

运行日志、SQLite 和 MCP 响应不得包含：

- 密码；
- Cookie；
- JWT、API Key 或其他 Token；
- 完整请求头；
- 登录表单；
- 原始登录响应；
- 未脱敏用户名。

错误只保存结构化错误码以及脱敏、限长后的摘要。`metadata_json` 使用固定白名单字段。

禁止直接序列化异常对象或记录 `exc_info` 中可能携带的原始登录响应；若需要堆栈定位，只记录异常类型和本地代码位置，不记录异常参数中的响应正文。

### 14.4 审计写入失败

运行日志始终先写。SQLite 审计属于诊断记录，不与内存账号状态做原子绑定；写入失败时：

- 记录 `account_audit_persistence_failed` 运行日志；
- 保留原始业务错误；
- 不阻塞其他健康工作槽；
- 不把审计异常替换成任务主错误。

## 15. 对外兼容性

以下保持不变：

- `seller_sprite_run`；
- `seller_sprite_job_status`；
- `seller_sprite_jobs_status`；
- `seller_sprite_export`；
- MCP ownership 和 quota；
- queued/running/succeeded/failed 状态；
- 有界状态等待；
- CLI remote adapter；
- Listing Analysis submit/status/result 对外协议；
- 人工队列恢复命令。

普通任务状态若展示 `assigned_account`，只返回安全账号名称，不返回完整用户名、`account_key` 或审计事件。

## 16. 测试策略

所有测试使用 fake/stub、`tmp_path`、`monkeypatch` 和可控 `asyncio.Event`，不访问真实账号接口、SellerSprite 或浏览器。

### 16.1 账号池和刷新

- 0～6 个账号得到正确工作/备用数量；
- 5 个账号故障接替后允许 4 工作 + 0 备用；
- 第二次故障无备用时槽数降为 3；
- 保持接口顺序；
- 相同密码的 unavailable 账号不恢复；
- 密码变化后恢复；
- 备用接替前没有活动会话；
- 接口失败会写日志和审计，现有健康会话继续；
- 首次获取失败时任务保持 queued，后续获取成功后开始执行。

### 16.2 队列和迁移

- generic worker 只领取 generic；
- Listing Analysis 规范化后始终写 listing_analysis；
- hidden 入口不能把 Listing Analysis 写成 generic；
- legacy 队列迁移覆盖普通、Listing Analysis、malformed JSON 和 running 行；
- 同一账号不能同时有两个 running generic 任务；
- 不同账号真实并行；
- generic FIFO 保持；
- 唯一索引冲突不会终止消费循环。

### 16.3 登录和接替

- 首次登录失败会强刷并尝试更新密码或备用；
- session expired 后原账号只重登一次；
- 重登成功不切备用；
- 备用 B 登录失败后按 generation CAS 改绑 C；
- CAS 冲突不覆盖其他结果；
- 备用成功后当前任务只完整执行一次；
- 无备用时任务和 MCP run 失败并关闭槽；
- 一个槽关闭不影响其他健康槽。

### 16.4 代际和输出

- 人工 requeue 增加 generation；
- 旧执行者不能写任务终态、MCP 终态或提升文件；
- 明确 session expired 可以重试；
- 网络结果不确定时不切账号；
- 失败 attempt 和成功 attempt 文件不混合。

### 16.5 日志与安全

- 登录结果、session expired、重登失败、备用耗尽和账号接口失败按白名单记录；
- 不记录正常任务使用和正常关闭；
- SQLite 事件不自动清理；
- 日志、数据库和路径名不包含明文凭证或完整用户名；
- 账号登录失败、移除或密码变化会清理旧认证状态；
- SQLite 审计写入失败不会覆盖任务主错误。
- 首次登录、重登、新凭证和备用接替的每次登录失败均产生可关联 job、slot、generation 的日志和审计记录；
- 登录失败记录包含失败阶段、错误码、耗时、failover 次数和下一动作，但不包含完整用户名或任何凭证。
- 会话 ready/busy/idle/recycling/closing/closed/close_failed 状态变化可查询，重复状态不重复记录；
- 30 分钟空闲回收和 6 小时轮换的关闭原因、会话年龄与累计任务数均为脱敏字段。

### 16.6 回归

- 现有异步提交、单任务状态和批量状态测试通过；
- MCP ownership、quota 和 CLI adapter 不变；
- Listing Analysis 对外工具行为不变；
- 人工队列恢复命令继续有效。

## 17. 验收标准

1. 账号接口返回 5 个有效账号且 generic 队列有至少 4 个可控阻塞任务时，4 个不同账号同时 running，第 5 个账号没有活动会话。
2. 工作账号首次登录失败或重登失败后，冷备用账号接管该槽，其他槽不被阻塞。
3. 备用账号全部不可用时，当前任务失败并关闭该槽，其他健康槽继续消费。
4. 账号接口失败会记录日志和 SQLite 事件，但不关闭现有健康工作会话。
5. generic worker 不领取 Listing Analysis；Listing Analysis 对外行为保持现状。
6. 同一账号没有两个 running generic 任务；人工恢复后旧执行者不能覆盖新任务状态或文件。
7. 登录结果和失败事件同时写入结构化运行日志和永久 SQLite 审计，且不含密码、Cookie、Token 或完整用户名。
8. 只有明确认证失败允许切账号重试；网络结果不确定时不重放。
9. 账号登录失败、移除或密码变化后，旧 Cookie 和 browser 认证状态被清理。
10. MCP ownership、quota、状态等待、CLI adapter 和人工恢复命令保持现有契约。
11. 空闲未满 30 分钟的会话保持复用，满 30 分钟后自动关闭并从 registry 移除。
12. 会话满 6 小时时不打断运行中任务，在任务完成边界关闭，并由下一任务懒创建新会话。
13. scheduler 正常关闭后不存在其管理的 browser-route context/playwright 资源。
14. 每次实际会话状态变化同时写结构化日志和 SQLite 审计，且不包含凭证或响应正文。
