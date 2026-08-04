"""Collector 采集结果 MySQL v1 表结构。"""

# v1 定义 Collector 通用任务、文件、Dataset 和逐行记录表。
SCHEMA_VERSION = 1

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
        )
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
        row_number BIGINT UNSIGNED NOT NULL,
        business_key VARCHAR(255) NULL,
        record_hash CHAR(64) NOT NULL,
        payload JSON NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        CONSTRAINT fk_collection_records_dataset
            FOREIGN KEY (dataset_id) REFERENCES collection_datasets(id)
            ON DELETE CASCADE,
        UNIQUE KEY uq_collection_record_row (dataset_id, row_number),
        KEY ix_collection_records_hash (record_hash),
        KEY ix_collection_records_business_key (business_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
)
