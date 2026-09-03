"""共享采集结果 MySQL 表结构。"""

# v3 增加手动维护的预取计划与独立执行队列，支持跨宿主租约领取。
SCHEMA_VERSION = 3

# 建表语句按外键依赖顺序执行，并固定匹配 MySQL 8 的 utf8mb4 排序规则。
SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS collection_schema_versions (
        module_name VARCHAR(64) NOT NULL PRIMARY KEY,
        schema_version INT UNSIGNED NOT NULL,
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_runs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        data_environment VARCHAR(16) NOT NULL,
        source_system VARCHAR(64) NOT NULL,
        source_job_id VARCHAR(191) NOT NULL,
        producer_service VARCHAR(64) NOT NULL,
        scenario VARCHAR(128) NOT NULL,
        site VARCHAR(32) NOT NULL,
        ingestion_mode VARCHAR(32) NOT NULL,
        collection_status VARCHAR(32) NOT NULL DEFAULT 'succeeded',
        request_params JSON NULL,
        request_fingerprint CHAR(64) NULL,
        cache_scope VARCHAR(128) NULL,
        parser_version VARCHAR(64) NOT NULL,
        source_row_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
        started_at DATETIME(6) NULL,
        completed_at DATETIME(6) NULL,
        persistence_completed_at DATETIME(6) NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),
        UNIQUE KEY uq_collection_run_source (
            data_environment, source_system, source_job_id
        ),
        KEY ix_collection_runs_scenario_time (
            source_system, scenario, completed_at
        ),
        KEY ix_collection_runs_cache_lookup (
            source_system, data_environment, scenario, site,
            request_fingerprint, cache_scope, persistence_completed_at
        )
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_call_events (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        trace_id CHAR(36) NOT NULL,
        event_type VARCHAR(32) NOT NULL DEFAULT 'mcp_tool',
        user_email VARCHAR(254) NULL,
        service VARCHAR(64) NOT NULL,
        operation VARCHAR(128) NOT NULL,
        endpoint VARCHAR(128) NULL,
        scenario VARCHAR(128) NULL,
        runtime_role VARCHAR(32) NOT NULL DEFAULT 'executor',
        site VARCHAR(64) NULL,
        period VARCHAR(64) NULL,
        provider VARCHAR(128) NULL,
        -- 兼容字段：公共调用统计不使用业务成功/失败状态。
        status VARCHAR(16) NOT NULL DEFAULT 'called',
        error_code VARCHAR(128) NULL,
        duration_ms INT UNSIGNED NULL,
        skill_name VARCHAR(128) NULL,
        dimensions_json JSON NULL,
        occurred_at DATETIME(6) NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        UNIQUE KEY uq_mcp_call_events_trace_id (trace_id),
        KEY ix_mcp_call_events_user_time (user_email, occurred_at),
        KEY ix_mcp_call_events_service_scenario_time (
            service, scenario, occurred_at
        ),
        KEY ix_mcp_call_events_service_endpoint_time (
            service, endpoint, occurred_at
        ),
        KEY ix_mcp_call_events_operation_time (operation, occurred_at),
        KEY ix_mcp_call_events_role_time (runtime_role, occurred_at),
        KEY ix_mcp_call_events_occurred_at (occurred_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_artifacts (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        run_id BIGINT UNSIGNED NOT NULL,
        artifact_type VARCHAR(32) NOT NULL,
        filename VARCHAR(255) NOT NULL,
        storage_uri TEXT NOT NULL,
        mime_type VARCHAR(191) NOT NULL,
        size_bytes BIGINT UNSIGNED NOT NULL,
        sha256 CHAR(64) NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        CONSTRAINT fk_collection_artifacts_run
            FOREIGN KEY (run_id) REFERENCES collection_runs(id) ON DELETE CASCADE,
        UNIQUE KEY uq_collection_artifact (run_id, artifact_type, sha256),
        KEY ix_collection_artifacts_sha256 (sha256)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_datasets (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        run_id BIGINT UNSIGNED NOT NULL,
        dataset_code VARCHAR(128) NOT NULL,
        dataset_name VARCHAR(255) NOT NULL,
        source_sheet VARCHAR(255) NOT NULL,
        columns_json JSON NOT NULL,
        row_count BIGINT UNSIGNED NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        CONSTRAINT fk_collection_datasets_run
            FOREIGN KEY (run_id) REFERENCES collection_runs(id) ON DELETE CASCADE,
        UNIQUE KEY uq_collection_dataset (run_id, dataset_code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_records (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        dataset_id BIGINT UNSIGNED NOT NULL,
        source_row_number BIGINT UNSIGNED NOT NULL,
        business_key VARCHAR(255) NULL,
        record_hash CHAR(64) NOT NULL,
        payload JSON NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        CONSTRAINT fk_collection_records_dataset
            FOREIGN KEY (dataset_id) REFERENCES collection_datasets(id)
            ON DELETE CASCADE,
        UNIQUE KEY uq_collection_record_row (dataset_id, source_row_number),
        KEY ix_collection_records_hash (record_hash),
        KEY ix_collection_records_business_key (business_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
)
