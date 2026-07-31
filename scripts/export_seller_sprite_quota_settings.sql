-- 从生产 quota.sqlite3 导出 SellerSprite 额度设置。
-- 用法：sqlite3 -batch -bail quota.sqlite3 < 本文件 > seller-sprite-quota-settings.sql

CREATE TEMP TABLE seller_sprite_quota_export_check (
    policy_count INTEGER NOT NULL CHECK (policy_count = 2)
);
INSERT INTO seller_sprite_quota_export_check (policy_count)
SELECT COUNT(*)
FROM mcp_quota_policy
WHERE service = 'seller_sprite'
  AND tool_name IN (
      'seller_sprite_run',
      'seller_sprite_listing_analysis_submit'
  );

SELECT '-- SellerSprite MCP 额度设置，请按敏感文件保管，禁止提交 Git。';
SELECT 'BEGIN IMMEDIATE;';
SELECT 'CREATE TABLE IF NOT EXISTS mcp_quota_policy ('
       || 'tool_name TEXT NOT NULL PRIMARY KEY,'
       || 'service TEXT NOT NULL,'
       || 'daily_limit INTEGER NOT NULL,'
       || 'enabled INTEGER NOT NULL DEFAULT 1,'
       || 'timezone TEXT NOT NULL DEFAULT ''Asia/Shanghai'','
       || 'created_at TEXT NOT NULL,'
       || 'updated_at TEXT NOT NULL);';
SELECT 'CREATE TABLE IF NOT EXISTS mcp_quota_bonus_daily ('
       || 'service TEXT NOT NULL,'
       || 'email TEXT NOT NULL,'
       || 'bonus_daily_limit INTEGER NOT NULL DEFAULT 0,'
       || 'created_at TEXT NOT NULL,'
       || 'updated_at TEXT NOT NULL,'
       || 'PRIMARY KEY (service, email));';

SELECT 'INSERT INTO mcp_quota_policy ('
       || 'tool_name,service,daily_limit,enabled,timezone,created_at,updated_at'
       || ') VALUES ('
       || quote(tool_name) || ','
       || quote(service) || ','
       || daily_limit || ','
       || enabled || ','
       || quote(timezone) || ','
       || quote(created_at) || ','
       || quote(updated_at)
       || ') ON CONFLICT(tool_name) DO UPDATE SET '
       || 'service=excluded.service,'
       || 'daily_limit=excluded.daily_limit,'
       || 'enabled=excluded.enabled,'
       || 'timezone=excluded.timezone,'
       || 'created_at=excluded.created_at,'
       || 'updated_at=excluded.updated_at;'
FROM mcp_quota_policy
WHERE service = 'seller_sprite'
  AND tool_name IN (
      'seller_sprite_run',
      'seller_sprite_listing_analysis_submit'
  )
ORDER BY tool_name;

SELECT 'DELETE FROM mcp_quota_bonus_daily WHERE service=''seller_sprite'';';
SELECT 'INSERT INTO mcp_quota_bonus_daily ('
       || 'service,email,bonus_daily_limit,created_at,updated_at'
       || ') VALUES ('
       || quote(service) || ','
       || quote(email) || ','
       || bonus_daily_limit || ','
       || quote(created_at) || ','
       || quote(updated_at)
       || ');'
FROM mcp_quota_bonus_daily
WHERE service = 'seller_sprite'
ORDER BY email;

SELECT 'COMMIT;';
