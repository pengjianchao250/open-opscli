from pathlib import Path


MIGRATION_SQL = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "migrate_collection_storage_v1_to_v3.sql"
)


def test_v1_to_v3_migration_contains_required_schema_changes():
    sql = MIGRATION_SQL.read_text(encoding="utf-8")

    assert "ADD COLUMN request_fingerprint CHAR(64) NULL" in sql
    assert "ADD COLUMN cache_scope VARCHAR(128) NULL" in sql
    assert "JSON_EXTRACT(request_params, '$._cache.cache_key')" in sql
    assert "JSON_EXTRACT(request_params, '$._cache.cache_scope')" in sql
    assert "CREATE INDEX ix_collection_runs_cache_lookup" in sql
    assert "CREATE TABLE IF NOT EXISTS collection_prefetch_schedules" in sql
    assert "CREATE TABLE IF NOT EXISTS collection_prefetch_runs" in sql
    assert "@collection_existing_schema_version <= 3" in sql
    assert "COLUMN_NAME ORDER BY SEQ_IN_INDEX" in sql


def test_v1_to_v3_migration_publishes_version_only_after_schema_changes():
    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    version_update = sql.index(
        "INSERT INTO collection_schema_versions (module_name, schema_version)"
    )

    for required_change in (
        "ADD COLUMN request_fingerprint",
        "ADD COLUMN cache_scope",
        "CREATE INDEX ix_collection_runs_cache_lookup",
        "CREATE TABLE IF NOT EXISTS collection_prefetch_schedules",
        "CREATE TABLE IF NOT EXISTS collection_prefetch_runs",
    ):
        assert sql.index(required_change) < version_update

    assert "WHERE @collection_schema_ready = 1" in sql[version_update:]
    assert "schema_version = GREATEST" in sql[version_update:]
    assert "SELECT @collection_schema_ready AS migration_ready" in sql
