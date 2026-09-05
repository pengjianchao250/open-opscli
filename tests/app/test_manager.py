"""create、init、push 三命令业务编排测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding
from opscli.app.services.binding import BindingStore
from opscli.app.services.manager import AppManager


def _repo_url(slug: str) -> str:
    return f"https://gitea.example/apps/{slug}.git"


class FakeClient:
    def __init__(self) -> None:
        self.closed = False
        self.create_payloads: list[dict] = []
        self.issue_calls: list[bool] = []
        self.accessible_calls = 0
        self.apps = {
            "sales-dashboard": {
                "app_id": "app-1",
                "slug": "sales-dashboard",
                "title": "销售看板",
                "status": "active",
                "repo_url": _repo_url("sales-dashboard"),
                "current_version": "v2",
                "url": "https://apps.example/sales-dashboard",
            }
        }
        self.accessible_slugs = ["sales-dashboard"]

    def create_app(self, request_payload: dict) -> dict:
        self.create_payloads.append(request_payload)
        slug = request_payload["name"]
        detail = {
            "app_id": f"app-{len(self.apps) + 1}",
            "slug": slug,
            "title": request_payload["title"],
            "status": "registered",
            "repo_url": _repo_url(slug),
            "current_version": None,
            "url": None,
        }
        self.apps[slug] = detail
        if slug not in self.accessible_slugs:
            self.accessible_slugs.append(slug)
        return {
            **detail,
            "git_username": "owner",
            "git_credential": {
                "username": "owner",
                "token": "one-time-secret",
                "token_hint": "12345678",
            },
        }

    def list_accessible_apps(self) -> dict:
        self.accessible_calls += 1
        return {
            "apps": [
                {
                    "app_id": self.apps[slug]["app_id"],
                    "slug": slug,
                    "title": self.apps[slug]["title"],
                    "status": self.apps[slug]["status"],
                }
                for slug in self.accessible_slugs
            ]
        }

    def get_app(self, slug: str) -> dict:
        return dict(self.apps[slug])

    def get_git_config(self, slug: str) -> dict:
        return {
            "repo_url": _repo_url(slug),
            "username": "owner",
            "bound": True,
        }

    def issue_git_credential(self, *, rotate: bool) -> dict:
        self.issue_calls.append(rotate)
        return {"username": "owner", "token": "rotated-secret", "token_hint": "87654321"}

    def close(self) -> None:
        self.closed = True


class FakeCredentialStore:
    def __init__(self, *, exists: bool = False) -> None:
        self.exists = exists
        self.saved: list[dict] = []

    def has_credential(self, root, *, repo_url, username):
        return self.exists

    def save_credential(self, root, *, repo_url, username, token):
        self.saved.append(
            {"root": root, "repo_url": repo_url, "username": username, "token": token}
        )
        self.exists = True


class FakeGit:
    def __init__(self, *, pushed: bool = True) -> None:
        self.init_calls: list[tuple[Path, dict]] = []
        self.push_calls: list[tuple[Path, dict]] = []
        self.pushed = pushed

    def initialize(self, root, **kwargs):
        self.init_calls.append((root, kwargs))
        return {
            "git_created": len(self.init_calls) == 1,
            "remote_main_sha": "a" * 40,
        }

    def push_all(self, root, **kwargs):
        self.push_calls.append((root, kwargs))
        return {
            "commit_sha": "b" * 40,
            "remote_commit_sha": "b" * 40,
            "committed": self.pushed,
            "pushed": self.pushed,
        }

def _manager(
    client: FakeClient,
    git: FakeGit,
    credentials: FakeCredentialStore | None = None,
) -> AppManager:
    return AppManager(
        client=client,
        git_service=git,
        credential_store=credentials or FakeCredentialStore(exists=True),
    )


def _write_manifest(root: Path, *, name: str = "template-app", title: str = "示例应用") -> None:
    (root / "app.yaml").write_text(
        f"apiVersion: apps.aukeys/v1\nname: {name}\ntitle: {title}\nruntime: fastapi\n",
        encoding="utf-8",
    )


def test_create_only_creates_and_binds_application(tmp_path: Path) -> None:
    client = FakeClient()
    git = FakeGit()
    credentials = FakeCredentialStore()
    manager = _manager(client, git, credentials)
    _write_manifest(tmp_path)

    result = manager.create_app("新看板", path=tmp_path)

    assert len(client.create_payloads) == 1
    payload = client.create_payloads[0]
    assert payload["database"] == {"path": None}
    assert "runtime" not in payload
    assert git.init_calls == []
    assert git.push_calls == []
    assert credentials.saved[0]["token"] == "one-time-secret"
    binding_payload = json.loads(
        (tmp_path / ".opscli" / "app.json").read_text(encoding="utf-8")
    )
    assert binding_payload["schema_version"] == 3
    assert "template_repo_url" not in binding_payload
    assert result["app_name"] == "新看板"
    manifest = (tmp_path / "app.yaml").read_text(encoding="utf-8")
    assert f'name: "{result["slug"]}"' in manifest
    assert 'title: "新看板"' in manifest
    assert "runtime: fastapi" in manifest


def test_create_without_manifest_does_not_generate_one(tmp_path: Path) -> None:
    manager = _manager(FakeClient(), FakeGit(), FakeCredentialStore())

    manager.create_app("新应用", path=tmp_path)

    assert not (tmp_path / "app.yaml").exists()


def test_create_default_path_reuses_existing_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "sales-dashboard"
    BindingStore().save(
        root,
        SiteBinding(
            app_id="app-1",
            app_name="销售看板",
            slug="sales-dashboard",
            repo_url=_repo_url("sales-dashboard"),
        ),
    )
    _write_manifest(root)
    client = FakeClient()
    monkeypatch.chdir(tmp_path)

    result = _manager(client, FakeGit()).create_app("sales-dashboard")

    assert client.create_payloads == []
    assert result["app_id"] == "app-1"
    manifest = (root / "app.yaml").read_text(encoding="utf-8")
    assert 'name: "sales-dashboard"' in manifest
    assert 'title: "销售看板"' in manifest


def test_init_recovers_accessible_application_without_create(tmp_path: Path) -> None:
    app_root = tmp_path / "sales-dashboard"
    app_root.mkdir()
    client = FakeClient()
    git = FakeGit()

    result = _manager(client, git).init_git(app_root)

    assert client.accessible_calls == 1
    assert client.create_payloads == []
    assert result["slug"] == "sales-dashboard"
    assert git.init_calls[0][1] == {"repo_url": _repo_url("sales-dashboard")}
    assert BindingStore().load(app_root).schema_version == 3


def test_init_discovers_application_identity_from_app_yaml(tmp_path: Path) -> None:
    app_root = tmp_path / "local-worktree"
    app_root.mkdir()
    (app_root / "app.yaml").write_text(
        "name: sales-dashboard\ntitle: 销售看板\n",
        encoding="utf-8",
    )
    client = FakeClient()
    git = FakeGit()

    result = _manager(client, git).init_git(app_root)

    assert client.create_payloads == []
    assert result["slug"] == "sales-dashboard"
    assert result["app_name"] == "销售看板"


def test_init_creates_application_when_no_remote_match(tmp_path: Path) -> None:
    app_root = tmp_path / "inventory-dashboard"
    app_root.mkdir()
    client = FakeClient()
    client.accessible_slugs = []
    git = FakeGit()
    credentials = FakeCredentialStore()

    result = _manager(client, git, credentials).init_git(app_root)

    assert client.create_payloads[0]["name"] == "inventory-dashboard"
    assert result["slug"] == "inventory-dashboard"
    assert git.init_calls[0][1] == {"repo_url": _repo_url("inventory-dashboard")}


def test_init_migrates_legacy_binding_without_template_fields(tmp_path: Path) -> None:
    target = tmp_path / ".opscli" / "app.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "app_id": "app-1",
                "site_name": "销售看板",
                "slug": "sales-dashboard",
                "repo_url": "https://gitea.example/legacy/apphub.git",
                "template_repo_url": "https://git.example/template.git",
                "template_branch": "main",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _manager(FakeClient(), FakeGit()).init_git(tmp_path)

    migrated = json.loads(target.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 3
    assert migrated["repo_url"] == _repo_url("sales-dashboard")
    assert "template_repo_url" not in migrated
    assert "template_branch" not in migrated


def test_push_only_pushes_source_and_never_publishes(tmp_path: Path) -> None:
    BindingStore().save(
        tmp_path,
        SiteBinding(
            app_id="app-1",
            app_name="销售看板",
            slug="sales-dashboard",
            repo_url=_repo_url("sales-dashboard"),
            git_username="owner",
        ),
    )
    client = FakeClient()
    git = FakeGit()

    result = _manager(client, git).push(tmp_path, message="优化首页")

    assert git.push_calls[0][1]["message"] == "优化首页"
    assert "release_id" not in result
    assert "version" not in result
    assert result["message"] == "源码已推送到远端仓库。"
