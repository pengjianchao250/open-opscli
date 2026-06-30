# 卖家精灵 MCP 调用记录设计

## 1. 背景

当前卖家精灵 MCP 服务已经具备：

- 基于 `seller_sprite_run` 的统一入口
- 基于 SQLite 的本地任务队列
- 基于任务目录的 `status.json` / `result.json` 结果落盘

但当前链路缺少“谁调用了什么、以什么模式调用、传了什么参数、最终是否成功、关联哪个任务”的统一审计记录。用户希望补充最小可用的调用记录能力，并明确：

- 仅覆盖 MCP 场景
- 仅覆盖 `seller_sprite_run`
- 记录调用用户、模式、参数、结果摘要
- 记录保存在 SQLite
- 不记录原始 JSON / XLS 内容
- 一次调用只保留一条记录，从创建到完成持续更新

## 2. 目标与非目标

### 2.1 目标

本次改动需要实现以下目标：

- 在现有卖家精灵 SQLite 库中新增独立审计表
- 每次 `seller_sprite_run` 成功进入处理链路时创建一条调用记录
- 任务进入运行态、成功、失败时持续更新同一条记录
- 记录调用用户邮箱、调用模式、调用参数、任务结果摘要
- 不改变现有任务目录产物和对外返回结构

### 2.2 非目标

本次明确不做以下内容：

- 不覆盖 `seller_sprite_start`
- 不覆盖非 MCP 入口
- 不新增新的 MCP 查询工具
- 不记录 `raw.json`、`result.json` 的完整内容
- 不记录导出文件内容
- 不新增第二个 SQLite 文件

## 3. 方案选型

候选方案有三种：

1. 在现有 `seller_sprite_task_queue` 表上直接追加审计字段
2. 在现有 SQLite 文件中新增独立审计表
3. 新建独立 SQLite 审计库

最终选择方案 2，原因如下：

- 可以复用现有 `task_queue.sqlite3`，不增加部署和运维复杂度
- 任务调度数据与调用审计数据分表，避免单表职责混杂
- 后续如果要按用户、场景、时间查询调用历史，独立表更清晰
- 当前需求规模较小，没有必要再引入第二个数据库文件

## 4. 数据模型设计

### 4.1 表名

新增表：`seller_sprite_mcp_runs`

### 4.2 字段定义

| 字段名 | 类型 | 说明 |
|------|------|------|
| `job_id` | `TEXT PRIMARY KEY` | 任务唯一标识，关联现有任务队列和任务目录 |
| `user_email` | `TEXT NOT NULL` | MCP 调用用户邮箱 |
| `scenario` | `TEXT NOT NULL` | 卖家精灵场景标识 |
| `mode` | `TEXT NOT NULL` | 调用模式，当前固定为 `browser-route`，保留字段用于历史排查 |
| `params_json` | `TEXT NOT NULL` | 调用参数 JSON 字符串，仅保存参数，不保存结果内容 |
| `result_state` | `TEXT NOT NULL` | 当前状态，取值为 `queued` / `running` / `succeeded` / `failed` |
| `result_row_count` | `INTEGER NOT NULL DEFAULT 0` | 成功时记录导出行数 |
| `result_export_format` | `TEXT NULL` | 导出格式，如 `xlsx` / `json` |
| `result_export_filename` | `TEXT NULL` | 导出文件名 |
| `result_export_job_id` | `TEXT NULL` | 导出关联任务号，当前直接写入 `job_id` |
| `error_json` | `TEXT NULL` | 失败时保存精简错误对象 |
| `created_at` | `TEXT NOT NULL` | 创建时间 |
| `started_at` | `TEXT NULL` | 开始执行时间 |
| `finished_at` | `TEXT NULL` | 完成时间 |
| `updated_at` | `TEXT NOT NULL` | 最近更新时间 |

### 4.3 索引

本期只保留主键，不额外创建索引。原因如下：

- 当前需求只要求记录，不要求暴露查询接口
- 现阶段写入量不大
- 后续若新增列表查询能力，再按真实查询条件补索引

## 5. 状态流转

一条记录的状态流转如下：

1. `seller_sprite_run` 创建任务请求后，插入记录，状态为 `queued`
2. 调度器成功 `claim_next` 后，状态更新为 `running`
3. 任务成功完成后，状态更新为 `succeeded`
4. 任务执行失败或入队失败后，状态更新为 `failed`

约束如下：

- 同一个 `job_id` 只允许存在一条记录
- 所有阶段都更新同一条记录，不新增事件明细行
- `updated_at` 每次状态变化都必须刷新

## 6. 写入时机设计

### 6.1 初始记录

位置：`opscli/mcp/tools/seller_sprite.py` 的 `seller_sprite_run`

步骤：

1. 解析 MCP 调用用户邮箱
2. 构造 `SellerSpriteScenarioRequest`
3. 如果请求中未传 `job_id`，先生成最终会入队使用的 `job_id`
4. 在调用调度器入队前写入 `seller_sprite_mcp_runs`
5. 初始状态写为 `queued`

记录字段：

- `job_id`
- `user_email`
- `scenario`
- `mode`
- `params_json`
- `result_state='queued'`
- `created_at`
- `updated_at`

### 6.2 进入运行态

位置：`opscli/seller_sprite/services/task_scheduler.py`

当调度器 `claim_next` 成功取到任务并准备执行时：

- 更新 `result_state='running'`
- 写入 `started_at`
- 刷新 `updated_at`

### 6.3 成功完成

位置：`opscli/seller_sprite/services/task_scheduler.py`

任务成功完成后更新：

- `result_state='succeeded'`
- `result_row_count`
- `result_export_format`
- `result_export_filename`
- `result_export_job_id=job_id`
- `finished_at`
- `updated_at`
- `error_json=NULL`

### 6.4 失败完成

分两类失败：

1. 入队前后在 MCP 工具层发生异常
2. 调度器执行任务时发生异常

两类失败都统一更新：

- `result_state='failed'`
- `error_json`
- `finished_at`
- `updated_at`

其中：

- 如果异常发生在写入审计记录之前，则不补写失败记录
- 如果异常发生在记录已创建之后，则必须将该记录更新为失败态

## 7. 代码改动范围

### 7.1 `opscli/seller_sprite/services/task_queue_store.py`

新增职责：

- 初始化 `seller_sprite_mcp_runs` 表结构
- 提供以下仓储方法：
  - `create_mcp_run(...)`
  - `mark_mcp_run_running(job_id)`
  - `finish_mcp_run_success(...)`
  - `finish_mcp_run_failed(...)`

设计原则：

- 审计表仍使用当前 SQLite 连接配置
- 审计写入逻辑与任务队列逻辑统一放在同一个仓储内，减少新模块扩散

### 7.2 `opscli/mcp/tools/seller_sprite.py`

新增职责：

- 解析当前 MCP 用户邮箱
- 保证写入审计记录时使用最终 `job_id`
- 在调度器入队前创建调用记录
- 如果入队过程抛错且记录已创建，则补写失败态

### 7.3 `opscli/seller_sprite/services/task_scheduler.py`

新增职责：

- 任务进入运行态时更新审计记录
- 任务成功或失败时更新审计结果摘要

## 8. 用户邮箱来源

本次记录的用户标识固定为 `email`。

邮箱获取原则：

- 优先使用当前 MCP 请求上下文中的用户邮箱
- 如果当前上下文无邮箱，则视为缺少必要身份信息并阻断写入逻辑

本次不引入 `api_key` 哈希兜底，因为需求已经明确指定只记录邮箱。

## 9. 错误处理策略

### 9.1 审计记录创建失败

如果 SQLite 审计记录创建失败：

- 直接让 `seller_sprite_run` 返回错误
- 不允许在“无审计”的情况下继续提交任务

原因：

- 这是用户明确要求的核心功能
- 放行任务但丢失记录会制造“执行成功但不可追踪”的不一致状态

### 9.2 审计状态更新失败

调度阶段如果更新审计状态失败：

- 直接抛出异常，按任务失败处理

原因：

- 调度结果和审计结果必须保持一致
- 本次优先保证一致性，不做“任务成功但审计失败”的弱一致实现

## 10. 测试策略

本次严格按 TDD 实施，最少覆盖以下行为：

### 10.1 仓储层测试

新增 `tests/seller_sprite/test_task_queue_store.py` 用例，覆盖：

- 初始化时自动创建 `seller_sprite_mcp_runs`
- 创建 MCP 调用记录后字段正确
- 标记 `running` 后状态和时间字段正确
- 标记成功后结果摘要字段正确
- 标记失败后错误字段正确

### 10.2 MCP 工具层测试

扩展 `tests/mcp/test_seller_sprite_tools.py`，覆盖：

- `seller_sprite_run` 入队时会创建初始调用记录
- 记录中保存用户邮箱、模式、参数和 `job_id`
- 调度器入队抛错时，已创建记录会被更新为失败态

### 10.3 调度层测试

扩展 `tests/seller_sprite/test_task_scheduler.py`，覆盖：

- 任务开始执行时审计记录变为 `running`
- 任务成功完成时审计记录变为 `succeeded`
- 任务失败时审计记录变为 `failed`

## 11. 验收标准

实现完成后，应满足以下验收标准：

- 调用一次 `seller_sprite_run` 后，SQLite 中存在对应 `job_id` 的审计记录
- 记录中可看到 `user_email`、`scenario`、`mode`、`params_json`
- 任务从排队到完成的过程中，始终只更新同一条记录
- 成功任务可看到 `row_count`、导出格式、导出文件名
- 失败任务可看到精简错误对象
- 不会保存结果 JSON 内容和导出文件内容

## 12. 实施顺序

建议按以下顺序实施：

1. 先为审计仓储能力补测试
2. 实现 SQLite 审计表和仓储方法
3. 为 MCP 工具层补测试
4. 实现 `seller_sprite_run` 的审计创建和失败回写
5. 为调度层补测试
6. 实现 `running` / `succeeded` / `failed` 审计更新
7. 做目标回归测试

