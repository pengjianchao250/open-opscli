# SQLite 运行库迁移 MySQL 操作手册

> 状态：Quota 已有实现和历史导入验证，存在待修复上线阻塞；SellerSprite 队列仍处于设计阶段
>
> 更新时间：2026-10-09
>
> 范围：MCP quota、SellerSprite 任务队列及其公共爬虫账号运行状态。

2026-10-09 合入准备中已修复默认 Quota 失效导入，普通用户与专属账号回归通过。上线前仍须处理 [2026-09-30 复核报告](../analysis/SQLite迁移现状与优先级复核-2026-09-30.md) 中的 MySQL 最新策略、启动校验和 Monitor 数据源问题。现有导入记录不能作为已部署或可直接切换的结论。

## 1. 当前可执行范围

本轮迁移决策：公共 SellerSprite 账号接口继续保留，优先迁移本地已确认真实使用的 quota 和任务队列 SQLite。公共账号凭据后端改用 MySQL 不属于本轮切换。

| 模块 | 建表 | 数据迁移 | 运行时切换 |
|---|---|---|---|
| MCP quota | 支持 | 支持 dry-run/apply | 支持显式切换 |
| SellerSprite 公共爬虫账号凭据 | 不在本地 SQLite | 本轮不迁移 | 继续使用 OPS 集成账号接口；后续另立范围 |
| SellerSprite 账号事件和隔离状态 | 随队列表预建 | 暂不支持 | 禁止切换 |
| SellerSprite 任务队列 | 仅预建 | 暂不支持 | 禁止切换 |
| SellerSprite 专属用户账号绑定 | 不处理 | 不迁移 | 保持现有 SQLite 加密实现 |

公共爬虫账号与专属用户绑定是两套独立逻辑。`seller_sprite_user_account_bindings` 保存 OPS 用户邮箱到专属账号的绑定关系，不是公共爬虫账号池。

## 2. 公共爬虫账号来源

生产调度通过 OPS 集成账号接口读取 SellerSprite 公共账号：

```text
GET /api/v1/integration-accounts?platform=seller_sprite
```

open-opscli 只在进程内缓存解密后的账号，默认 TTL 为 600 秒，不把公共账号凭据写入 SQLite。生产调度使用 `allow_local_fallback=False`，接口异常或返回空账号时失败关闭。

因此：

- 不导出 `account_bindings.sqlite3` 作为公共爬虫账号迁移源。
- 不使用 `.account_bindings.key` 迁移公共账号。
- 不把 `seller_sprite_legacy/accounts.json` 或系统 Keyring 当作生产账号源。
- 若需要迁移 OPS 集成账号的底层存储，必须在 OPS 后端仓库确认其数据库和表结构后另立方案。

SQLite 中真实使用的公共账号运行状态位于 `task_queue.sqlite3`：

- `seller_sprite_account_events`
- `seller_sprite_account_quarantine`
- 任务行中的账号分配、失败账号和接替次数字段
- `seller_sprite_runtime_heartbeats`

这些状态与任务租约和账号互斥耦合，后续必须随任务队列整体迁移。

## 3. 当前生产导出状态

已收到的生产 opscli SQLite 导出位于：

```text
D:\Gitlab\open-opscli-worktrees\sqlite_tmp
```

已确认：

- `quota.sqlite3` 完整性通过并已导入 MySQL。
- `task_queue.sqlite3` 是截至 2026-07-30 的旧 schema 快照，包含 2 条 `running` 任务，不得直接迁移。
- `mcp.sqlite3` 只有已完成的 collection outbox 数据，不能当作完整 collect 导出。
- `serpapi.sqlite3` 没有 key 数据，已确认不再使用，单独归档下线。

## 4. MySQL 建表

建表文件：

```text
scripts/create_sqlite_runtime_mysql_tables_v1.sql
```

当前版本只创建 quota 和 SellerSprite 队列预建表，不再创建专属账号绑定表。

```bash
mysql --default-character-set=utf8mb4 \
  -h <mysql-host> \
  -P 3306 \
  -u <ddl-user> \
  -p \
  <database> \
  < scripts/create_sqlite_runtime_mysql_tables_v1.sql
```

脚本结尾必须满足：

```text
mcp_quota_migration_ready = 1
queue_schema_precreated = 1
```

`queue_schema_precreated = 1` 只表示空表存在，不表示允许迁移生产任务或切换 Worker。

## 5. MySQL 连接配置

```bash
OPSCLI_RUNTIME_MYSQL_HOST=<mysql-host>
OPSCLI_RUNTIME_MYSQL_PORT=3306
OPSCLI_RUNTIME_MYSQL_DATABASE=<database>
OPSCLI_RUNTIME_MYSQL_USER=<runtime-user>
OPSCLI_RUNTIME_MYSQL_PASSWORD=<secret>
# OPSCLI_RUNTIME_MYSQL_SSL_CA=/etc/opscli/mysql-ca.pem
OPSCLI_RUNTIME_MYSQL_CONNECT_TIMEOUT_SECONDS=10
```

未设置专用变量时，会回退到 `OPSCLI_COLLECTION_MYSQL_*`。当前可运行的 quota 账号只需要以下五张表的相应权限：

```text
mcp_quota_schema_versions
mcp_quota_policy
mcp_quota_migrations
mcp_quota_daily
mcp_quota_bonus_daily
```

队列表在切换方案批准前不要授予生产 Worker 写权限。

## 6. Quota 数据迁移

### 6.1 一致性快照

```bash
sqlite3 /var/lib/opscli/mcp_quota/quota.sqlite3 \
  ".backup '/backup/quota-final.sqlite3'"

sqlite3 /backup/quota-final.sqlite3 "PRAGMA integrity_check;"
sha256sum /backup/quota-final.sqlite3
```

### 6.2 Dry-run

```bash
python -m opscli.migrations.sqlite_runtime quota \
  --sqlite /backup/quota-final.sqlite3
```

### 6.3 正式导入

```bash
python -m opscli.migrations.sqlite_runtime quota \
  --sqlite /backup/quota-final.sqlite3 \
  --apply
```

默认拒绝写入非空目标表。只有完成差异审查后，才允许使用 `--allow-nonempty`。

### 6.4 切换

```bash
OPSCLI_MCP_QUOTA_BACKEND=mysql
```

MySQL 读写异常会阻断受限 Tool。当前 `check_schema()` 尚未接入默认工厂，schema/策略完整性必须补齐启动预检后才能切换，不能仅凭环境变量认为版本校验已生效。

## 7. Quota 核对

```sql
SELECT COUNT(*) FROM mcp_quota_policy;
SELECT COUNT(*) FROM mcp_quota_migrations;
SELECT COUNT(*) FROM mcp_quota_daily;
SELECT COUNT(*) FROM mcp_quota_bonus_daily;

SELECT service, quota_day, COUNT(*) AS identities,
       SUM(calls) AS calls, SUM(failures) AS failures
FROM mcp_quota_daily
GROUP BY service, quota_day
ORDER BY quota_day, service;
```

MySQL 已产生新扣减后不能直接切回旧 SQLite，否则会导致额度倒退。

## 8. 误建专属账号表清理

早期错误范围可能已经创建：

```text
seller_sprite_account_schema_versions
seller_sprite_dedicated_accounts
seller_sprite_user_account_bindings
seller_sprite_account_binding_audit
```

这些表不属于公共爬虫账号管理。先在目标连接执行：

```sql
SELECT DATABASE(), @@hostname, @@port;
SELECT COUNT(*) FROM seller_sprite_dedicated_accounts;
SELECT COUNT(*) FROM seller_sprite_user_account_bindings;
SELECT COUNT(*) FROM seller_sprite_account_binding_audit;
```

确认连接和数据均来自本次误建后，使用：

```text
scripts/cleanup_mistaken_seller_sprite_dedicated_account_tables.sql
```

脚本默认将确认变量设为 `0` 并主动失败。执行人员必须检查数据库名和行数，再把：

```sql
SET @confirm_drop_mistaken_dedicated_account_tables := 0;
```

改成：

```sql
SET @confirm_drop_mistaken_dedicated_account_tables := 1;
```

清理不会修改 `seller_sprite_account_events`、`seller_sprite_account_quarantine`、任务表或浏览器 Profile。

同时从服务启动配置中移除误加的：

```text
OPSCLI_SELLER_SPRITE_ACCOUNT_BINDING_BACKEND=mysql
```

专属用户绑定继续使用原有加密 SQLite；本次不导出、不迁移、不切换。

## 9. 任务队列与账号状态后续迁移

当前没有队列 MySQL 运行时适配器和数据迁移命令。下一阶段必须先取得当前生产一致性快照，然后完成：

1. 当前 schema 与 MySQL DDL 字段映射。
2. queued/running、lease、Worker 心跳和账号占用对账。
3. 账号事件和隔离状态的幂等迁移设计。
4. 旧 `session_id`、`jwt` 等敏感字段清理。
5. MySQL lease/CAS/assignment generation 和账号互斥实现。
6. 多 Worker、崩溃接管、租约过期和重启压测。
7. 排空、切换和回滚 Runbook。

在此之前禁止导入旧 `running` 任务、设置未定义的队列后端变量或启动 MySQL Worker。
