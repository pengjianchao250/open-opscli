-- collection_storage Schema v1/v2 -> v3
--
-- Preconditions:
-- 1. Run with MySQL 8.0 and a DDL-capable migration account.
-- 2. Select the collection storage database before running this file.
-- 3. Stop every general MCP and Collector MCP process that uses this database.
-- 4. Back up the database and reserve a maintenance window for the backfill/index.
--
-- MySQL DDL auto-commits. This script is restartable after a partial failure:
-- existing columns/indexes/tables are skipped, and the schema version is written last.

SELECT DATABASE() AS migration_database;

SELECT module_name, schema_version, updated_at
FROM collection_schema_versions
WHERE module_name = 'collector_storage';

SET @collection_schema_name := DATABASE();
SET @collection_existing_schema_version := COALESCE(
    (
        SELECT schema_version
        FROM collection_schema_versions
        WHERE module_name = 'collector_storage'
    ),
    0
);

-- v2: materialize the cache identity currently stored in request_params._cache.
SET @collection_migration_sql := IF(
    EXISTS(
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = @collection_schema_name
          AND TABLE_NAME = 'collection_runs'
          AND COLUMN_NAME = 'request_fingerprint'
    ),
    'SELECT ''request_fingerprint already exists'' AS migration_status',
    'ALTER TABLE collection_runs ADD COLUMN request_fingerprint CHAR(64) NULL AFTER request_params'
);
PREPARE collection_migration_stmt FROM @collection_migration_sql;
EXECUTE collection_migration_stmt;
DEALLOCATE PREPARE collection_migration_stmt;

SET @collection_migration_sql := IF(
    EXISTS(
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = @collection_schema_name
          AND TABLE_NAME = 'collection_runs'
          AND COLUMN_NAME = 'cache_scope'
    ),
    'SELECT ''cache_scope already exists'' AS migration_status',
    'ALTER TABLE collection_runs ADD COLUMN cache_scope VARCHAR(128) NULL AFTER request_fingerprint'
);
PREPARE collection_migration_stmt FROM @collection_migration_sql;
EXECUTE collection_migration_stmt;
DEALLOCATE PREPARE collection_migration_stmt;

UPDATE collection_runs
SET request_fingerprint = COALESCE(
        request_fingerprint,
        JSON_UNQUOTE(JSON_EXTRACT(request_params, '$._cache.cache_key'))
    ),
    cache_scope = COALESCE(
        cache_scope,
        JSON_UNQUOTE(JSON_EXTRACT(request_params, '$._cache.cache_scope'))
    )
WHERE request_params IS NOT NULL
  AND (
      (
          request_fingerprint IS NULL
          AND JSON_EXTRACT(request_params, '$._cache.cache_key') IS NOT NULL
      )
      OR (
          cache_scope IS NULL
          AND JSON_EXTRACT(request_params, '$._cache.cache_scope') IS NOT NULL
      )
  );

SET @collection_migration_sql := IF(
    EXISTS(
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = @collection_schema_name
          AND TABLE_NAME = 'collection_runs'
          AND INDEX_NAME = 'ix_collection_runs_cache_lookup'
    ),
    'SELECT ''ix_collection_runs_cache_lookup already exists'' AS migration_status',
    'CREATE INDEX ix_collection_runs_cache_lookup ON collection_runs (source_system, data_environment, scenario, site, request_fingerprint, cache_scope, persistence_completed_at)'
);
PREPARE collection_migration_stmt FROM @collection_migration_sql;
EXECUTE collection_migration_stmt;
DEALLOCATE PREPARE collection_migration_stmt;

-- v3: user-managed prefetch schedules and their independently leased runs.
CREATE TABLE IF NOT EXISTS collection_prefetch_schedules (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    schedule_name VARCHAR(191) NOT NULL,
    source_system VARCHAR(64) NOT NULL,
    scenario VARCHAR(128) NOT NULL,
    request_json JSON NOT NULL,
    cadence VARCHAR(32) NOT NULL DEFAULT 'daily',
    run_time TIME NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    next_run_at DATETIME(6) NOT NULL,
    created_by VARCHAR(254) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    KEY ix_prefetch_schedules_due (
        source_system, enabled, next_run_at
    ),
    KEY ix_prefetch_schedules_owner (created_by, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS collection_prefetch_runs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    schedule_id BIGINT UNSIGNED NOT NULL,
    source_system VARCHAR(64) NOT NULL,
    scenario VARCHAR(128) NOT NULL,
    request_json JSON NOT NULL,
    trigger_type VARCHAR(32) NOT NULL,
    scheduled_for DATETIME(6) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    execution_owner VARCHAR(191) NULL,
    lease_expires_at DATETIME(6) NULL,
    source_job_id VARCHAR(191) NULL,
    error_code VARCHAR(128) NULL,
    error_message VARCHAR(500) NULL,
    started_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_prefetch_runs_schedule
        FOREIGN KEY (schedule_id) REFERENCES collection_prefetch_schedules(id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_prefetch_scheduled_run (
        schedule_id, trigger_type, scheduled_for
    ),
    KEY ix_prefetch_runs_claim (
        source_system, status, scheduled_for, lease_expires_at
    ),
    KEY ix_prefetch_runs_schedule_time (schedule_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Only publish v3 after all required objects are present. A zero value leaves the
-- previous schema version unchanged; inspect the verification result below.
SET @collection_schema_ready := (
    SELECT
        (
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = @collection_schema_name
              AND TABLE_NAME = 'collection_runs'
              AND COLUMN_NAME IN ('request_fingerprint', 'cache_scope')
        ) = 2
        AND (
            SELECT GROUP_CONCAT(
                COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ','
            )
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = @collection_schema_name
              AND TABLE_NAME = 'collection_runs'
              AND INDEX_NAME = 'ix_collection_runs_cache_lookup'
        ) = CONCAT(
            'source_system,data_environment,scenario,site,',
            'request_fingerprint,cache_scope,persistence_completed_at'
        )
        AND (
            SELECT COUNT(*)
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = @collection_schema_name
              AND TABLE_NAME IN (
                  'collection_prefetch_schedules',
                  'collection_prefetch_runs'
              )
        ) = 2
        AND @collection_existing_schema_version <= 3
);

INSERT INTO collection_schema_versions (module_name, schema_version)
SELECT 'collector_storage', 3
WHERE @collection_schema_ready = 1
ON DUPLICATE KEY UPDATE schema_version = GREATEST(
    schema_version,
    3
);

-- Post-migration verification. migration_ready must be 1 and schema_version must be 3.
SELECT @collection_schema_ready AS migration_ready;

SELECT module_name, schema_version, updated_at
FROM collection_schema_versions
WHERE module_name = 'collector_storage';

SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = @collection_schema_name
  AND TABLE_NAME = 'collection_runs'
  AND COLUMN_NAME IN ('request_fingerprint', 'cache_scope')
ORDER BY ORDINAL_POSITION;

SELECT INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = @collection_schema_name
  AND TABLE_NAME = 'collection_runs'
  AND INDEX_NAME = 'ix_collection_runs_cache_lookup'
ORDER BY SEQ_IN_INDEX;

SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = @collection_schema_name
  AND TABLE_NAME IN (
      'collection_prefetch_schedules',
      'collection_prefetch_runs'
  )
ORDER BY TABLE_NAME;
