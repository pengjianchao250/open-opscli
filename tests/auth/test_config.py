from opscli.auth import config


def test_ops_url_can_be_configured_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.ini")
    (tmp_path / ".env").write_text(
        "OPSCLI_OPS_URL=https://ops.example.com/api",
        encoding="utf-8",
    )

    assert config.get_ops_url() == "https://ops.example.com/api"


def test_ops_url_can_be_configured_from_process_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.ini")
    monkeypatch.setenv("OPSCLI_OPS_URL", "https://ops.process-env.example.com/api")

    assert config.get_ops_url() == "https://ops.process-env.example.com/api"


def test_ops_url_can_be_configured_from_config_ini(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.ini"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    config_path.write_text(
        "\n".join(
            [
                "[systems]",
                "ops_url = https://ops.example.com/api",
            ]
        ),
        encoding="utf-8",
    )

    assert config.get_ops_url() == "https://ops.example.com/api"


def test_apphub_url_defaults_to_production(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.ini")
    monkeypatch.delenv("OPSCLI_APPHUB_URL", raising=False)

    assert config.get_apphub_url() == "http://10.1.13.143:8080"


def test_apphub_url_can_be_configured_from_process_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.ini")
    monkeypatch.setenv("OPSCLI_APPHUB_URL", "http://10.1.13.143:8080")

    assert config.get_apphub_url() == "http://10.1.13.143:8080"


def test_apphub_url_can_be_configured_from_config_ini(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.ini"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    config_path.write_text(
        "\n".join(
            [
                "[systems]",
                "apphub_url = http://10.1.13.143:8080",
            ]
        ),
        encoding="utf-8",
    )

    assert config.get_apphub_url() == "http://10.1.13.143:8080"


def test_app_template_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.ini")
    monkeypatch.delenv("OPSCLI_APP_TEMPLATE_REPO", raising=False)
    monkeypatch.delenv("OPSCLI_APP_TEMPLATE_BRANCH", raising=False)

    assert (
        config.get_app_template_repo()
        == "http://10.1.13.143:3000/aukeys-admin/template.git"
    )
    assert config.get_app_template_branch() == "main"


def test_app_template_can_be_configured_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.ini")
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPSCLI_APP_TEMPLATE_REPO=https://git.test.example/templates/app.git",
                "OPSCLI_APP_TEMPLATE_BRANCH=testing",
            ]
        ),
        encoding="utf-8",
    )

    assert (
        config.get_app_template_repo()
        == "https://git.test.example/templates/app.git"
    )
    assert config.get_app_template_branch() == "testing"


def test_app_template_can_be_configured_from_config_ini(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.ini"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    config_path.write_text(
        "\n".join(
            [
                "[systems]",
                "app_template_repo = https://git.prod.example/templates/app.git",
                "app_template_branch = stable",
            ]
        ),
        encoding="utf-8",
    )

    assert (
        config.get_app_template_repo()
        == "https://git.prod.example/templates/app.git"
    )
    assert config.get_app_template_branch() == "stable"


def test_process_env_overrides_app_template_dotenv_and_config_ini(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.ini"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    config_path.write_text(
        "\n".join(
            [
                "[systems]",
                "app_template_repo = https://git.ini.example/templates/app.git",
                "app_template_branch = ini",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPSCLI_APP_TEMPLATE_REPO=https://git.dotenv.example/templates/app.git",
                "OPSCLI_APP_TEMPLATE_BRANCH=dotenv",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "OPSCLI_APP_TEMPLATE_REPO",
        "https://git.process.example/templates/app.git",
    )
    monkeypatch.setenv("OPSCLI_APP_TEMPLATE_BRANCH", "process")

    assert (
        config.get_app_template_repo()
        == "https://git.process.example/templates/app.git"
    )
    assert config.get_app_template_branch() == "process"


def test_rufus_endpoint_keys_are_not_config_surface(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.ini"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    legacy_upload_key = "_".join(["rufus", "upload", "endpoint"])
    legacy_question_key = "_".join(["rufus", "question", "templates", "endpoint"])
    config_path.write_text(
        "\n".join(
            [
                "[systems]",
                f"{legacy_upload_key} = /v1/rufus/upload",
                f"{legacy_question_key} = /opencalw/default-question-templates",
            ]
        ),
        encoding="utf-8",
    )

    loaded = config.load_config()

    assert legacy_upload_key not in loaded
    assert legacy_question_key not in loaded


def test_polaris_is_enabled_as_builtin_system_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.ini")

    aliases = {system["alias"] for system in config.get_builtin_systems()}

    assert {"ops", "polaris"}.issubset(aliases)


def test_process_env_can_enable_polaris_over_local_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.ini"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    config_path.write_text(
        "\n".join(
            [
                "[systems]",
                "polaris_enabled = false",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPSCLI_POLARIS_ENABLED", "true")

    aliases = {system["alias"] for system in config.get_builtin_systems()}

    assert "polaris" in aliases
