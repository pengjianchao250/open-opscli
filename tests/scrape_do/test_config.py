"""Scrape.do 非敏感运行配置测试。"""

from opscli.scrape_do.config import load_settings


def test_load_settings_does_not_read_api_key_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPSCLI_SCRAPEDO_TOKEN", "legacy-env-token")
    monkeypatch.setenv("OPSCLI_SCRAPEDO_TOKEN_FILE", str(tmp_path / "token.txt"))
    (tmp_path / "token.txt").write_text("legacy-file-token", encoding="utf-8")

    settings = load_settings()

    public = settings.to_public_dict()
    assert "token" not in public
    assert "legacy-env-token" not in str(settings)
    assert "legacy-file-token" not in str(settings)


def test_load_settings_keeps_non_secret_runtime_options(monkeypatch, tmp_path):
    monkeypatch.setenv("OPSCLI_SCRAPEDO_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("OPSCLI_SCRAPEDO_TIMEOUT_SECONDS", "12")

    settings = load_settings()

    assert settings.output_dir == tmp_path
    assert settings.timeout_seconds == 12
