# SQLite 迁移 TODO：Quota、卖家精灵账号状态、任务队列

> 更新时间：2026-10-09
>
> `[x]` 完成；`[~]` 部分完成；`[ ]` 待执行；`[!]` 硬前置；`[-]` 不处理。

## 本次代码合入

- `[x]` 修复 Quota 对已删除 `get_account_binding_store` 的引用，恢复现有 SQLite 专属绑定读取；补普通用户与专属账号默认解析回归。
- `[ ]` 将 Quota MySQL Store、导入工具、SQL、测试和文档合入主仓库当前 `feature/sellersprite` 分支并完成回归。
- `[!]` 合并代码不代表生产切换；MySQL 最新策略、启动预检、Monitor 数据源适配、真实并发与生产对账仍待完成。
- `[!]` 队列 DDL 仍为旧预建草案，不支持直接切换最新队列运行时。

## 0. 2026-09-30 深度复核

详见 [现状与优先级复核](../analysis/SQLite迁移现状与优先级复核-2026-09-30.md)。历史导入、联调成功不等于当前生产已切换。

- `[x]` 核对主仓库 `676e1d91` 和迁移 worktree `b4f98a69`；迁移实现仍未提交，主仓库相对旧基线已有 39 个提交。
- `[x]` 七个本地快照只读完整性、结构、行数、状态和关系核验；定向测试本次 `41 passed`。
- `[x]` 2026-10-09 修复 Quota 默认访问解析器失效引用；9 月 30 日已隔离复现 `MCP_QUOTA_ACCESS_UNAVAILABLE`。
- `[!]` 合入最新策略并为 MySQL 核对/补齐 `ext_xydc_openapi_call`，保留生产人工额度设置。
- `[!]` 把 MySQL schema/策略预检接入启动路径；现有 `check_schema()` 仅显式执行，DDL readiness 只统计表数。
- `[!]` 重新核对最新队列 schema，补入 `seller_sprite_product_checkpoints`，旧 DDL 不是最新可上线合同。
- `[!]` 制定历史孤立运行记录处理方式：旧快照有 202 条 failed MCP 记录没有 queue 行，直接导入会违反目标外键。
- `[ ]` 适配 Monitor 后端对 quota/任务队列的读取数据源；已确认业务 SQLite 连接只读，自有状态库另行写入，不涉及展示开发。
- `[ ]` 为在线 `collection_storage/mcp.sqlite3` 和 `collector.sqlite3` 制定 completed 保留期/对账清理，优先保留本地故障补偿。
- `[ ]` 评估 `collector_monitor/state.sqlite3` 的多实例需求及隐藏会话事件库的归并/归档。
- `[!]` 不使用旧快照配合 `--allow-nonempty` 覆盖已经产生新调用的 MySQL 日计数。

## 1. 范围

- `[x]` Quota 纳入本项目。
- `[x]` SellerSprite 公共爬虫账号运行状态随任务队列纳入本项目。
- `[-]` SellerSprite 专属用户账号绑定；`account_bindings.sqlite3` 不迁移。
- `[-]` AppHub 站点数据库、Sorftime 离线 SQLite、展示层。
- `[x]` 在线 Collector/MCP Outbox 属于实际运行链路，区别于 Sorftime 离线 SQLite；本轮建议保留并治理。
- `[x]` SerpAPI SQLite 已确认停用，不迁移。

## 2. 范围纠正

- `[x]` 确认 `seller_sprite_user_account_bindings` 是 OPS 用户邮箱专属账号绑定，不是公共爬虫账号池。
- `[x]` 已撤销专属账号 MySQL Store、明文密码字段和运行时切换开关；Quota 失效工厂引用已修复。
- `[x]` 从统一建表 SQL 中移除专属账号绑定四张表。
- `[x]` 专属账号 Store 已恢复 SQLite 加密实现；默认 Quota 接入恢复原 Store，并补回归测试。
- `[x]` 提供误建表清理脚本，默认带人工确认门禁。
- `[ ]` 在正确 MySQL 实例核对误建表行数和使用方后再清理。
- `[!]` 清理前禁止选择、导出或记录 `password_plaintext`。

## 3. 公共爬虫账号源

- `[x]` 确认生产账号通过 OPS `/api/v1/integration-accounts?platform=seller_sprite` 获取。
- `[x]` 本轮保持该接口和现有读取链路不变，不改为 open-opscli 直连 MySQL。
- `[x]` 本轮优先处理 quota、任务队列及其账号运行状态等本地 SQLite。
- `[x]` 确认生产调度 `allow_local_fallback=False`，远端异常时不会读取本地账号。
- `[x]` 确认账号凭据只做进程内 TTL 缓存，不落本地 SQLite。
- `[x]` 确认旧 `seller_sprite_legacy/accounts.json` 和 Keyring 不属于当前生产调用链。
- `[ ]` 【后续范围】确认 OPS 集成账号后端实际存储引擎、表结构和运维责任方。
- `[ ]` 【后续范围】如果 OPS 后端仍使用 SQLite，在对应后端仓库另立迁移方案。
- `[ ]` 【后续范围】验证生产账号增删、启停、排序和密码轮换后，Collector 最迟在缓存 TTL 后刷新。

## 4. Quota

- `[~]` MySQL Store、DDL、迁移命令和已有回归测试完成；默认接入、最新策略及启动预检待补齐，尚不可直接上线。
- `[x]` 导入 policy=7、migration=1、daily=1488、bonus=7。
- `[x]` 完成真实 MySQL schema、策略读取、reserve 和缓存退款联调。
- `[x]` 验证 `OPSCLI_MCP_QUOTA_BACKEND=mysql` 选择 `MySqlQuotaStore`。
- `[ ]` 验证业务失败退款：`calls` 恢复且 `failures + 1`。
- `[~]` 已复核本地 SQLite 服务聚合；仍需对比当前 MySQL 服务、日期、calls、failures 聚合。
- `[ ]` 完成生产切换和一个北京时间自然日观察。
- `[!]` MySQL 已产生新扣减后禁止直接切回 SQLite。

## 5. 账号运行状态与任务队列

- `[x]` 确认 `seller_sprite_account_events` 被调度器写入、Monitor 读取。
- `[x]` 确认 `seller_sprite_account_quarantine` 被账号池跨进程读取和更新。
- `[x]` 确认任务行的账号分配、失败账号和接替次数与队列事务耦合。
- `[x]` 当前 MySQL DDL 仅预建队列及账号状态表，不提供运行时切换。
- `[ ]` 从当前生产实例重新导出 `task_queue.sqlite3` 一致性快照。
- `[ ]` 保存完整 `sqlite_master`、表行数、状态分布、哈希和 WAL 处理记录。
- `[ ]` 对 running、lease、账号隔离、Worker 心跳和 browser 会话做切换前对账。
- `[ ]` 设计并实现 MySQL lease、CAS、assignment generation 和账号互斥。
- `[ ]` 设计账号事件与隔离状态的幂等迁移键和过期数据策略。
- `[ ]` 对分页 checkpoint、Monitor 业务数据读取和独立 session events 库补充迁移映射；Monitor 自有状态库单独评估。
- `[ ]` 确认历史 MCP 记录的外键兼容与归档策略，不伪造待执行任务补外键。
- `[ ]` 删除或引用化旧 `session_id`、`jwt` 等敏感字段，禁止原样入库。
- `[ ]` 完成多 Worker、崩溃接管、租约过期、重复事件和 MySQL 重启压测。
- `[ ]` 制定 queued/running 排空、切换和回滚 Runbook。
- `[!]` 禁止直接 INSERT 旧快照或迁移生产 `running` 任务。

## 6. 重复数据与缩表

- `[ ]` 【后续范围】获取 OPS 集成账号后端数据模型，确认是否已是 MySQL。
- `[ ]` 【后续范围】比较 OPS 集成账号配置、队列账号事件和账号隔离状态的职责与业务键。
- `[x]` 专属用户绑定与公共爬虫账号池职责不同，不合并。
- `[x]` 账号事件审计与当前隔离状态职责不同，不合并。
- `[x]` 本次 mcp Outbox 快照有 3570 条 completed，无待办；不代表当前生产及 Collector Outbox 无积压。
- `[ ]` 按来源三元键及 MySQL `persistence_completed_at` 核实后，设计历史 completed 清理；保留 cutover、对账游标和幂等保障。
- `[x]` 本次 SerpAPI 快照为零行，另三份 4096 字节 SQLite 无表，无需迁移这些副本。
- `[ ]` 检查代码、服务、监控和定时任务对旧表的引用后再提出删除建议。

## 7. 阶段出口

- `[ ]` 阶段 A：修复 Quota 接入、完成最新策略与预检；误建专属账号表清理单独核实，不阻塞代码修复。
- `[ ]` 阶段 B：Quota 完成生产切换和自然日观察。
- `[ ]` 阶段 C（后续范围）：OPS 公共账号源完成后端存储确认和刷新联调；本轮不执行。
- `[ ]` 阶段 D：任务队列及账号运行状态完成设计、压测和生产 Runbook。
