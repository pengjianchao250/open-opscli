from pathlib import Path


SCHEMA_SQL = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "create_sqlite_runtime_mysql_tables_v1.sql"
)


def test_schema_creates_quota_tables_and_excludes_dedicated_bindings():
    sql = SCHEMA_SQL.read_text(encoding="utf-8")

    for table in (
        "mcp_quota_schema_versions",
        "mcp_quota_policy",
        "mcp_quota_migrations",
        "mcp_quota_daily",
        "mcp_quota_bonus_daily",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "PRIMARY KEY (service, quota_day, identity_hash)" in sql
    for table in (
        "seller_sprite_account_schema_versions",
        "seller_sprite_dedicated_accounts",
        "seller_sprite_user_account_bindings",
        "seller_sprite_account_binding_audit",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" not in sql


def test_schema_precreates_complete_queue_tables_with_mysql_lock_guards():
    sql = SCHEMA_SQL.read_text(encoding="utf-8")

    for table in (
        "seller_sprite_queue_schema_versions",
        "seller_sprite_task_queue",
        "seller_sprite_collection_success_events",
        "seller_sprite_mcp_runs",
        "seller_sprite_account_events",
        "seller_sprite_account_quarantine",
        "seller_sprite_task_progress_events",
        "seller_sprite_runtime_heartbeats",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "lease_token CHAR(36)" in sql
    assert "running_account_guard VARCHAR(200)" in sql
    assert "GENERATED ALWAYS AS" in sql
    assert "UNIQUE KEY uq_seller_sprite_running_account" in sql
    assert "UNIQUE KEY uq_seller_sprite_progress_generation_sequence" in sql
    assert "auth_context_ciphertext VARBINARY(8192)" in sql
    assert "session_id TEXT" not in sql
    assert "jwt TEXT" not in sql


def test_schema_uses_mysql_8_conventions_and_publishes_versions_last():
    sql = SCHEMA_SQL.read_text(encoding="utf-8")

    assert sql.count("ENGINE=InnoDB") == 13
    assert sql.count("COLLATE=utf8mb4_0900_ai_ci") == 13
    assert "DATETIME(6)" in sql
    assert "SELECT DATABASE() AS migration_database" in sql

    quota_version = sql.index(
        "INSERT INTO mcp_quota_schema_versions (module_name, schema_version)"
    )
    queue_version = sql.index(
        "INSERT INTO seller_sprite_queue_schema_versions "
        "(module_name, schema_version)"
    )

    assert sql.index("CREATE TABLE IF NOT EXISTS mcp_quota_bonus_daily") < quota_version
    assert (
        sql.index("CREATE TABLE IF NOT EXISTS seller_sprite_runtime_heartbeats")
        < queue_version
    )

    assert "WHERE @mcp_quota_schema_ready = 1" in sql[quota_version:]
    assert "WHERE @seller_sprite_queue_schema_ready = 1" in sql[queue_version:]
