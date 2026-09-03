"""三命令业务编排测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding
from opscli.app.services.binding import BindingStore
from opscli.app.services.manager import AppManager

TARGET_REPO_URL = "http://10.1.13.143:3000/aukeys-admin/apphub.git"


class FakeClient:
    def __init__(self) -> None:
        self.closed = False
        self.create_calls = 0

    def create_site(self, site_name: str) -> dict:
        self.create_calls += 1
        return {
            "site_id": "site-1",
            "site_name": site_name,
            "slug": "sales-dashboard",
            "created_by": "owner@aukeys.com",
            "created_at": "2026-09-01T00:00:00Z",
        }

    def close(self) -> None:
        self.closed = True


class FakeGit:
    def __init__(self) -> None:
        self.init_args = None
        self.push_args = None

    def initialize(self, root, **kwargs):
        self.init_args = (root, kwargs)
        return {"git_created": True, "template_applied": kwargs["apply_template"]}

    def push_all(self, root, **kwargs):
        self.push_args = (root, kwargs)
        return {"commit_sha": "a" * 40, "committed": True, "pushed": True}


def test_manager_defaults_to_real_gitea_target(monkeypatch) -> None:
    monkeypatch.delenv("OPSCLI_APP_REPO_URL", raising=False)

    manager = AppManager(client=FakeClient(), git_service=FakeGit())

    assert manager.target_repo_url == TARGET_REPO_URL


def test_create_binds_existing_directory(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "index.html").write_text("keep", encoding="utf-8")
    manager = AppManager(
        client=FakeClient(),
        git_service=FakeGit(),
        target_repo_url=TARGET_REPO_URL,
    )

    result = manager.create_site("销售看板", path=existing)

    assert result["site_id"] == "site-1"
    assert result["repo_url"] == TARGET_REPO_URL
    assert (existing / "index.html").read_text(encoding="utf-8") == "keep"
    binding = BindingStore().load(existing)
    assert binding.slug == "sales-dashboard"
    assert binding.repo_url == TARGET_REPO_URL


def test_init_existing_project_skips_template(tmp_path: Path) -> None:
    store = BindingStore()
    store.save(
        tmp_path,
        SiteBinding(
            site_id="site-1",
            site_name="销售看板",
            slug="sales-dashboard",
            repo_url="https://gitlab.example/sites/sales-dashboard.git",
        ),
    )
    (tmp_path / "index.html").write_text("keep", encoding="utf-8")
    git = FakeGit()
    manager = AppManager(
        client=FakeClient(),
        binding_store=store,
        git_service=git,
        target_repo_url=TARGET_REPO_URL,
    )

    result = manager.init_git(tmp_path)

    assert git.init_args[1]["apply_template"] is False
    assert git.init_args[1]["repo_url"] == TARGET_REPO_URL
    assert result["template_applied"] is False
    assert store.load(tmp_path).repo_url == TARGET_REPO_URL
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "keep"


def test_create_reuses_same_local_binding_without_remote_call(tmp_path: Path) -> None:
    store = BindingStore()
    store.save(
        tmp_path,
        SiteBinding(
            site_id="site-1",
            site_name="销售看板",
            slug="sales-dashboard",
            repo_url="https://gitlab.example/sites/sales-dashboard.git",
        ),
    )
    client = FakeClient()
    manager = AppManager(
        client=client,
        binding_store=store,
        git_service=FakeGit(),
        target_repo_url=TARGET_REPO_URL,
    )

    result = manager.create_site("销售看板", path=tmp_path)

    assert client.create_calls == 0
    assert result["site_id"] == "site-1"


def test_push_passes_codex_summary(tmp_path: Path) -> None:
    store = BindingStore()
    store.save(
        tmp_path,
        SiteBinding(
            site_id="site-1",
            site_name="销售看板",
            slug="sales-dashboard",
            repo_url="https://gitlab.example/sites/sales-dashboard.git",
        ),
    )
    git = FakeGit()
    manager = AppManager(
        client=FakeClient(),
        binding_store=store,
        git_service=git,
        target_repo_url="https://gitlab.example/sites/sales-dashboard.git",
    )

    result = manager.push(tmp_path, message="优化首页筛选交互")

    assert git.push_args[1]["message"] == "优化首页筛选交互"
    assert result["commit_sha"] == "a" * 40


def test_push_rejects_stale_target_repo_binding(tmp_path: Path) -> None:
    store = BindingStore()
    store.save(
        tmp_path,
        SiteBinding(
            site_id="site-1",
            site_name="销售看板",
            slug="sales-dashboard",
            repo_url="https://gitlab.example/sites/legacy.git",
        ),
    )
    git = FakeGit()
    manager = AppManager(
        client=FakeClient(),
        binding_store=store,
        git_service=git,
        target_repo_url=TARGET_REPO_URL,
    )

    with pytest.raises(AppProjectError) as caught:
        manager.push(tmp_path, message="更新首页")

    assert caught.value.code == "APP-REPO-CONFIG-CHANGED"
    assert git.push_args is None
