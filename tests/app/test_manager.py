"""create/init/push 三命令业务编排测试。"""

from __future__ import annotations

import json
from pathlib import Path

from opscli.app.domain.models import SiteBinding
from opscli.app.services.binding import BindingStore
from opscli.app.services.manager import AppManager

REPO_URL = "https://gitea.example/apps/sales-dashboard.git"


class FakeClient:
    def __init__(self) -> None:
        self.closed = False
        self.create_payloads: list[dict] = []
        self.issue_calls: list[bool] = []
        self.publish_calls: list[dict] = []
        self.git_config = {
            "repo_url": REPO_URL,
            "username": "owner",
            "bound": True,
        }
        self.app_detail = {
            "app_id": "app-1",
            "slug": "sales-dashboard",
            "status": "active",
            "repo_url": REPO_URL,
            "current_version": "v2",
            "url": "https://apps.example/sales-dashboard",
        }
        self.releases = {
            "releases": [
                {"status": "healthy", "is_rollback": False, "commit_sha": "a" * 40}
            ]
        }

    def create_app(self, app_yaml: dict) -> dict:
        self.create_payloads.append(app_yaml)
        return {
            "app_id": "app-1",
            "site_name": app_yaml["title"],
            "slug": "sales-dashboard",
            "repo_url": REPO_URL,
            "git_username": "owner",
            "git_credential": {
                "username": "owner",
                "token": "one-time-secret",
                "token_hint": "12345678",
            },
        }

    def get_app(self, slug: str) -> dict:
        assert slug == "sales-dashboard"
        return dict(self.app_detail)

    def get_git_config(self, slug: str) -> dict:
        assert slug == "sales-dashboard"
        return dict(self.git_config)

    def issue_git_credential(self, *, rotate: bool) -> dict:
        self.issue_calls.append(rotate)
        return {"username": "owner", "token": "rotated-secret", "token_hint": "87654321"}

    def list_releases(self, slug: str, **kwargs) -> dict:
        assert slug == "sales-dashboard"
        assert kwargs == {"page": 1, "size": 1, "is_rollback": False}
        return self.releases

    def publish_release(
        self,
        slug: str,
        *,
        commit_sha: str,
        message: str,
        on_event=None,
    ) -> dict:
        self.publish_calls.append(
            {"slug": slug, "commit_sha": commit_sha, "message": message}
        )
        if on_event is not None:
            on_event({"seq": 6, "level": "info", "message": "healthy", "status": "healthy"})
        return {
            "release_id": 41,
            "last_seq": 6,
            "terminal_event": {"status": "healthy", "seq": 6},
        }

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
    def __init__(self) -> None:
        self.init_args = None
        self.push_args = None

    def initialize(self, root, **kwargs):
        self.init_args = (root, kwargs)
        return {
            "git_created": True,
            "template_applied": kwargs["apply_template"],
            "remote_main_sha": "a" * 40,
        }

    def push_all(self, root, **kwargs):
        self.push_args = (root, kwargs)
        return {
            "commit_sha": "b" * 40,
            "remote_commit_sha": "b" * 40,
            "committed": True,
            "pushed": True,
        }


def test_create_uses_apphub_repo_and_current_template_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "opscli.app.services.manager.get_app_template_repo",
        lambda: "https://git.current.example/templates/app.git",
    )
    monkeypatch.setattr(
        "opscli.app.services.manager.get_app_template_branch",
        lambda: "current",
    )
    client = FakeClient()
    credentials = FakeCredentialStore()
    manager = AppManager(
        client=client,
        git_service=FakeGit(),
        credential_store=credentials,
    )

    result = manager.create_site("sales-dashboard", path=tmp_path)

    assert result["app_id"] == "app-1"
    assert result["repo_url"] == REPO_URL
    assert client.create_payloads[0]["apiVersion"] == "apps.aukeys/v1"
    assert client.create_payloads[0]["entrypoint"] == "app.py"
    assert credentials.saved[0]["token"] == "one-time-secret"
    binding_text = (tmp_path / ".opscli" / "app.json").read_text(encoding="utf-8")
    assert "one-time-secret" not in binding_text
    binding_payload = json.loads(binding_text)
    assert binding_payload["schema_version"] == 2
    assert (
        binding_payload["template_repo_url"]
        == "https://git.current.example/templates/app.git"
    )
    assert binding_payload["template_branch"] == "current"


def test_init_migrates_v1_refreshes_repo_and_rotates_missing_credential(
    tmp_path: Path,
) -> None:
    binding_file = tmp_path / ".opscli" / "app.json"
    binding_file.parent.mkdir()
    binding_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "site_id": "legacy-site",
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
    (tmp_path / "index.html").write_text("keep", encoding="utf-8")
    client = FakeClient()
    git = FakeGit()
    credentials = FakeCredentialStore(exists=False)
    manager = AppManager(
        client=client,
        git_service=git,
        credential_store=credentials,
    )

    result = manager.init_git(tmp_path)

    assert client.issue_calls == [True]
    assert git.init_args[1]["repo_url"] == REPO_URL
    assert git.init_args[1]["apply_template"] is False
    assert result["credential_rotated"] is True
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "keep"
    migrated = BindingStore().load(tmp_path)
    assert migrated.schema_version == 2
    assert migrated.app_id == "app-1"
    assert migrated.repo_url == REPO_URL
    assert migrated.template_repo_url == "https://git.example/template.git"
    assert migrated.template_branch == "template"
    assert git.init_args[1]["template_repo_url"] == "https://git.example/template.git"
    assert git.init_args[1]["template_branch"] == "template"


def test_empty_project_init_uses_current_template_config(
    tmp_path: Path, monkeypatch
) -> None:
    BindingStore().save(
        tmp_path,
        SiteBinding(
            app_id="app-1",
            site_name="销售看板",
            slug="sales-dashboard",
            repo_url=REPO_URL,
            git_username="owner",
            template_repo_url="https://git.old.example/templates/app.git",
            template_branch="old",
        ),
    )
    monkeypatch.setattr(
        "opscli.app.services.manager.get_app_template_repo",
        lambda: "https://git.current.example/templates/app.git",
    )
    monkeypatch.setattr(
        "opscli.app.services.manager.get_app_template_branch",
        lambda: "current",
    )
    git = FakeGit()
    manager = AppManager(
        client=FakeClient(),
        git_service=git,
        credential_store=FakeCredentialStore(exists=True),
    )

    result = manager.init_git(tmp_path)

    assert git.init_args[1]["apply_template"] is True
    assert (
        git.init_args[1]["template_repo_url"]
        == "https://git.current.example/templates/app.git"
    )
    assert git.init_args[1]["template_branch"] == "current"
    assert result["template_applied"] is True
    binding = BindingStore().load(tmp_path)
    assert (
        binding.template_repo_url
        == "https://git.current.example/templates/app.git"
    )
    assert binding.template_branch == "current"


def test_push_publishes_remote_main_sha(tmp_path: Path) -> None:
    BindingStore().save(
        tmp_path,
        SiteBinding(
            app_id="app-1",
            site_name="销售看板",
            slug="sales-dashboard",
            repo_url=REPO_URL,
            git_username="owner",
        ),
    )
    client = FakeClient()
    git = FakeGit()
    manager = AppManager(
        client=client,
        git_service=git,
        credential_store=FakeCredentialStore(exists=True),
    )

    result = manager.push(tmp_path, message="优化首页筛选交互")

    assert git.push_args[1]["message"] == "优化首页筛选交互"
    assert client.publish_calls == [
        {
            "slug": "sales-dashboard",
            "commit_sha": "b" * 40,
            "message": "优化首页筛选交互",
        }
    ]
    assert result["release_id"] == 41
    assert result["version"] == "v2"
    assert result["status"] == "healthy"


def test_push_returns_git_004_noop_for_healthy_baseline(tmp_path: Path) -> None:
    BindingStore().save(
        tmp_path,
        SiteBinding(
            app_id="app-1",
            site_name="销售看板",
            slug="sales-dashboard",
            repo_url=REPO_URL,
            git_username="owner",
        ),
    )
    client = FakeClient()
    client.releases = {
        "baseline": {"commit_sha": "b" * 40},
        "releases": [],
    }
    manager = AppManager(
        client=client,
        git_service=FakeGit(),
        credential_store=FakeCredentialStore(exists=True),
    )

    result = manager.push(tmp_path, message="确认发布状态")

    assert result["status"] == "noop"
    assert result["error_code"] == "GIT-004"
    assert client.publish_calls == []


def test_create_reuses_same_local_binding_without_remote_call(tmp_path: Path) -> None:
    BindingStore().save(
        tmp_path,
        SiteBinding(
            app_id="app-1",
            site_name="sales-dashboard",
            slug="sales-dashboard",
            repo_url=REPO_URL,
        ),
    )
    client = FakeClient()
    manager = AppManager(
        client=client,
        git_service=FakeGit(),
        credential_store=FakeCredentialStore(exists=True),
    )

    result = manager.create_site("sales-dashboard", path=tmp_path)

    assert client.create_payloads == []
    assert result["app_id"] == "app-1"
