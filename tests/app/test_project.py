"""AppHub 项目识别与 manifest 契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppManifestError, AppRuntimeUnsupportedError
from opscli.app.services.project import ProjectLoader


def _write_manifest(root: Path, extra: str = "") -> None:
    root.joinpath("app.yaml").write_text(
        "\n".join([
            "apiVersion: apps.aukeys/v1",
            "name: demo-app",
            "runtime: streamlit",
            "entrypoint: app.py",
            extra,
        ]),
        encoding="utf-8",
    )


def test_load_valid_manifest(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "opscli:\n  datasets: [ds_abcdef]")

    project = ProjectLoader().load(tmp_path)

    assert project.slug == "demo-app"
    assert project.manifest.runtime == "streamlit"


def test_codex_node_site_is_rejected_before_git(tmp_path: Path) -> None:
    tmp_path.joinpath("package.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AppRuntimeUnsupportedError) as caught:
        ProjectLoader().load(tmp_path)

    assert caught.value.code == "APP-RUNTIME-UNSUPPORTED"
    assert "Node/static" in caught.value.message


def test_static_runtime_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "")
    content = tmp_path.joinpath("app.yaml").read_text(encoding="utf-8")
    tmp_path.joinpath("app.yaml").write_text(content.replace("streamlit", "static"), encoding="utf-8")

    with pytest.raises(AppRuntimeUnsupportedError) as caught:
        ProjectLoader().load(tmp_path)

    assert caught.value.code == "APP-RUNTIME-UNSUPPORTED"


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "unexpected: true")

    with pytest.raises(AppManifestError) as caught:
        ProjectLoader().load(tmp_path)

    assert caught.value.code == "YAML-INVALID"
    assert "unexpected" in caught.value.message


def test_reserved_slug_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "")
    content = tmp_path.joinpath("app.yaml").read_text(encoding="utf-8")
    tmp_path.joinpath("app.yaml").write_text(content.replace("demo-app", "admin"), encoding="utf-8")

    with pytest.raises(AppManifestError) as caught:
        ProjectLoader().load(tmp_path)

    assert caught.value.code == "SLUG-RESERVED"

