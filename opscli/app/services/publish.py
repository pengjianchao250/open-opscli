"""Git push 后的 release baseline 与 SSE 发布编排。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.transport.client import AppHubClient


class PublishService:
    def __init__(self, client: AppHubClient) -> None:
        self.client = client

    def publish(
        self,
        slug: str,
        *,
        commit_sha: str,
        message: str,
        releases_payload: dict[str, Any],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        baseline_sha = _baseline_commit_sha(releases_payload)
        if baseline_sha == commit_sha:
            return {
                "release_id": None,
                "status": "noop",
                "error_code": "GIT-004",
                "baseline_commit_sha": baseline_sha,
                "message": "远端 main 与最近健康发布一致，无新内容需要发布。",
            }

        progress = self.client.publish_release(
            slug,
            commit_sha=commit_sha,
            message=message,
            on_event=on_event,
        )
        terminal = progress.get("terminal_event") or {}
        status = str(terminal.get("status") or "unknown")
        if status == "failed":
            raise AppHubHttpError(
                str(terminal.get("error_code") or "PUBLISH-FAILED"),
                str(terminal.get("message") or "AppHub 发布失败。"),
                fix_hint=terminal.get("fix_hint"),
                detail={"release_id": progress.get("release_id")},
            )
        return {
            "release_id": progress.get("release_id"),
            "status": status,
            "last_seq": progress.get("last_seq"),
            "baseline_commit_sha": baseline_sha,
        }


def _baseline_commit_sha(payload: dict[str, Any]) -> str | None:
    baseline = payload.get("baseline")
    if isinstance(baseline, dict):
        value = baseline.get("commit_sha") or baseline.get("git_commit")
        if value:
            return str(value)
    releases = payload.get("releases")
    if not isinstance(releases, list):
        return None
    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("is_rollback") is True or release.get("status") != "healthy":
            continue
        value = release.get("commit_sha") or release.get("git_commit")
        if value:
            return str(value)
    return None
