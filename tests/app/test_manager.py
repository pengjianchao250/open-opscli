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
        self.keys: list[str] = []
        self.detail_calls: list[str] = []
        self.git_calls: list[str] = []
        self.scope = "qa-owner-1"
        self.api_base_url = "https://apphub.example/api/v1"
        self.created_by_key: dict[str, dict] = {}
        self.apps = {
            "Ab123": {
                "app_id": "Ab123",
                "slug": "sales-dashboard",
                "title": "销售看板",
                "status": "active",
                "repo_url": _repo_url("sales-dashboard"),
                "current_version": "v2",
                "url": "https://apps.example/sales-dashboard",
            }
        }
        self.accessible_slugs = ["sales-dashboard"]

    def creation_scope(self) -> str:
        """模拟稳定的账号与环境作用域。"""
        return self.scope

    def create_app(self, request_payload: dict, *, idempotency_key: str) -> dict:
        self.create_payloads.append(request_payload)
        self.keys.append(idempotency_key)
        if idempotency_key in self.created_by_key:
            return self.created_by_key[idempotency_key]
        slug = request_payload["name"]
        detail = {
            "app_id": f"Ab{len(self.apps) + 1:03}",
            "slug": slug,
            "title": request_payload["title"],
            "status": "registered",
            "repo_url": _repo_url(f"repo-{len(self.apps) + 1}"),
            "current_version": None,
            "url": None,
        }
        self.apps[detail["app_id"]] = detail
        if slug not in self.accessible_slugs:
            self.accessible_slugs.append(slug)
        response = {
            **detail,
            "git_username": "owner",
            "git_credential": {
                "username": "owner",
                "token": "one-time-secret",
                "token_hint": "12345678",
            },
        }
        self.created_by_key[idempotency_key] = response
        return response

    def list_accessible_apps(self) -> dict:
        self.accessible_calls += 1
        return {
            "apps": [
                {
                    "app_id": detail["app_id"],
                    "slug": detail["slug"],
                    "title": detail["title"],
                    "status": detail["status"],
                }
                for detail in self.apps.values()
            ]
        }

    def get_app(self, app_id: str) -> dict:
        self.detail_calls.append(app_id)
        return dict(self.apps[app_id])

    def get_git_config(self, app_id: str) -> dict:
        self.git_calls.append(app_id)
        return {
            "app_id": app_id,
            "repo_url": self.apps[app_id]["repo_url"],
            "default_branch": "master",
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

    def has_credential(self, root, *, repo_url, username, token_hint=None):
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
            "remote_branch": "master",
            "remote_branch_sha": "a" * 40,
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
    assert payload["database"] == {"kind": "sqlite", "path": "/data/app.db"}
    assert "runtime" not in payload
    assert git.init_calls == []
    assert git.push_calls == []
    # 兼容旧服务响应，但 create 不再消费或保存内联 token。
    assert credentials.saved == []
    assert result["credential_saved"] is False
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
            app_id="Ab123",
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
    assert result["app_id"] == "Ab123"
    manifest = (root / "app.yaml").read_text(encoding="utf-8")
    assert 'name: "sales-dashboard"' in manifest
    assert 'title: "销售看板"' in manifest


def test_init_recovers_accessible_application_without_create(tmp_path: Path) -> None:
    app_root = tmp_path / "sales-dashboard"
    app_root.mkdir()
    client = FakeClient()
    git = FakeGit()

    result = _manager(client, git).init_git(app_root, app_id="Ab123")

    assert client.accessible_calls == 0
    assert client.create_payloads == []
    assert result["slug"] == "sales-dashboard"
    assert git.init_calls[0][1] == {
        "repo_url": _repo_url("sales-dashboard"),
        "branch": "master",
    }
    assert result["default_branch"] == "master"
    assert BindingStore().load(app_root).schema_version == 3


def test_init_requires_id_even_when_app_yaml_matches(tmp_path: Path) -> None:
    app_root = tmp_path / "local-worktree"
    app_root.mkdir()
    (app_root / "app.yaml").write_text(
        "name: sales-dashboard\ntitle: 销售看板\n",
        encoding="utf-8",
    )
    client = FakeClient()
    git = FakeGit()

    with pytest.raises(AppProjectError, match="未绑定"):
        _manager(client, git).init_git(app_root)

    assert client.create_payloads == []
    assert client.detail_calls == []
    assert client.accessible_calls == 0
    assert git.init_calls == []


def test_init_without_binding_does_not_create(tmp_path: Path) -> None:
    app_root = tmp_path / "inventory-dashboard"
    app_root.mkdir()
    client = FakeClient()
    client.accessible_slugs = []
    git = FakeGit()
    credentials = FakeCredentialStore()

    with pytest.raises(AppProjectError, match="未绑定"):
        _manager(client, git, credentials).init_git(app_root, app_slug="inventory-dashboard")

    assert client.create_payloads == []
    assert client.accessible_calls == 0
    assert client.issue_calls == []
    assert credentials.saved == []
    assert git.init_calls == []


def test_init_migrates_legacy_binding_without_template_fields(tmp_path: Path) -> None:
    target = tmp_path / ".opscli" / "app.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "app_id": "Ab123",
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

    _manager(FakeClient(), FakeGit()).init_git(tmp_path, app_id="Ab123")

    migrated = json.loads(target.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 3
    assert migrated["repo_url"] == _repo_url("sales-dashboard")
    assert "template_repo_url" not in migrated
    assert "template_branch" not in migrated


def test_push_only_pushes_source_and_never_publishes(tmp_path: Path) -> None:
    BindingStore().save(
        tmp_path,
        SiteBinding(
            app_id="Ab123",
            app_name="销售看板",
            slug="sales-dashboard",
            repo_url=_repo_url("sales-dashboard"),
            git_username="owner",
        ),
    )
    client = FakeClient()
    git = FakeGit()
    credentials = FakeCredentialStore()

    result = _manager(client, git, credentials).push(tmp_path, message="优化首页")

    assert client.issue_calls == [True]
    assert credentials.saved[0]["token"] == "rotated-secret"
    assert result["credential_refreshed"] is True
    assert result["credential_rotated"] is True
    assert git.push_calls[0][1]["message"] == "优化首页"
    assert git.push_calls[0][1]["branch"] == "master"
    assert "release_id" not in result
    assert "version" not in result
    assert result["message"] == "源码已推送到远端仓库。"


def test_same_slug_and_case_sensitive_ids_keep_repositories_separate(tmp_path: Path) -> None:
    """同名应用只按 ID 读写，大小写不同也不能共享仓库。"""
    client = FakeClient()
    client.apps["ab123"] = {
        **client.apps["Ab123"], "app_id": "ab123", "repo_url": _repo_url("second-repo"),
    }
    git = FakeGit()
    manager = _manager(client, git)
    for index, app_id in enumerate(("Ab123", "ab123")):
        # Windows 目录不区分大小写，使用独立目录验证 ID 大小写隔离。
        root = tmp_path / f"project-{index}"
        manager.init_git(root, app_id=app_id)
        manager.push(root, message=f"修改 {app_id}")
        assert BindingStore().load(root).app_id == app_id
    assert [call[1]["repo_url"] for call in git.push_calls] == [
        _repo_url("sales-dashboard"), _repo_url("second-repo"),
    ]
    assert set(client.detail_calls) == {"Ab123", "ab123"}
    assert client.git_calls == ["Ab123", "Ab123", "ab123", "ab123"]
    assert client.accessible_calls == 0


@pytest.mark.parametrize("remote_id", [None, "wrong", "ab123"])
def test_wrong_or_missing_remote_id_never_changes_local_state(tmp_path: Path, remote_id) -> None:
    """返回缺 ID 或另一 ID 时，在修改文件、凭据和 Git 前拒绝。"""
    client = FakeClient()
    binding = SiteBinding.from_app_detail("销售看板", client.apps["Ab123"])
    target = BindingStore().save(tmp_path, binding)
    before = target.read_bytes()
    _write_manifest(tmp_path)
    manifest = (tmp_path / "app.yaml").read_bytes()
    client.apps["Ab123"]["app_id"] = remote_id
    git = FakeGit()
    with pytest.raises(AppProjectError) as caught:
        _manager(client, git).push(tmp_path, message="修改")
    assert caught.value.code == "APPHUB-PROTOCOL"
    assert target.read_bytes() == before
    assert (tmp_path / "app.yaml").read_bytes() == manifest
    assert git.init_calls == git.push_calls == client.git_calls == []


def test_push_missing_binding_does_not_contact_remote(tmp_path: Path) -> None:
    """push 缺绑定时不得隐式登记应用。"""
    client = FakeClient()
    with pytest.raises(AppProjectError) as caught:
        _manager(client, FakeGit()).push(tmp_path, message="修改")
    assert caught.value.code == "APP-NOT-BOUND"
    assert client.detail_calls == client.create_payloads == []


def test_create_timeout_reuses_persisted_key_across_manager_restart(tmp_path: Path) -> None:
    """服务端已创建但响应丢失时，新进程仍携原键，只产生一个应用。"""
    client = FakeClient()
    original = client.create_app
    def timeout_after_create(payload, *, idempotency_key):
        state = json.loads((tmp_path / ".opscli" / "creation.json").read_text(encoding="utf-8"))
        assert state["key"] == idempotency_key
        original(payload, idempotency_key=idempotency_key)
        raise TimeoutError("响应丢失")
    client.create_app = timeout_after_create
    with pytest.raises(TimeoutError):
        _manager(client, FakeGit()).create_app("新应用", path=tmp_path)
    client.create_app = original
    result = _manager(client, FakeGit()).create_app("新应用", path=tmp_path)
    assert len(client.apps) == 2
    assert client.keys[0] == client.keys[1]
    state = json.loads((tmp_path / ".opscli" / "creation.json").read_text(encoding="utf-8"))
    assert state["completed"] is True
    assert state["app_id"] == result["app_id"]
    assert "secret" not in json.dumps(state)


@pytest.mark.parametrize("changed", ["request", "scope"])
def test_pending_create_rejects_changed_request_or_scope(tmp_path: Path, changed: str) -> None:
    """失败创建的请求内容、账号或环境变化时不能复用键发送。"""
    client = FakeClient()
    def fail(payload, *, idempotency_key):
        raise TimeoutError("发送失败")
    client.create_app = fail
    with pytest.raises(TimeoutError):
        _manager(client, FakeGit()).create_app("新应用", path=tmp_path)
    if changed == "scope":
        client.scope = "production-owner-2"
    with pytest.raises(AppProjectError) as caught:
        _manager(client, FakeGit()).create_app("不同名称" if changed == "request" else "新应用", path=tmp_path)
    assert caught.value.code == "APP-CREATE-CONFLICT"


def test_new_directories_create_same_name_with_distinct_intents(tmp_path: Path) -> None:
    """主动在独立目录创建同名应用时生成独立 ID、仓库和幂等键。"""
    client = FakeClient()
    manager = _manager(client, FakeGit())
    a = manager.create_app("同名应用", path=tmp_path / "a")
    b = manager.create_app("同名应用", path=tmp_path / "b")
    assert a["slug"] == b["slug"]
    assert a["app_id"] != b["app_id"]
    assert a["repo_url"] != b["repo_url"]
    assert client.keys[0] != client.keys[1]


@pytest.mark.parametrize("legacy_id", [None, "sales-dashboard", "sales"])
def test_explicit_id_repairs_untrusted_legacy_binding(tmp_path: Path, legacy_id) -> None:
    """遗留无真实 ID 的绑定只允许明确指定 ID 修复，包括五位 slug fallback。"""
    client = FakeClient()
    payload = SiteBinding.from_app_detail("销售看板", client.apps["Ab123"]).to_dict()
    payload["app_id"] = legacy_id
    if legacy_id == "sales":
        payload["slug"] = "sales"
    target = tmp_path / ".opscli" / "app.json"
    target.parent.mkdir()
    target.write_text(json.dumps(payload), encoding="utf-8")
    manager = _manager(client, FakeGit())
    with pytest.raises(AppProjectError):
        manager.init_git(tmp_path)
    assert client.detail_calls == []
    result = manager.init_git(tmp_path, app_id="Ab123")
    assert result["app_id"] == "Ab123"
    assert BindingStore().load(tmp_path).app_id == "Ab123"


def test_bound_project_rejects_another_environment_before_network(tmp_path: Path) -> None:
    """同一公开 ID 出现在另一控制面时，不覆盖原仓库。"""
    client = FakeClient()
    manager = _manager(client, FakeGit())
    manager.init_git(tmp_path, app_id="Ab123")
    client.api_base_url = "https://production.example/api/v1"
    client.detail_calls.clear()
    with pytest.raises(AppProjectError) as caught:
        manager.init_git(tmp_path, app_id="Ab123")
    assert caught.value.code == "APP-BINDING-ENVIRONMENT"
    assert client.detail_calls == []


def test_old_binding_with_changed_repository_requires_explicit_recovery(tmp_path: Path) -> None:
    """没有环境标记的旧绑定必须核对仓库，不能仅凭五位 ID 接管。"""
    client = FakeClient()
    binding = SiteBinding.from_app_detail("销售看板", client.apps["Ab123"])
    BindingStore().save(tmp_path, binding)
    client.apps["Ab123"]["repo_url"] = _repo_url("other-environment")
    manager = _manager(client, FakeGit())
    with pytest.raises(AppProjectError) as caught:
        manager.init_git(tmp_path)
    assert caught.value.code == "APP-BINDING-ENVIRONMENT"
    assert client.git_calls == []


def test_completed_creation_does_not_recreate_after_binding_loss(tmp_path: Path) -> None:
    """已完成意图丢失绑定时仍拒绝新建，保留明确恢复的 ID。"""
    client = FakeClient()
    manager = _manager(client, FakeGit())
    result = manager.create_app("新应用", path=tmp_path)
    binding_path = tmp_path / ".opscli" / "app.json"
    binding_path.rename(binding_path.with_suffix(".backup"))
    with pytest.raises(AppProjectError) as caught:
        manager.create_app("新应用", path=tmp_path)
    assert caught.value.code == "APP-NOT-BOUND"
    assert result["app_id"] in str(caught.value)
    assert len(client.create_payloads) == 1


@pytest.mark.parametrize("config_id", [None, "ab123"])
def test_git_config_requires_matching_id_before_local_changes(tmp_path: Path, config_id) -> None:
    """Git 配置缺失 ID 或指向另一应用时不写绑定、不碰仓库。"""
    client = FakeClient()
    original = client.get_git_config
    client.get_git_config = lambda app_id: {**original(app_id), "app_id": config_id}
    git = FakeGit()
    with pytest.raises(AppProjectError) as caught:
        _manager(client, git).init_git(tmp_path, app_id="Ab123")
    assert caught.value.code == "APPHUB-PROTOCOL"
    assert not BindingStore().is_bound(tmp_path)
    assert git.init_calls == []


def test_confirmed_id_equal_to_slug_remains_usable(tmp_path: Path) -> None:
    """明确恢复后的五位同值 ID/slug 不再被当成历史 fallback。"""
    client = FakeClient()
    client.apps["sales"] = {**client.apps["Ab123"], "app_id": "sales", "slug": "sales"}
    manager = _manager(client, FakeGit())
    manager.init_git(tmp_path, app_id="sales")
    assert manager.push(tmp_path, message="修改")["app_id"] == "sales"
