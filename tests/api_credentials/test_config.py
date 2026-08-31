"""API 凭据池部署配置测试。"""

import pytest

from opscli.api_credentials.config import load_settings
from opscli.api_credentials.exceptions import ApiCredentialConfigError


def test_load_settings_requires_mysql():
    settings = load_settings({})

    assert settings.to_public_dict() == {"mysql_configured": False}
    with pytest.raises(ApiCredentialConfigError, match="MySQL"):
        settings.validate_mysql()
    with pytest.raises(ApiCredentialConfigError, match="MySQL"):
        settings.validate()

    mysql_only = load_settings(
        {
            "OPSCLI_API_CREDENTIAL_MYSQL_HOST": "mysql.internal",
            "OPSCLI_API_CREDENTIAL_MYSQL_DATABASE": "ops",
            "OPSCLI_API_CREDENTIAL_MYSQL_USER": "migration",
            "OPSCLI_API_CREDENTIAL_MYSQL_PASSWORD": "database-password",
        }
    )
    mysql_only.validate_mysql()
    mysql_only.validate()


def test_load_settings_does_not_expose_connection_password():
    settings = load_settings(
        {
            "OPSCLI_API_CREDENTIAL_MYSQL_HOST": "mysql.internal",
            "OPSCLI_API_CREDENTIAL_MYSQL_DATABASE": "ops",
            "OPSCLI_API_CREDENTIAL_MYSQL_USER": "credential_runtime",
            "OPSCLI_API_CREDENTIAL_MYSQL_PASSWORD": "mysql-secret",
        }
    )

    settings.validate()
    public = str(settings.to_public_dict())
    assert "mysql.internal" not in public
    assert "mysql-secret" not in public


def test_load_settings_falls_back_to_collection_mysql_configuration():
    settings = load_settings(
        {
            "OPSCLI_COLLECTION_MYSQL_HOST": "mysql.internal",
            "OPSCLI_COLLECTION_MYSQL_PORT": "3307",
            "OPSCLI_COLLECTION_MYSQL_DATABASE": "ops",
            "OPSCLI_COLLECTION_MYSQL_USER": "credential_runtime",
            "OPSCLI_COLLECTION_MYSQL_PASSWORD": "mysql-secret",
            "OPSCLI_COLLECTION_MYSQL_SSL_CA": "/etc/mysql/ca.pem",
            "OPSCLI_COLLECTION_MYSQL_CONNECT_TIMEOUT_SECONDS": "15",
        }
    )

    assert settings.mysql.host == "mysql.internal"
    assert settings.mysql.port == 3307
    assert settings.mysql.database == "ops"
    assert settings.mysql.user == "credential_runtime"
    assert settings.mysql.password == "mysql-secret"
    assert settings.mysql.ssl_ca == "/etc/mysql/ca.pem"
    assert settings.mysql.connect_timeout_seconds == 15
    settings.validate()


def test_load_settings_prefers_api_credential_configuration():
    settings = load_settings(
        {
            "OPSCLI_COLLECTION_MYSQL_HOST": "shared.mysql.internal",
            "OPSCLI_COLLECTION_MYSQL_DATABASE": "shared",
            "OPSCLI_COLLECTION_MYSQL_USER": "shared-user",
            "OPSCLI_COLLECTION_MYSQL_PASSWORD": "shared-secret",
            "OPSCLI_API_CREDENTIAL_MYSQL_HOST": "dedicated.mysql.internal",
            "OPSCLI_API_CREDENTIAL_MYSQL_DATABASE": "dedicated",
            "OPSCLI_API_CREDENTIAL_MYSQL_USER": "dedicated-user",
            "OPSCLI_API_CREDENTIAL_MYSQL_PASSWORD": "dedicated-secret",
        }
    )

    assert settings.mysql.host == "dedicated.mysql.internal"
    assert settings.mysql.database == "dedicated"
    assert settings.mysql.user == "dedicated-user"
    assert settings.mysql.password == "dedicated-secret"
