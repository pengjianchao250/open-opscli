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
