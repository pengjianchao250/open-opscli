"""app.yaml 应用身份同步测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding
from opscli.app.services.manifest import AppManifestStore


def _binding() -> SiteBinding:
    return SiteBinding(
        app_id="app-1",
        app_name="销售看板",
        slug="sales-dashboard",
        repo_url="https://gitea.example/apps/sales-dashboard.git",
    )


def test_sync_identity_preserves_project_fields_and_comments(tmp_path: Path) -> None:
    target = tmp_path / "app.yaml"
    target.write_text(
        "# template identity\n"
        "apiVersion: apps.aukeys/v1\n"
        "name: sample-app\n"
        "title: 示例应用\n"
        "runtime: fastapi\n"
        "opscli:\n"
        "  auth_mode: viewer\n"
        "  datasets:\n"
        "    - sales_daily\n"
        "x-extension: keep-me\n",
        encoding="utf-8",
    )

    changed = AppManifestStore().sync_identity(tmp_path, _binding())

    assert changed is True
    content = target.read_text(encoding="utf-8")
    payload = yaml.safe_load(content)
    assert payload["name"] == "sales-dashboard"
    assert payload["title"] == "销售看板"
    assert payload["runtime"] == "fastapi"
    assert payload["opscli"]["datasets"] == ["sales_daily"]
    assert payload["x-extension"] == "keep-me"
    assert "# template identity" in content


def test_sync_identity_inserts_missing_identity_after_api_version(tmp_path: Path) -> None:
    target = tmp_path / "app.yaml"
    target.write_text(
        "apiVersion: apps.aukeys/v1\nruntime: fastapi\n",
        encoding="utf-8",
    )

    AppManifestStore().sync_identity(tmp_path, _binding())

    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[1] == 'name: "sales-dashboard"'
    assert lines[2] == 'title: "销售看板"'


def test_sync_identity_uses_app_id_schema_without_legacy_name(tmp_path: Path) -> None:
    target = tmp_path / "app.yaml"
    target.write_text(
        "apiVersion: apps.aukeys/v1\n"
        "name: stale-slug\n"
        "app_id: old-id\n"
        "title: 示例应用\n"
        "database:\n"
        "  kind: sqlite\n",
        encoding="utf-8",
    )

    changed = AppManifestStore().sync_identity(tmp_path, _binding())

    assert changed is True
    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert payload["app_id"] == "app-1"
    assert payload["title"] == "销售看板"
    assert "name" not in payload
    assert payload["database"] == {"kind": "sqlite"}


def test_required_manifest_must_exist(tmp_path: Path) -> None:
    with pytest.raises(AppProjectError) as caught:
        AppManifestStore().load(tmp_path, required=True)

    assert caught.value.code == "APP-MANIFEST-NOT-FOUND"


@pytest.mark.parametrize(
    "content",
    (
        "- not-a-mapping\n",
        "name: [broken\n",
        "name: first\nname: second\n",
        "name:\n  nested: value\n",
    ),
)
def test_invalid_manifest_is_rejected(tmp_path: Path, content: str) -> None:
    (tmp_path / "app.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(AppProjectError) as caught:
        AppManifestStore().load(tmp_path)

    assert caught.value.code == "APP-MANIFEST-INVALID"
