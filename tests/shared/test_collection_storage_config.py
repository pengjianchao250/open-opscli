"""共享采集数据沉淀配置测试。"""

from opscli.shared.collection_storage.config import load_storage_settings


def test_collection_storage_is_disabled_without_explicit_enablement(tmp_path):
    settings = load_storage_settings("collector", {}, config_dir=tmp_path)

    assert settings.enabled is False
    assert (
        settings.outbox_db_path
        == (tmp_path / "collection_storage" / "collector.sqlite3").resolve()
    )
    assert settings.to_public_dict() == {
        "enabled": False,
        "data_environment": None,
        "mysql_configured": False,
        "auto_create_schema": False,
        "batch_size": 500,
    }


def test_enabled_collection_storage_requires_and_loads_mysql_configuration(tmp_path):
    ssl_ca = tmp_path / "mysql-ca.pem"
    ssl_ca.write_text("test-ca", encoding="ascii")
    settings = load_storage_settings(
        "collector",
        {
            "OPSCLI_COLLECTION_STORAGE_ENABLED": "true",
            "OPSCLI_DATA_ENVIRONMENT": "production",
            "OPSCLI_COLLECTION_MYSQL_HOST": "mysql.internal",
            "OPSCLI_COLLECTION_MYSQL_PORT": "3307",
            "OPSCLI_COLLECTION_MYSQL_DATABASE": "polaris_ops_mcp",
            "OPSCLI_COLLECTION_MYSQL_USER": "collection_writer",
            "OPSCLI_COLLECTION_MYSQL_PASSWORD": "secret",
            "OPSCLI_COLLECTION_MYSQL_SSL_CA": str(ssl_ca),
            "OPSCLI_COLLECTION_STORAGE_AUTO_CREATE_SCHEMA": "true",
        },
        config_dir=tmp_path,
    )

    assert settings.enabled is True
    assert settings.data_environment == "production"
    assert settings.mysql.host == "mysql.internal"
    assert settings.mysql.port == 3307
    assert settings.mysql.password == "secret"
    assert settings.mysql.ssl_ca == str(ssl_ca)
    assert settings.to_public_dict()["mysql_configured"] is True
    assert "password" not in str(settings.to_public_dict()).lower()


def test_production_collection_storage_allows_optional_mysql_tls_ca(tmp_path):
    settings = load_storage_settings(
        "collector",
        {
            "OPSCLI_COLLECTION_STORAGE_ENABLED": "true",
            "OPSCLI_DATA_ENVIRONMENT": "production",
            "OPSCLI_COLLECTION_MYSQL_HOST": "mysql.internal",
            "OPSCLI_COLLECTION_MYSQL_DATABASE": "polaris_ops_mcp",
            "OPSCLI_COLLECTION_MYSQL_USER": "collection_writer",
            "OPSCLI_COLLECTION_MYSQL_PASSWORD": "secret",
        },
        config_dir=tmp_path,
    )

    assert settings.enabled is True
    assert settings.data_environment == "production"
    assert settings.mysql.ssl_ca == ""


def test_each_mcp_host_uses_an_independent_default_outbox(tmp_path):
    general = load_storage_settings("mcp", {}, config_dir=tmp_path)
    collector = load_storage_settings("collector", {}, config_dir=tmp_path)

    assert general.outbox_db_path.name == "mcp.sqlite3"
    assert collector.outbox_db_path.name == "collector.sqlite3"
    assert general.outbox_db_path != collector.outbox_db_path


def test_collector_runtime_accepts_legacy_environment_names(tmp_path):
    settings = load_storage_settings(
        "collector",
        {
            "OPSCLI_COLLECTOR_STORAGE_ENABLED": "true",
            "OPSCLI_DATA_ENVIRONMENT": "debug",
            "OPSCLI_COLLECTOR_MYSQL_HOST": "mysql.internal",
            "OPSCLI_COLLECTOR_MYSQL_DATABASE": "polaris_ops_mcp",
            "OPSCLI_COLLECTOR_MYSQL_USER": "collector_writer",
            "OPSCLI_COLLECTOR_MYSQL_PASSWORD": "secret",
        },
        config_dir=tmp_path,
    )

    assert settings.enabled is True
    assert settings.runtime_id == "collector"
    assert settings.mysql.user == "collector_writer"
