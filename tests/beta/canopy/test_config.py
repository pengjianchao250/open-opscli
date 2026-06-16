from opscli.beta.canopy import config as canopy_config


def test_load_local_api_key_reads_trimmed_project_file(monkeypatch, tmp_path):
    """本地 Canopy key 只从文件读取，读取时自动去除首尾空白。"""
    key_path = tmp_path / "canopy" / "api_key"
    monkeypatch.setattr(canopy_config, "DEFAULT_API_KEY_PATH", key_path)

    key_path.parent.mkdir(parents=True)
    key_path.write_text("  local-canopy-key  ", encoding="utf-8")

    assert canopy_config.load_local_api_key() == "local-canopy-key"

def test_load_local_api_key_returns_none_when_missing_or_blank(monkeypatch, tmp_path):
    """缺失或空白文件都不应提供有效凭据。"""
    monkeypatch.setattr(canopy_config, "DEFAULT_API_KEY_PATH", tmp_path / "api_key")

    assert canopy_config.load_local_api_key() is None

    (tmp_path / "api_key").write_text("  ", encoding="utf-8")

    assert canopy_config.load_local_api_key() is None
