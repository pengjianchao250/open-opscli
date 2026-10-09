from opscli.shared.runtime_mysql import load_runtime_mysql_settings


def test_runtime_mysql_settings_use_dedicated_values():
    settings = load_runtime_mysql_settings(
        {
            "OPSCLI_RUNTIME_MYSQL_HOST": "runtime.mysql.internal",
            "OPSCLI_RUNTIME_MYSQL_PORT": "3307",
            "OPSCLI_RUNTIME_MYSQL_DATABASE": "ops_runtime",
            "OPSCLI_RUNTIME_MYSQL_USER": "runtime_writer",
            "OPSCLI_RUNTIME_MYSQL_PASSWORD": "secret",
            "OPSCLI_RUNTIME_MYSQL_SSL_CA": "/etc/mysql/ca.pem",
            "OPSCLI_RUNTIME_MYSQL_CONNECT_TIMEOUT_SECONDS": "15",
        }
    )

    assert settings.host == "runtime.mysql.internal"
    assert settings.port == 3307
    assert settings.database == "ops_runtime"
    assert settings.user == "runtime_writer"
    assert settings.password == "secret"
    assert settings.ssl_ca == "/etc/mysql/ca.pem"
    assert settings.connect_timeout_seconds == 15


def test_runtime_mysql_settings_fall_back_to_collection_values():
    settings = load_runtime_mysql_settings(
        {
            "OPSCLI_COLLECTION_MYSQL_HOST": "shared.mysql.internal",
            "OPSCLI_COLLECTION_MYSQL_DATABASE": "polaris_ops_mcp",
            "OPSCLI_COLLECTION_MYSQL_USER": "shared_writer",
            "OPSCLI_COLLECTION_MYSQL_PASSWORD": "secret",
        }
    )

    assert settings.host == "shared.mysql.internal"
    assert settings.database == "polaris_ops_mcp"
    assert settings.user == "shared_writer"
    assert settings.configured is True
