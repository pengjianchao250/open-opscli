# MCP 限额 SQLite 策略表设计

## 背景

当前 MCP quota 的策略配置来自 `opscli/mcp/configs/mcp-quota.json`。线上修改该 JSON 后，运行中的 MCP 服务不会自动重新加载配置，需要重启服务才能生效，运维成本较高。

本设计将 MCP quota 的策略配置迁移到 SQLite 表。运行时只读取 SQLite，线上直接修改 SQLite 表后，下一次 MCP tool 调用立即使用新策略。

## 目标

1. 使用 SQLite 表保存 MCP tool 限额策略。
2. 运行时不再读取 `mcp-quota.json`。
3. 线上直接 SQL 修改策略后，无需重启 MCP 服务即可生效。
4. 保留现有每日用量、失败退回、长期日加额和身份识别逻辑。
5. 首次部署时，如果策略表为空，写入代码默认策略。

## 非目标

1. 不新增 quota 运维 CLI。
2. 不新增 quota 管理 MCP tool。
3. 不从旧 JSON 自动迁移线上额度。
4. 不改变 `quota` 响应字段结构。
5. 不改变 `mcp_quota_daily` 和 `mcp_quota_bonus_daily` 的核心语义。

## 架构设计

### 配置源

SQLite 是 MCP quota 策略的唯一运行时配置源。以下 JSON 配置链路会被删除：

- `QuotaConfig`
- `load_quota_config()`
- `_find_quota_config_path()`
- `_working_directory_quota_config_path()`
- `_project_quota_config_path()`
- `_packaged_quota_config_path()`
- `_parse_sqlite_path()`
- `_merge_policy_config()`
- `ENV_QUOTA_CONFIG_PATH`
- `opscli/mcp/configs/mcp-quota.json`
- `pyproject.toml` 中的 `mcp/configs/mcp-quota.json` package-data 配置

保留以下环境变量：

- `OPSCLI_MCP_QUOTA_ENABLED`：quota 总开关，关闭后受限工具直接放行。
- `OPSCLI_MCP_QUOTA_SQLITE_PATH`：指定 quota SQLite 文件路径；不设置时使用 `CONFIG_DIR / "mcp_quota" / "quota.sqlite3"`。

### 职责划分

#### `QuotaPolicy`

`QuotaPolicy` 继续作为运行时策略对象，字段保持为：

- `tool_name`
- `service`
- `daily_limit`
- `timezone`

数据来源从 JSON 改为 SQLite 表行。

#### `SQLiteQuotaStore`

`SQLiteQuotaStore` 统一管理 quota SQLite 数据：

- `mcp_quota_policy`：tool 基础限额策略。
- `mcp_quota_daily`：每日用量记录。
- `mcp_quota_bonus_daily`：邮箱长期日加额。

初始化 schema 时创建三张表。如果 `mcp_quota_policy` 为空，写入 `default_quota_policies()` 返回的代码默认策略。如果表非空，不覆盖任何线上手工修改。

#### `QuotaLimiter`

`QuotaLimiter` 不再持有启动时加载的 `policies` 字典。每次调用都从 `SQLiteQuotaStore` 动态读取策略：

- 无策略：该 tool 不受限，直接放行。
- 策略 `enabled = 0`：该 tool 暂不受限，直接放行。
- 策略 `enabled = 1`：执行身份解析、限额占用和调用后结算。

`quota_snapshot(tool_name)` 也动态读取策略。

#### `get_quota_limiter()`

`get_quota_limiter()` 不再调用 JSON 配置加载函数，只负责创建默认 limiter：

1. 读取 `OPSCLI_MCP_QUOTA_SQLITE_PATH`。
2. 创建 `SQLiteQuotaStore`。
3. 创建 `QuotaLimiter`。

quota 是否启用只由 `OPSCLI_MCP_QUOTA_ENABLED` 判断。

## 表结构设计

新增表：`mcp_quota_policy`。

```sql
CREATE TABLE IF NOT EXISTS mcp_quota_policy (
    tool_name TEXT NOT NULL PRIMARY KEY,
    service TEXT NOT NULL,
    daily_limit INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `tool_name` | MCP tool 函数名，例如 `seller_sprite_run`。 |
| `service` | 业务服务名，例如 `seller_sprite`、`keepa`。 |
| `daily_limit` | 每个身份每天基础成功调用次数，必须大于 0。 |
| `enabled` | `1` 表示启用限额，`0` 表示该 tool 直接放行。 |
| `timezone` | 统计自然日时区，当前使用 `Asia/Shanghai`。 |
| `created_at` | 策略创建时间。 |
| `updated_at` | 策略更新时间。 |

首次初始化默认写入：

| tool_name | service | daily_limit | enabled |
| --- | --- | --- | --- |
| `keepa_run` | `keepa` | 5 | 1 |
| `seller_sprite_run` | `seller_sprite` | 5 | 1 |
| `seller_sprite_listing_analysis_submit` | `seller_sprite` | 5 | 1 |

这些默认值来自代码内的 `default_quota_policies()`，不读取旧 JSON。

## 直接 SQL 运维方式

查看策略：

```sql
SELECT tool_name, service, daily_limit, enabled, timezone, updated_at
FROM mcp_quota_policy
ORDER BY tool_name;
```

修改卖家精灵 run 每日额度为 100：

```sql
UPDATE mcp_quota_policy
SET daily_limit = 100,
    updated_at = datetime('now')
WHERE tool_name = 'seller_sprite_run';
```

修改 Listing Analysis submit 每日额度为 10：

```sql
UPDATE mcp_quota_policy
SET daily_limit = 10,
    updated_at = datetime('now')
WHERE tool_name = 'seller_sprite_listing_analysis_submit';
```

关闭某个 tool 的限额：

```sql
UPDATE mcp_quota_policy
SET enabled = 0,
    updated_at = datetime('now')
WHERE tool_name = 'seller_sprite_run';
```

恢复启用：

```sql
UPDATE mcp_quota_policy
SET enabled = 1,
    updated_at = datetime('now')
WHERE tool_name = 'seller_sprite_run';
```

新增未来 tool 的限额策略：

```sql
INSERT INTO mcp_quota_policy (
    tool_name, service, daily_limit, enabled, timezone, created_at, updated_at
)
VALUES (
    'xiyou_run', 'xiyou', 10, 1, 'Asia/Shanghai', datetime('now'), datetime('now')
);
```

## 调用数据流

### 普通 tool 调用

1. MCP tool 被调用，例如 `seller_sprite_run`。
2. `_quota_wrap()` 调用 `QuotaLimiter.before_call("seller_sprite_run")`。
3. 如果 `OPSCLI_MCP_QUOTA_ENABLED` 关闭，直接放行。
4. `QuotaLimiter` 从 `SQLiteQuotaStore` 读取 `mcp_quota_policy` 中的最新策略。
5. 无策略或 `enabled = 0` 时直接放行。
6. `enabled = 1` 时解析当前身份：邮箱优先，本地凭证邮箱次之，API Key hash 兜底。
7. 调用 `SQLiteQuotaStore.reserve(policy, identity)` 占用一次额度。
8. 如果超限，返回 `MCP_QUOTA_EXCEEDED`。
9. 如果未超限，执行真实业务 tool。
10. 业务返回 `success = false` 时，调用 `refund_failure()` 退回本次调用次数并累计失败次数。
11. 业务成功时，响应顶层追加 `quota` 快照。
12. 业务抛异常时，`after_exception()` 尝试退回调用次数，然后继续抛出原异常。

### quota-status 调用

`keepa_quota_status()` 和 `seller_sprite_quota_status()` 继续调用 `QuotaLimiter.quota_snapshot()`。

新逻辑：

1. 动态读取 `mcp_quota_policy`。
2. 如果 tool 无策略或 disabled，返回错误，提示该 tool 当前未启用限额策略。
3. 如果 enabled，读取当前身份对应的额度快照。
4. 返回 `limit / used / remaining / failures / reset_at`。

## 错误处理

| 场景 | 普通业务 tool 行为 | quota-status 行为 |
| --- | --- | --- |
| 无策略 | 直接放行 | 返回无策略错误 |
| `enabled = 0` | 直接放行 | 返回策略禁用错误 |
| 身份缺失 | 返回 `MCP_QUOTA_IDENTITY_MISSING` | 返回身份缺失错误 |
| SQLite 不可用 | 返回 `MCP_QUOTA_UNAVAILABLE` | 返回读取失败错误 |
| `daily_limit <= 0` 或字段非法 | 返回 `MCP_QUOTA_UNAVAILABLE` | 返回读取失败错误 |
| 超限 | 返回 `MCP_QUOTA_EXCEEDED` | 不适用 |

SQLite 仍是限额的强依赖。只要策略启用，SQLite 连接失败、schema 初始化失败、策略字段非法或用量更新失败，都阻断受限 tool，避免存储故障导致绕过每日限额。

## 并发行为

用量占用继续使用 `BEGIN IMMEDIATE` 获取 SQLite 写锁，确保同一台 MCP 服务机器上的并发请求不会超卖额度。策略读取每次调用执行，修改 `daily_limit`、`enabled`、新增策略或删除策略后，下一次调用立即生效。

## 测试计划

调整 `tests/mcp/test_quota.py`：

1. 删除 JSON 配置读取相关测试。
2. 新增策略表自动初始化测试。
3. 新增非空策略表不覆盖测试。
4. 新增动态读取策略测试。
5. 新增 disabled 策略直接放行测试。
6. 新增删除策略直接放行测试。
7. 新增非法策略阻断测试。
8. 保留并调整每日用量持久化、失败退回、长期日加额、快照读取和 SQLite 不可用测试。

同时运行受影响的 MCP tool 测试：

```bash
pytest tests/mcp/test_quota.py -v
pytest tests/mcp/test_seller_sprite_tools.py -v
pytest tests/mcp/test_keepa_tools.py -v
```

如果 package-data 变化需要验证构建，再运行：

```bash
python -m build
```

## 迁移说明

本次不从旧 `mcp-quota.json` 自动迁移额度。首次发布后，空策略表会写入代码默认值：

```text
keepa_run = 5
seller_sprite_run = 5
seller_sprite_listing_analysis_submit = 5
```

如果线上要保持当前旧 JSON 中的额度，需要发布后直接 SQL 更新：

```sql
UPDATE mcp_quota_policy
SET daily_limit = 200, updated_at = datetime('now')
WHERE tool_name = 'keepa_run';

UPDATE mcp_quota_policy
SET daily_limit = 100, updated_at = datetime('now')
WHERE tool_name = 'seller_sprite_run';

UPDATE mcp_quota_policy
SET daily_limit = 10, updated_at = datetime('now')
WHERE tool_name = 'seller_sprite_listing_analysis_submit';
```

## 回滚方式

代码层回滚本次提交即可。旧代码不会读取 `mcp_quota_policy`，因此数据层不需要处理。

如果需要清理策略表，可以手工执行：

```sql
DROP TABLE IF EXISTS mcp_quota_policy;
```
