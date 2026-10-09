# SQLite 迁移开发方案：Quota、卖家精灵账号状态、任务队列

> 文档状态：Quota 已有实现与历史导入验证，2026-09-30 复核发现接入和策略阻塞项；SellerSprite 队列等待最新快照与 schema 核对
>
> 更新时间：2026-10-09
>
> AppHub 站点数据库、Sorftime 离线 SQLite、展示层不在本项目内；在线 Collector/MCP Outbox 建议保留本地补偿并设计清理。

历史核验依据见 [2026-09-30 复核报告](../analysis/SQLite迁移现状与优先级复核-2026-09-30.md)，当前进度见 [迁移 TODO](SQLite迁移-Quota卖家精灵账号状态任务队列TODO.md)。2026-10-09 合入准备中已修复默认 Quota 访问解析器失效导入并通过回归；MySQL 最新西柚策略、启动预检、Monitor 读取适配和队列分页 checkpoint 仍待处理，不能直接上线。

## 1. 范围修正

### 本轮迁移决策

本轮不修改公共 SellerSprite 账号的来源接口，继续保留：

```text
GET /api/v1/integration-accounts?platform=seller_sprite
```

当前优先级为：

1. Quota SQLite -> MySQL 的生产验证与切换收尾；
2. `task_queue.sqlite3` 中任务队列、账号运行状态和 Worker 心跳的 MySQL 迁移设计；
3. 公共账号凭据改用 MySQL 另立后续范围；OPS 接口后端的真实存储引擎尚未确认。

本轮不让 `open-opscli` 直接连接 MySQL 读取公共账号，也不改变 OPS 集成账号接口合同。

| 模块 | 实际来源 | 结论 | 阶段 |
|---|---|---|---|
| MCP quota | `quota.sqlite3` | 真实运行数据，已导入 MySQL | P1 |
| SellerSprite 公共爬虫账号凭据 | OPS `/api/v1/integration-accounts?platform=seller_sprite` | 本轮保持接口和读取链路不变；后端存储迁移另立范围 | 后续 |
| SellerSprite 账号运行状态 | `task_queue.sqlite3` | 事件、隔离和任务账号分配随队列迁移 | P2 |
| SellerSprite 专属账号绑定 | `account_bindings.sqlite3` | OPS 用户邮箱绑定功能，不是公共爬虫账号管理，本项目不迁移 | 排除 |
| SellerSprite 任务队列 | `task_queue.sqlite3` | 旧快照不能直接迁移，需重做 schema 和运行态对账 | P2 |
| SerpAPI SQLite | 已确认停用 | 归档下线，不迁移 | 独立下线 |

此前将 `seller_sprite_user_account_bindings` 误判为公共爬虫账号管理。该表实际保存 OPS 用户邮箱与专属账号的绑定关系，不参与公共账号池调度。本方案已撤销对应 MySQL Store、运行时开关和建表范围。

## 2. 公共爬虫账号真实调用链

生产 SellerSprite 调度器通过以下链路获取公共账号：

1. `SellerSpriteTaskScheduler._ensure_account_provider()` 创建 `SellerSpriteAccountProvider`。
2. 生产调度显式使用 `allow_local_fallback=False`，远端账号源异常时失败关闭。
3. `IntegrationAccountClient.get_accounts("seller_sprite")` 调用 OPS `/api/v1/integration-accounts`。
4. 客户端使用 `INTEGRATION_ACCOUNT_ENCRYPT_KEY` 解密接口返回的用户名和密码。
5. 账号只在当前进程内按平台缓存，默认 TTL 为 600 秒。

因此，open-opscli 本地没有可导出的公共账号 SQLite。本轮不处理 OPS 集成账号后端存储；若后续确认 OPS 后端仍使用 SQLite，需要在 OPS 后端代码库另立迁移范围，不能在本项目中猜测表结构或直接改成 Collector 直连 MySQL。

以下来源不作为生产公共账号迁移源：

- `account_bindings.sqlite3`：用户专属绑定。
- `seller_sprite_legacy/accounts.json` 与系统 Keyring：旧版 CLI 命名账号。
- `OPSCLI_SELLER_SPRITE_ACCOUNTS`：本地兼容配置；生产调度禁止回退。
- `browser_profiles/`：浏览器登录 Profile，是文件/持久卷问题，不是 MySQL 表数据。

## 3. SQLite 中真实使用的账号运行状态

公共账号的凭据不在 SQLite，但以下运行状态位于 `task_queue.sqlite3`，并被生产调度和 Collector Monitor 实际读取：

- `seller_sprite_account_events`：账号拉取、登录失败、重登、接替和会话生命周期事件。
- `seller_sprite_account_quarantine`：认证失败账号的跨进程隔离状态和有效期。
- `seller_sprite_task_queue.assigned_account`、`assigned_account_key`、`last_failed_account_key`、`failover_count`：任务分配和接替状态。
- `seller_sprite_runtime_heartbeats`：Worker 容量和账号工作槽摘要。

这些表不能脱离任务队列单独迁移，否则账号隔离、任务租约和账号互斥会失去一致性。后续统一归入任务队列 MySQL 迁移。

## 4. Quota 迁移状态

`quota.sqlite3` 已完成：

- 完整性检查和 SHA-256 留档；
- policy=7、migration=1、daily=1488、bonus=7 导入；
- MySQL schema、策略读取、reserve 和缓存退款联调；
- `OPSCLI_MCP_QUOTA_BACKEND=mysql` Store 选择验证。

剩余工作包括修复 Quota 默认接入、补齐最新策略与启动预检，再完成真实 MySQL 业务失败退款、源目标聚合对账、生产切换和一个完整北京时间自然日观察。历史联调不代表上述工作已完成。

## 5. 任务队列迁移约束

当前导出的 `task_queue.sqlite3` 是 2026-07-30 前的旧 schema 快照，包含 2 条 `running` 任务，并缺少当前 progress、quarantine、runtime heartbeat、success event 及新 lease 字段。后续必须：

1. 从当前生产实例重新导出一致性快照和 `sqlite_master`。
2. 对任务、账号事件、账号隔离、运行时心跳和进度表做完整字段映射。
3. 清除旧 `session_id`、`jwt` 等不应迁移的敏感字段。
4. 实现 MySQL lease、CAS、assignment generation 和运行账号互斥。
5. 完成多 Worker、崩溃接管、租约过期和重复事件压测。
6. 制定 queued/running 排空与切换 Runbook。

在这些条件完成前，MySQL 队列表仅允许预建，不允许导入生产数据或切换 Worker。

## 6. 误建专属账号表处理

早期错误范围可能已经在目标库创建以下表：

- `seller_sprite_account_schema_versions`
- `seller_sprite_dedicated_accounts`
- `seller_sprite_user_account_bindings`
- `seller_sprite_account_binding_audit`

这些表不是公共爬虫账号池。先核对目标数据库和行数，再使用 `scripts/cleanup_mistaken_seller_sprite_dedicated_account_tables.sql` 清理。该脚本默认拒绝执行，必须人工把确认变量改为 `1`。

## 7. 重复数据和缩表判断

- 公共账号凭据与专属账号绑定职责不同，不能合并。
- `seller_sprite_account_events` 和 `seller_sprite_account_quarantine` 是队列运行状态，不与 OPS 集成账号配置重复。
- 账号事件是审计事实，隔离表是当前状态，两者不能因都含 `account_key` 而合并。
- 只有确认 OPS 集成账号后端的数据模型后，才能判断其与其他 MySQL 凭据表是否重复。
