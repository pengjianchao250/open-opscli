"""应用 binding v3 与旧版本迁移测试。"""

import json
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding
from opscli.app.services.binding import BindingStore


def _binding(app_id: str = "Ab123") -> SiteBinding:
    return SiteBinding(
        app_id=app_id,
        app_name="销售看板",
        slug="sales-dashboard",
        repo_url="https://gitea.example/apps/sales-dashboard.git",
        git_username="owner",
    )


def test_binding_v3_round_trip_and_source_detection(tmp_path: Path) -> None:
    store = BindingStore()
    target = store.save(tmp_path, _binding())

    assert target == tmp_path / ".opscli" / "app.json"
    assert store.load(tmp_path) == _binding()
    assert store.has_source_files(tmp_path) is False
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert payload["app_name"] == "销售看板"
    assert "site_name" not in payload
    assert "template_repo_url" not in payload
    assert "template_branch" not in payload
    assert "token" not in target.read_text(encoding="utf-8").lower()
    assert payload["default_branch"] == "master"

    (tmp_path / "index.html").write_text("app", encoding="utf-8")
    assert store.has_source_files(tmp_path) is True


def test_binding_reads_remote_default_branch() -> None:
    binding = SiteBinding.from_app_detail(
        "销售看板",
        {
            "app_id": "Ab123",
            "slug": "sales-dashboard",
            "title": "销售看板",
            "repo_url": "https://gitea.example/apps/sales-dashboard.git",
            "default_branch": "master",
        },
    )

    assert binding.default_branch == "master"


@pytest.mark.parametrize("schema_version", [1, 2])
def test_binding_loads_legacy_schema_and_saves_as_v3(
    tmp_path: Path,
    schema_version: int,
) -> None:
    target = tmp_path / ".opscli" / "app.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "app_id": "Ab123",
                "site_name": "销售看板",
                "slug": "sales-dashboard",
                "repo_url": "https://gitea.example/legacy/apphub.git",
                "template_repo_url": "https://git.example/template.git",
                "template_branch": "template",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = BindingStore()

    legacy = store.load(tmp_path)
    assert legacy.schema_version == schema_version
    assert legacy.app_name == "销售看板"
    assert legacy.site_name == "销售看板"

    store.save(
        tmp_path,
        legacy.migrated(repo_url="https://gitea.example/apps/sales-dashboard.git"),
    )
    migrated = json.loads(target.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 3
    assert migrated["app_name"] == "销售看板"
    assert "site_id" not in migrated
    assert "site_name" not in migrated
    assert "template_repo_url" not in migrated


def test_binding_refuses_different_app(tmp_path: Path) -> None:
    store = BindingStore()
    store.save(tmp_path, _binding())

    with pytest.raises(AppProjectError) as caught:
        store.save(tmp_path, _binding("Xy789"))

    assert caught.value.code == "APP-ALREADY-BOUND"


@pytest.mark.parametrize("field", ["app_name", "slug", "repo_url"])
def test_binding_rejects_empty_required_fields(tmp_path: Path, field: str) -> None:
    payload = _binding().to_dict()
    payload[field] = None
    target = tmp_path / ".opscli" / "app.json"
    target.parent.mkdir()
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AppProjectError) as caught:
        BindingStore().load(tmp_path)

    assert caught.value.code == "APP-BINDING-INVALID"


@pytest.mark.parametrize("app_id", [None, "", "sales-dashboard", "Ab1234", " Ab123", 12345])
def test_remote_response_requires_public_id_without_fallback(app_id) -> None:
    """数字 ID、site_id、slug 都不能代替公开 app_id。"""
    payload = _binding().to_dict()
    payload.update(app_id=app_id, id="Ab123", site_id="Ab123", slug="sales")
    with pytest.raises(AppProjectError) as caught:
        SiteBinding.from_create_response("销售看板", payload)
    assert caught.value.code == "APPHUB-PROTOCOL"


def test_legacy_schema_cannot_replace_id_just_because_slug_matches(tmp_path: Path) -> None:
    """升级旧版本绑定也不能利用同名条件替换合法 ID。"""
    target = BindingStore().save(tmp_path, _binding())
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AppProjectError) as caught:
        BindingStore().save(tmp_path, _binding("Xy789"))
    assert caught.value.code == "APP-ALREADY-BOUND"
