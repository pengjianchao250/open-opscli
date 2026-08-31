"""发布 NOOP、SSE 成功和 resume 关键路径测试。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import httpx

from opscli.app.domain.models import AppManifest, AppProject, GitConfig, PublishSession
from opscli.app.services.publish import PublishManager
from opscli.app.services.session import PublishSessionStore


def _project(tmp_path: Path) -> AppProject:
    manifest = AppManifest(
        api_version="apps.aukeys/v1",
        name="demo-app",
        runtime="streamlit",
        python="3.11",
        entrypoint="app.py",
        raw={},
    )
    return AppProject(tmp_path, tmp_path / "app.yaml", manifest)


class Loader:
    def __init__(self, project):
        self.project = project

    def load(self, path):
        return self.project


class Scanner:
    def __init__(self):
        self.called = False

    def scan(self, root):
        self.called = True


class Credentials:
    def __init__(self, path):
        self.path = path

    def ensure_usable(self, project, config):
        return self.path


class Git:
    def __init__(self, *, dirty=False, sha="a" * 40, pushed=False):
        self.dirty = dirty
        self.sha = sha
        self.pushed = pushed

    def preflight(self, root, slug, repo_url):
        return repo_url

    def fetch(self, root, credential_file):
        return None

    def is_dirty(self, root):
        return self.dirty

    def select_publish_sha(self, root, credential_file, *, dirty, message):
        return self.sha, self.pushed


class Client:
    base_url = "https://apphub.example"

    def __init__(self, release_payloads, stream_text=""):
        self.release_payloads = list(release_payloads)
        self.stream_text = stream_text
        self.release_calls = 0

    def close(self):
        return None

    def get_git_config(self, slug):
        return GitConfig("https://git.example/apps/demo-app.git", "user", True)

    def list_releases(self, slug):
        return self.release_payloads.pop(0)

    @contextmanager
    def release_stream(self, slug, commit_sha, message):
        self.release_calls += 1
        yield httpx.Response(
            200,
            content=self.stream_text.encode(),
            headers={"X-Apphub-Release-Id": "9"},
            request=httpx.Request("POST", "https://apphub.example/api/releases"),
        )

    @contextmanager
    def resume_stream(self, slug, release_id, last_seq):
        yield httpx.Response(
            200,
            content=self.stream_text.encode(),
            headers={"X-Apphub-Release-Id": str(release_id)},
            request=httpx.Request("GET", "https://apphub.example/api/events"),
        )


def test_clean_published_sha_is_noop(tmp_path: Path) -> None:
    sha = "a" * 40
    client = Client([{"baseline": {"id": 3, "commit_sha": sha, "display_version": "v2", "tag": "v2"}}])
    scanner = Scanner()
    manager = PublishManager(
        client=client,
        project_loader=Loader(_project(tmp_path)),
        git_service=Git(sha=sha),
        scanner=scanner,
        session_store=PublishSessionStore(base_dir=tmp_path / "config"),
        credential_service=Credentials(tmp_path / "credential"),
    )

    result = manager.publish(tmp_path, message="publish")

    assert result.noop is True
    assert result.release_id == 3
    assert client.release_calls == 0
    assert scanner.called is True


def test_publish_consumes_sse_and_enriches_release(tmp_path: Path) -> None:
    sha = "b" * 40
    stream = "\n".join([
        'data: {"seq":0,"level":"info","status":"received","release_id":9}',
        "",
        'data: {"seq":1,"level":"info","status":"healthy","message":"发布完成"}',
        "",
        "event: done",
        "data: {}",
        "",
    ])
    client = Client([
        {"baseline": None},
        {"releases": [{"id": 9, "status": "healthy", "commit_sha": sha, "display_version": "v1", "tag": "v1"}]},
    ], stream)
    store = PublishSessionStore(base_dir=tmp_path / "config")
    manager = PublishManager(
        client=client,
        project_loader=Loader(_project(tmp_path)),
        git_service=Git(sha=sha),
        scanner=Scanner(),
        session_store=store,
        credential_service=Credentials(tmp_path / "credential"),
    )

    result = manager.publish(tmp_path, message="publish")

    assert result.status == "healthy"
    assert result.version == "v1"
    assert result.release_id == 9
    assert not store.path_for("demo-app").exists()


def test_resume_uses_saved_release_without_git(tmp_path: Path) -> None:
    sha = "c" * 40
    stream = "\n".join([
        'data: {"seq":2,"level":"info","status":"healthy","message":"发布完成"}',
        "",
        "event: done",
        "data: {}",
        "",
    ])
    client = Client([
        {"releases": [{"id": 12, "status": "healthy", "commit_sha": sha, "display_version": "v4", "tag": "v4"}]},
    ], stream)
    store = PublishSessionStore(base_dir=tmp_path / "config")
    store.save(PublishSession(12, 1, "demo-app", sha, "2026-08-31T00:00:00+00:00"))

    class NoGit:
        def preflight(self, *args, **kwargs):
            raise AssertionError("resume must not run git")

    manager = PublishManager(
        client=client,
        project_loader=Loader(_project(tmp_path)),
        git_service=NoGit(),
        scanner=Scanner(),
        session_store=store,
        credential_service=Credentials(tmp_path / "credential"),
    )

    result = manager.publish(tmp_path, resume=True)

    assert result.release_id == 12
    assert result.status == "healthy"

