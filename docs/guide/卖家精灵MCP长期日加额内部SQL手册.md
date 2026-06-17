# 卖家精灵MCP长期日加额内部SQL手册

> 仅供内部运维使用，不对普通用户公开。

## 1. 适用范围

- 仅适用于 `seller_sprite` MCP 限额
- 仅适用于长期日加额场景
- 不用于临时余额包、到期失效加额或公开命令行操作

## 2. SQLite 文件位置

默认限额库文件路径：

```text
~/.config/opscli/mcp_quota/quota.sqlite3
```

若部署环境设置了 `OPSCLI_MCP_QUOTA_SQLITE_PATH`，则以该环境变量指向的文件为准。

PowerShell 可先定义库文件变量：

```powershell
$db = "$env:USERPROFILE\.config\opscli\mcp_quota\quota.sqlite3"
```

若使用自定义路径：

```powershell
$db = $env:OPSCLI_MCP_QUOTA_SQLITE_PATH
```

## 3. 操作前建议

先备份原库文件，再执行任何写操作。

```bash
cp ~/.config/opscli/mcp_quota/quota.sqlite3 ~/.config/opscli/mcp_quota/quota.sqlite3.bak
```

PowerShell 备份示例：

```powershell
Copy-Item $db "$db.bak" -Force
```

## 4. 建表 SQL

```sql
CREATE TABLE IF NOT EXISTS mcp_quota_bonus_daily (
    service TEXT NOT NULL,
    email TEXT NOT NULL,
    bonus_daily_limit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (service, email)
);
```

直接执行：

```powershell
sqlite3 $db @"
CREATE TABLE IF NOT EXISTS mcp_quota_bonus_daily (
    service TEXT NOT NULL,
    email TEXT NOT NULL,
    bonus_daily_limit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (service, email)
);
"@
```

如果机器没有 `sqlite3`，可用 Python 标准库：

```powershell
@'
import sqlite3
db = r"""C:\Users\YourUser\.config\opscli\mcp_quota\quota.sqlite3"""
sql = """
CREATE TABLE IF NOT EXISTS mcp_quota_bonus_daily (
    service TEXT NOT NULL,
    email TEXT NOT NULL,
    bonus_daily_limit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (service, email)
);
"""
with sqlite3.connect(db) as conn:
    conn.execute(sql)
'@ | python -
```

## 5. 单用户新增或覆盖长期日加额

将 `a@example.com` 的卖家精灵每日长期加额设为 `3`：

```sql
INSERT INTO mcp_quota_bonus_daily (
    service, email, bonus_daily_limit, created_at, updated_at
)
VALUES (
    'seller_sprite',
    lower(trim('a@example.com')),
    3,
    datetime('now'),
    datetime('now')
)
ON CONFLICT(service, email) DO UPDATE SET
    bonus_daily_limit = excluded.bonus_daily_limit,
    updated_at = excluded.updated_at;
```

直接执行：

```powershell
$email = "a@example.com".Trim().ToLower()
$bonus = 3
sqlite3 $db @"
INSERT INTO mcp_quota_bonus_daily (
    service, email, bonus_daily_limit, created_at, updated_at
)
VALUES (
    'seller_sprite',
    lower(trim('$email')),
    $bonus,
    datetime('now'),
    datetime('now')
)
ON CONFLICT(service, email) DO UPDATE SET
    bonus_daily_limit = excluded.bonus_daily_limit,
    updated_at = excluded.updated_at;
"@
```

## 6. 多用户批量新增或覆盖

```sql
INSERT INTO mcp_quota_bonus_daily (
    service, email, bonus_daily_limit, created_at, updated_at
)
VALUES
    ('seller_sprite', lower(trim('a@example.com')), 2, datetime('now'), datetime('now')),
    ('seller_sprite', lower(trim('b@example.com')), 3, datetime('now'), datetime('now')),
    ('seller_sprite', lower(trim('c@example.com')), 5, datetime('now'), datetime('now'))
ON CONFLICT(service, email) DO UPDATE SET
    bonus_daily_limit = excluded.bonus_daily_limit,
    updated_at = excluded.updated_at;
```

直接执行：

```powershell
sqlite3 $db @"
INSERT INTO mcp_quota_bonus_daily (
    service, email, bonus_daily_limit, created_at, updated_at
)
VALUES
    ('seller_sprite', lower(trim('a@example.com')), 2, datetime('now'), datetime('now')),
    ('seller_sprite', lower(trim('b@example.com')), 3, datetime('now'), datetime('now')),
    ('seller_sprite', lower(trim('c@example.com')), 5, datetime('now'), datetime('now'))
ON CONFLICT(service, email) DO UPDATE SET
    bonus_daily_limit = excluded.bonus_daily_limit,
    updated_at = excluded.updated_at;
"@
```

## 7. 查询当前长期日加额

查询所有卖家精灵长期日加额：

```sql
SELECT service, email, bonus_daily_limit, created_at, updated_at
FROM mcp_quota_bonus_daily
WHERE service = 'seller_sprite'
ORDER BY email;
```

直接执行：

```powershell
sqlite3 -header -column $db @"
SELECT service, email, bonus_daily_limit, created_at, updated_at
FROM mcp_quota_bonus_daily
WHERE service = 'seller_sprite'
ORDER BY email;
"@
```

查询单个邮箱：

```sql
SELECT service, email, bonus_daily_limit, created_at, updated_at
FROM mcp_quota_bonus_daily
WHERE service = 'seller_sprite'
  AND email = lower(trim('a@example.com'));
```

直接执行：

```powershell
$email = "a@example.com".Trim().ToLower()
sqlite3 -header -column $db @"
SELECT service, email, bonus_daily_limit, created_at, updated_at
FROM mcp_quota_bonus_daily
WHERE service = 'seller_sprite'
  AND email = lower(trim('$email'));
"@
```

## 8. 删除长期日加额

删除后，该邮箱恢复为全局默认额度。

```sql
DELETE FROM mcp_quota_bonus_daily
WHERE service = 'seller_sprite'
  AND email = lower(trim('a@example.com'));
```

直接执行：

```powershell
$email = "a@example.com".Trim().ToLower()
sqlite3 $db @"
DELETE FROM mcp_quota_bonus_daily
WHERE service = 'seller_sprite'
  AND email = lower(trim('$email'));
"@
```

## 9. 注意事项

- `email` 必须统一使用小写并去掉首尾空白
- `bonus_daily_limit` 不允许写负数
- `mcp_quota_bonus_daily` 是长期策略表，`mcp_quota_daily` 是每日使用结果表，不要直接修改 `mcp_quota_daily` 代替长期加额
