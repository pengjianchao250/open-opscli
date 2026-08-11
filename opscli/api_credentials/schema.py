"""第三方 API 凭据池 MySQL v1 表结构。"""

# Schema 由显式管理命令创建，运行期连接不自动执行 DDL。
SCHEMA_VERSION = 1

# 建表顺序固定为版本、账号、密钥、运行状态、审计，以满足外键依赖。
SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS api_credential_schema_versions (
        module_name VARCHAR(64) NOT NULL PRIMARY KEY,
        schema_version INT UNSIGNED NOT NULL,
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS api_provider_accounts (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        provider VARCHAR(32) NOT NULL,
        account_name VARCHAR(128) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        priority INT UNSIGNED NOT NULL DEFAULT 100,
        remark VARCHAR(500) NULL,
        created_by VARCHAR(191) NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),
        UNIQUE KEY uq_api_provider_account (provider, account_name),
        KEY ix_api_provider_account_select (provider, status, priority, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS api_account_credentials (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        account_id BIGINT UNSIGNED NOT NULL,
        credential_type VARCHAR(32) NOT NULL DEFAULT 'api_key',
        secret_ciphertext LONGBLOB NOT NULL,
        secret_nonce BINARY(12) NOT NULL,
        encrypted_dek VARBINARY(64) NOT NULL,
        dek_nonce BINARY(12) NOT NULL,
        secret_masked VARCHAR(64) NOT NULL,
        secret_fingerprint CHAR(64) NOT NULL,
        secret_version INT UNSIGNED NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        activated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        expires_at DATETIME(6) NULL,
        revoked_at DATETIME(6) NULL,
        rotated_from_id BIGINT UNSIGNED NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        CONSTRAINT fk_api_credential_account
            FOREIGN KEY (account_id) REFERENCES api_provider_accounts(id) ON DELETE CASCADE,
        CONSTRAINT fk_api_credential_rotated_from
            FOREIGN KEY (rotated_from_id) REFERENCES api_account_credentials(id),
        UNIQUE KEY uq_api_account_credential_version (account_id, secret_version),
        KEY ix_api_account_credential_active (account_id, status),
        KEY ix_api_account_credential_fingerprint (secret_fingerprint)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS api_account_runtime (
        account_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
        remaining_quota BIGINT NULL,
        current_usage BIGINT NULL,
        quota_reset_at DATETIME(6) NULL,
        last_selected_at DATETIME(6) NULL,
        last_used_at DATETIME(6) NULL,
        last_verified_at DATETIME(6) NULL,
        cooldown_until DATETIME(6) NULL,
        consecutive_failures INT UNSIGNED NOT NULL DEFAULT 0,
        last_error_code VARCHAR(128) NULL,
        last_error_message VARCHAR(500) NULL,
        provider_metadata JSON NULL,
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),
        CONSTRAINT fk_api_runtime_account
            FOREIGN KEY (account_id) REFERENCES api_provider_accounts(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS api_credential_audit_logs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        account_id BIGINT UNSIGNED NOT NULL,
        action VARCHAR(64) NOT NULL,
        actor VARCHAR(191) NULL,
        detail JSON NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        CONSTRAINT fk_api_audit_account
            FOREIGN KEY (account_id) REFERENCES api_provider_accounts(id) ON DELETE CASCADE,
        KEY ix_api_audit_account_time (account_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
)
