-- SQLite runtime stores -> MySQL schema v1
-- Generated: 2026-09-20
--
-- Scope:
--   1. MCP quota                         (may be created before application cutover)
--   2. SellerSprite task queue          (PRE-CREATE ONLY; do not cut traffic yet)
--
-- Preconditions:
--   1. Run on MySQL 8.0 with a DDL-capable migration account.
--   2. Select the target database before running this file.
--   3. Confirm no conflicting tables exist with a different schema.
--   4. Back up the target database before execution.
--
-- This file creates empty target tables only. It does not read SQLite, migrate
-- production data, change application configuration, or switch runtime traffic.
-- MySQL DDL auto-commits. CREATE TABLE IF NOT EXISTS makes the create phase
-- restartable, while schema versions are published only after verification.

SELECT DATABASE() AS migration_database;
SET @opscli_schema_name := DATABASE();

-- ---------------------------------------------------------------------------
-- 1. MCP quota schema v1
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mcp_quota_schema_versions (
    module_name VARCHAR(64) NOT NULL PRIMARY KEY,
    schema_version INT UNSIGNED NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS mcp_quota_policy (
    tool_name VARCHAR(128) NOT NULL PRIMARY KEY,
    service VARCHAR(64) NOT NULL,
    daily_limit BIGINT UNSIGNED NOT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    KEY ix_mcp_quota_policy_service (service, enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS mcp_quota_migrations (
    migration_id VARCHAR(191) NOT NULL PRIMARY KEY,
    applied_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS mcp_quota_daily (
    service VARCHAR(64) NOT NULL,
    quota_day DATE NOT NULL COMMENT 'Asia/Shanghai business day',
    identity_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    identity_type VARCHAR(32) NOT NULL,
    identity_key VARCHAR(254) NOT NULL DEFAULT '',
    calls BIGINT UNSIGNED NOT NULL DEFAULT 0,
    failures BIGINT UNSIGNED NOT NULL DEFAULT 0,
    limit_count BIGINT UNSIGNED NOT NULL,
    reset_at DATETIME(6) NOT NULL COMMENT 'UTC instant for the next reset',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (service, quota_day, identity_hash),
    KEY ix_mcp_quota_daily_identity (identity_type, identity_key, quota_day),
    KEY ix_mcp_quota_daily_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS mcp_quota_bonus_daily (
    service VARCHAR(64) NOT NULL,
    email VARCHAR(254) NOT NULL,
    bonus_daily_limit BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (service, email),
    KEY ix_mcp_quota_bonus_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET @mcp_quota_schema_ready := (
    SELECT COUNT(*) = 4
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = @opscli_schema_name
      AND TABLE_NAME IN (
          'mcp_quota_policy',
          'mcp_quota_migrations',
          'mcp_quota_daily',
          'mcp_quota_bonus_daily'
      )
);

INSERT INTO mcp_quota_schema_versions (module_name, schema_version)
SELECT 'mcp_quota', 1
WHERE @mcp_quota_schema_ready = 1
ON DUPLICATE KEY UPDATE schema_version = GREATEST(schema_version, 1);

-- ---------------------------------------------------------------------------
-- 2. SellerSprite task queue schema v1
-- PRE-CREATE ONLY. Do not switch workers until lease/CAS code and migration
-- tooling have passed multi-worker tests and a production drain window exists.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS seller_sprite_queue_schema_versions (
    module_name VARCHAR(64) NOT NULL PRIMARY KEY,
    schema_version INT UNSIGNED NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS seller_sprite_task_queue (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(191) NOT NULL,
    queue_scope VARCHAR(128) NOT NULL,
    task_kind VARCHAR(32) NOT NULL DEFAULT 'generic',
    status VARCHAR(32) NOT NULL,
    request_json JSON NOT NULL,
    root_dir TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    started_at DATETIME(6) NULL,
    finished_at DATETIME(6) NULL,
    assigned_account VARCHAR(128) NULL,
    assigned_account_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    worker_key VARCHAR(191) NULL,
    assignment_generation INT UNSIGNED NOT NULL DEFAULT 0,
    failover_count INT UNSIGNED NOT NULL DEFAULT 0,
    last_error_code VARCHAR(128) NULL,
    last_failed_account_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    retry_reason VARCHAR(500) NULL,
    result_path TEXT NULL,
    row_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
    export_json JSON NULL,
    error_json JSON NULL,
    credential_scope VARCHAR(64) NULL,
    runtime_auth_required TINYINT(1) NOT NULL DEFAULT 0,
    expected_user_email VARCHAR(254) NULL,
    account_route VARCHAR(32) NOT NULL DEFAULT 'shared_pool',
    requested_account_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    requested_account_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    auth_context_ref VARCHAR(191) NULL,
    auth_context_ciphertext VARBINARY(8192) NULL,
    auth_crypto_version VARCHAR(64) NULL,
    auth_key_id VARCHAR(191) NULL,
    execution_owner VARCHAR(191) NULL,
    heartbeat_at DATETIME(6) NULL,
    lease_expires_at DATETIME(6) NULL,
    lease_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    remote_task_id VARCHAR(191) NULL,
    progress_stage VARCHAR(64) NOT NULL DEFAULT 'queued',
    progress_at DATETIME(6) NULL,
    progress_sequence BIGINT UNSIGNED NOT NULL DEFAULT 0,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    running_account_guard VARCHAR(200)
        COLLATE utf8mb4_0900_bin
        GENERATED ALWAYS AS (
            CASE
                WHEN status = 'running' AND assigned_account_key IS NOT NULL
                THEN CONCAT(queue_scope, ':', assigned_account_key)
                ELSE NULL
            END
        ) STORED,
    UNIQUE KEY uq_seller_sprite_task_job_id (job_id),
    UNIQUE KEY uq_seller_sprite_running_account (running_account_guard),
    KEY ix_seller_sprite_task_claim (
        queue_scope, task_kind, account_route, status, id
    ),
    KEY ix_seller_sprite_task_owner_lease (
        status, execution_owner, lease_expires_at
    ),
    KEY ix_seller_sprite_task_remote (remote_task_id),
    KEY ix_seller_sprite_task_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS seller_sprite_collection_success_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(191) NOT NULL,
    succeeded_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_seller_sprite_success_task
        FOREIGN KEY (job_id) REFERENCES seller_sprite_task_queue(job_id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_seller_sprite_success_job (job_id),
    KEY ix_seller_sprite_success_cursor (succeeded_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS seller_sprite_mcp_runs (
    job_id VARCHAR(191) NOT NULL PRIMARY KEY,
    user_email VARCHAR(254) NOT NULL,
    scenario VARCHAR(128) NOT NULL,
    mode VARCHAR(32) NOT NULL,
    params_json JSON NOT NULL,
    result_state VARCHAR(32) NOT NULL,
    result_row_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
    result_export_format VARCHAR(32) NULL,
    result_export_filename VARCHAR(255) NULL,
    result_export_job_id VARCHAR(191) NULL,
    error_json JSON NULL,
    created_at DATETIME(6) NOT NULL,
    started_at DATETIME(6) NULL,
    finished_at DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_seller_sprite_mcp_run_task
        FOREIGN KEY (job_id) REFERENCES seller_sprite_task_queue(job_id)
        ON DELETE CASCADE,
    KEY ix_seller_sprite_mcp_user_time (user_email, created_at),
    KEY ix_seller_sprite_mcp_state_time (result_state, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS seller_sprite_account_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    created_at DATETIME(6) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    account_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    account_name VARCHAR(128) NULL,
    masked_username VARCHAR(254) NULL,
    job_id VARCHAR(191) NULL,
    worker_key VARCHAR(191) NULL,
    assignment_generation INT UNSIGNED NULL,
    execution_mode VARCHAR(64) NULL,
    login_stage VARCHAR(64) NULL,
    error_code VARCHAR(128) NULL,
    error_summary VARCHAR(1000) NULL,
    replacement_account_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    duration_ms BIGINT UNSIGNED NULL,
    failover_count INT UNSIGNED NULL,
    next_action VARCHAR(128) NULL,
    metadata_json JSON NOT NULL,
    KEY ix_seller_sprite_account_events_created (created_at),
    KEY ix_seller_sprite_account_events_job (job_id, created_at),
    KEY ix_seller_sprite_account_events_account (account_key, created_at),
    KEY ix_seller_sprite_account_events_type (event_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS seller_sprite_account_quarantine (
    account_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    credential_version CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    reason VARCHAR(500) NOT NULL,
    first_failed_at DATETIME(6) NOT NULL,
    last_failed_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    failure_count INT UNSIGNED NOT NULL DEFAULT 1,
    last_error_code VARCHAR(128) NOT NULL,
    PRIMARY KEY (account_key, credential_version),
    KEY ix_seller_sprite_quarantine_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS seller_sprite_task_progress_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(191) NOT NULL,
    progress_stage VARCHAR(64) NOT NULL,
    progress_at DATETIME(6) NOT NULL,
    progress_sequence BIGINT UNSIGNED NOT NULL,
    assignment_generation INT UNSIGNED NOT NULL,
    metadata_json JSON NOT NULL,
    CONSTRAINT fk_seller_sprite_progress_task
        FOREIGN KEY (job_id) REFERENCES seller_sprite_task_queue(job_id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_seller_sprite_progress_generation_sequence (
        job_id, assignment_generation, progress_sequence
    ),
    KEY ix_seller_sprite_progress_job_sequence (job_id, progress_sequence),
    KEY ix_seller_sprite_progress_time (progress_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS seller_sprite_runtime_heartbeats (
    execution_owner VARCHAR(191) NOT NULL PRIMARY KEY,
    lifecycle_state VARCHAR(32) NOT NULL,
    heartbeat_at DATETIME(6) NOT NULL,
    generic_workers_alive INT UNSIGNED NOT NULL DEFAULT 0,
    listing_worker_alive INT UNSIGNED NOT NULL DEFAULT 0,
    generic_available_capacity INT UNSIGNED NOT NULL DEFAULT 0,
    listing_available_capacity INT UNSIGNED NOT NULL DEFAULT 0,
    available_capacity INT UNSIGNED NOT NULL DEFAULT 0,
    standby_capacity INT UNSIGNED NOT NULL DEFAULT 0,
    last_claim_at DATETIME(6) NULL,
    last_progress_at DATETIME(6) NULL,
    KEY ix_seller_sprite_runtime_heartbeat (heartbeat_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET @seller_sprite_queue_schema_ready := (
    SELECT COUNT(*) = 7
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = @opscli_schema_name
      AND TABLE_NAME IN (
          'seller_sprite_task_queue',
          'seller_sprite_collection_success_events',
          'seller_sprite_mcp_runs',
          'seller_sprite_account_events',
          'seller_sprite_account_quarantine',
          'seller_sprite_task_progress_events',
          'seller_sprite_runtime_heartbeats'
      )
);

INSERT INTO seller_sprite_queue_schema_versions (module_name, schema_version)
SELECT 'seller_sprite_queue', 1
WHERE @seller_sprite_queue_schema_ready = 1
ON DUPLICATE KEY UPDATE schema_version = GREATEST(schema_version, 1);

-- ---------------------------------------------------------------------------
-- Verification
-- Both readiness values must be 1. Queue readiness only means that
-- empty tables exist; it does not authorize queue data migration or cutover.
-- ---------------------------------------------------------------------------

SELECT
    @mcp_quota_schema_ready AS mcp_quota_migration_ready,
    @seller_sprite_queue_schema_ready AS queue_schema_precreated;

SELECT module_name, schema_version, updated_at
FROM mcp_quota_schema_versions
WHERE module_name = 'mcp_quota';

SELECT module_name, schema_version, updated_at
FROM seller_sprite_queue_schema_versions
WHERE module_name = 'seller_sprite_queue';

SELECT TABLE_NAME, TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = @opscli_schema_name
  AND TABLE_NAME IN (
      'mcp_quota_policy',
      'mcp_quota_migrations',
      'mcp_quota_daily',
      'mcp_quota_bonus_daily',
      'seller_sprite_task_queue',
      'seller_sprite_collection_success_events',
      'seller_sprite_mcp_runs',
      'seller_sprite_account_events',
      'seller_sprite_account_quarantine',
      'seller_sprite_task_progress_events',
      'seller_sprite_runtime_heartbeats'
  )
ORDER BY TABLE_NAME;
