"""AppHub D9 publish 状态机。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from opscli.app.domain.constants import MESSAGE_MAX_LENGTH, TERMINAL_STATUSES
from opscli.app.domain.exceptions import (
    AppHubBusinessError,
    AppHubProtocolError,
    AppProjectError,
    PublishInterruptedError,
)
from opscli.app.domain.models import AppProject, PublishResult, PublishSession
from opscli.app.services.credentials import GitCredentialService
from opscli.app.services.gitops import GitService
from opscli.app.services.project import ProjectLoader
from opscli.app.services.scanner import GitleaksScanner
from opscli.app.services.session import PublishSessionStore
from opscli.app.services.sse import parse_sse
from opscli.app.transport.client import AppHubClient

ProgressCallback = Callable[[dict[str, Any]], None]


class PublishManager:
    """编排项目校验、Git push、release API 与 SSE 续订。"""

    def __init__(
        self,
        *,
        client: AppHubClient | None = None,
        project_loader: ProjectLoader | None = None,
        git_service: GitService | None = None,
        scanner: GitleaksScanner | None = None,
        session_store: PublishSessionStore | None = None,
        credential_service: GitCredentialService | None = None,
    ) -> None:
        self.client = client or AppHubClient()
        self.project_loader = project_loader or ProjectLoader()
        self.git_service = git_service or GitService()
        self.scanner = scanner or GitleaksScanner()
        self.session_store = session_store or PublishSessionStore()
        self.credentials = credential_service or GitCredentialService(
            self.client,
            self.git_service,
        )

    def close(self) -> None:
        """释放 HTTP 连接。"""
        self.client.close()

    def publish(
        self,
        path: str | Path = ".",
        *,
        message: str | None = None,
        resume: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> PublishResult:
        """执行发布或从本地句柄续订。"""
        project = self.project_loader.load(path)
        if resume:
            if message:
                raise AppProjectError("APP-ARGUMENT", "--resume 与 --message 不能同时使用。")
            return self._resume(project, on_progress=on_progress)

        publish_message = (message or "").strip()
        if not publish_message:
            raise AppProjectError(
                "APP-ARGUMENT",
                "非交互发布必须提供 --message。",
                fix_hint="例如：opscli app publish -m \"发布首页更新\"",
            )
        if len(publish_message) > MESSAGE_MAX_LENGTH:
            raise AppProjectError(
                "APP-ARGUMENT",
                f"--message 最长 {MESSAGE_MAX_LENGTH} 字符。",
            )

        git_config = self.client.get_git_config(project.slug)
        self.git_service.preflight(project.root, project.slug, git_config.repo_url)
        credential_file = self.credentials.ensure_usable(project, git_config)
        self.git_service.fetch(project.root, credential_file)
        self.scanner.scan(project.root)

        dirty = self.git_service.is_dirty(project.root)
        releases_before = self.client.list_releases(project.slug)
        baseline = releases_before.get("baseline")
        commit_sha, pushed = self.git_service.select_publish_sha(
            project.root,
            credential_file,
            dirty=dirty,
            message=publish_message,
        )

        baseline_sha = baseline.get("commit_sha") if isinstance(baseline, dict) else None
        if not dirty and not pushed and baseline_sha == commit_sha:
            return PublishResult(
                slug=project.slug,
                release_id=_optional_int(baseline.get("id")) if isinstance(baseline, dict) else None,
                status="noop",
                commit_sha=commit_sha,
                version=baseline.get("display_version") if isinstance(baseline, dict) else None,
                tag=baseline.get("tag") if isinstance(baseline, dict) else None,
                url=f"{self.client.base_url}/apps/{project.slug}",
                message="没有可发布的改动。",
                noop=True,
            )

        try:
            with self.client.release_stream(project.slug, commit_sha, publish_message) as response:
                return self._consume_stream(
                    project,
                    commit_sha,
                    response,
                    expected_release_id=None,
                    require_first_frame=True,
                    on_progress=on_progress,
                )
        except httpx.HTTPError as exc:
            raise PublishInterruptedError(
                "APP-PUBLISH-INTERRUPTED",
                "发布连接中断。若已生成句柄，请使用 --resume 继续。",
                fix_hint="执行 opscli app publish --resume。",
            ) from exc

    def git_status(self, path: str | Path = ".") -> dict:
        """检查应用仓库和 Git 凭据状态。"""
        project = self.project_loader.load(path)
        return self.credentials.status(project)

    def git_bind(self, path: str | Path = ".", *, rotate: bool = False) -> dict:
        """签发并绑定本机 Git 凭据。"""
        project = self.project_loader.load(path)
        return self.credentials.bind(project, rotate=rotate)

    def git_revoke(self) -> dict:
        """吊销当前用户 Git 凭据。"""
        return self.credentials.revoke()

    def _resume(
        self,
        project: AppProject,
        *,
        on_progress: ProgressCallback | None,
    ) -> PublishResult:
        session = self.session_store.load(project.slug)
        if session.slug != project.slug:
            raise AppProjectError("APP-SESSION-INVALID", "发布句柄 slug 与当前项目不一致。")
        try:
            with self.client.resume_stream(
                project.slug,
                session.release_id,
                session.last_seq,
            ) as response:
                return self._consume_stream(
                    project,
                    session.commit_sha,
                    response,
                    expected_release_id=session.release_id,
                    require_first_frame=False,
                    on_progress=on_progress,
                    existing_session=session,
                )
        except httpx.HTTPError as exc:
            raise PublishInterruptedError(
                "APP-PUBLISH-INTERRUPTED",
                "发布续订连接再次中断，句柄已保留。",
                fix_hint="网络恢复后再次执行 opscli app publish --resume。",
                release_id=session.release_id,
            ) from exc

    def _consume_stream(
        self,
        project: AppProject,
        commit_sha: str,
        response: httpx.Response,
        *,
        expected_release_id: int | None,
        require_first_frame: bool,
        on_progress: ProgressCallback | None,
        existing_session: PublishSession | None = None,
    ) -> PublishResult:
        header_value = response.headers.get("X-Apphub-Release-Id")
        try:
            release_id = int(header_value) if header_value is not None else expected_release_id
        except ValueError as exc:
            raise AppHubProtocolError("APPHUB-PROTOCOL", "release id 响应头不是整数。") from exc
        if release_id is None:
            raise AppHubProtocolError("APPHUB-PROTOCOL", "AppHub 未返回 release id。")
        if expected_release_id is not None and release_id != expected_release_id:
            raise AppHubProtocolError(
                "APPHUB-PROTOCOL",
                "续订响应的 release id 与本地句柄不一致。",
                release_id=expected_release_id,
            )

        session = existing_session or PublishSession(
            release_id=release_id,
            last_seq=0,
            slug=project.slug,
            commit_sha=commit_sha,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.session_store.save(session)
        last_seq = session.last_seq
        latest_payload: dict[str, Any] = {}
        saw_done = False
        first_data_frame = True

        try:
            for frame in parse_sse(response.iter_lines()):
                if frame.event == "done":
                    saw_done = True
                    break
                payload = frame.data
                seq = payload.get("seq")
                if not isinstance(seq, int) or seq < 0:
                    raise AppHubProtocolError(
                        "APPHUB-PROTOCOL",
                        "SSE 事件缺少有效 seq。",
                        release_id=release_id,
                    )
                if require_first_frame and first_data_frame:
                    if seq != 0 or _optional_int(payload.get("release_id")) != release_id:
                        raise AppHubProtocolError(
                            "APPHUB-PROTOCOL",
                            "SSE 首帧与 X-Apphub-Release-Id 不一致。",
                            release_id=release_id,
                        )
                first_data_frame = False
                if seq <= last_seq:
                    continue
                last_seq = seq
                session = PublishSession(
                    release_id=release_id,
                    last_seq=last_seq,
                    slug=project.slug,
                    commit_sha=commit_sha,
                    started_at=session.started_at,
                )
                self.session_store.save(session)
                latest_payload = payload
                if payload.get("level") != "hidden" and on_progress is not None:
                    on_progress(payload)
        except (httpx.HTTPError, OSError) as exc:
            raise PublishInterruptedError(
                "APP-PUBLISH-INTERRUPTED",
                "发布流中断，续订句柄已保留。",
                fix_hint="执行 opscli app publish --resume。",
                release_id=release_id,
            ) from exc

        if not saw_done:
            raise PublishInterruptedError(
                "APP-PUBLISH-INTERRUPTED",
                "发布流在终态前结束，续订句柄已保留。",
                fix_hint="执行 opscli app publish --resume。",
                release_id=release_id,
            )

        releases = self.client.list_releases(project.slug)
        release = _find_release(releases, release_id)
        status = str((release or {}).get("status") or latest_payload.get("status") or "")
        self.session_store.clear(project.slug)
        if status not in TERMINAL_STATUSES:
            raise AppHubProtocolError(
                "APPHUB-PROTOCOL",
                f"SSE 已结束但 release 状态不是终态: {status or '(missing)'}",
                release_id=release_id,
            )
        if status != "healthy":
            raise AppHubBusinessError(
                str(latest_payload.get("error_code") or (release or {}).get("error_code") or status.upper()),
                str(latest_payload.get("message") or f"发布以 {status} 结束。"),
                fix_hint=latest_payload.get("fix_hint"),
                release_id=release_id,
                detail=latest_payload.get("detail") if isinstance(latest_payload.get("detail"), dict) else None,
            )
        return PublishResult(
            slug=project.slug,
            release_id=release_id,
            status=status,
            commit_sha=str((release or {}).get("commit_sha") or commit_sha),
            version=(release or {}).get("display_version"),
            tag=(release or {}).get("tag"),
            url=f"{self.client.base_url}/apps/{project.slug}",
            message=latest_payload.get("message"),
        )


def _find_release(payload: dict[str, Any], release_id: int) -> dict[str, Any] | None:
    releases = payload.get("releases")
    if not isinstance(releases, list):
        return None
    for item in releases:
        if isinstance(item, dict) and _optional_int(item.get("id")) == release_id:
            return item
    baseline = payload.get("baseline")
    if isinstance(baseline, dict) and _optional_int(baseline.get("id")) == release_id:
        return baseline
    return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

