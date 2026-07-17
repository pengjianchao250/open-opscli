import importlib
import importlib.metadata
import sys


def test_config_reads_pyproject_version_in_development_mode(monkeypatch):
    """开发模式下未安装包元数据时，可从 pyproject.toml 读取版本号。"""
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: (_ for _ in ()).throw(importlib.metadata.PackageNotFoundError(name)),
    )
    sys.modules.pop("opscli.config", None)

    try:
        config = importlib.import_module("opscli.config")
    finally:
        sys.modules.pop("opscli.config", None)

    assert config.__version__ == "0.0.108"
