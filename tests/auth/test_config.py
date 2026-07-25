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
