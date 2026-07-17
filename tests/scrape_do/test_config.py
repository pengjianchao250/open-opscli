from pathlib import Path

from opscli.scrape_do.config import ENV_TOKEN_FILE, load_settings


def test_load_settings_reads_token_from_local_file(monkeypatch, tmp_path: Path):
    token_file = tmp_path / "scrape_do_token.txt"
    token_file.write_text(" local-token \n", encoding="utf-8")

    monkeypatch.delenv("OPSCLI_SCRAPEDO_TOKEN", raising=False)
    monkeypatch.setenv(ENV_TOKEN_FILE, str(token_file))
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.token == "local-token"
    assert settings.to_public_dict()["has_token"] is True
    assert "local-token" not in str(settings.to_public_dict())


def test_env_token_overrides_local_token_file(monkeypatch, tmp_path: Path):
    token_file = tmp_path / "scrape_do_token.txt"
    token_file.write_text("file-token", encoding="utf-8")

    monkeypatch.setenv("OPSCLI_SCRAPEDO_TOKEN", "env-token")
    monkeypatch.setenv(ENV_TOKEN_FILE, str(token_file))
    monkeypatch.chdir(tmp_path)

    assert load_settings().token == "env-token"
