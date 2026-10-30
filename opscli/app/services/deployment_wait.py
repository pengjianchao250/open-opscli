"""Wait for one pushed commit and retain separate failure artifacts."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from opscli.app.domain.exceptions import AppHubHttpError, AppProjectError
from opscli.app.transport.client import AppHubClient
from opscli.config import CONFIG_DIR


INTERVAL_SECONDS = 15.0
DEFAULT_TIMEOUT_SECONDS = 1200.0
MAX_TIMEOUT_SECONDS = 3600.0
_TERMINAL = {"healthy", "healthy_not_current", "failed", "superseded"}
_RETRYABLE_ERRORS = {"UPSTREAM_ERROR", "HTTP-500", "HTTP-502", "HTTP-503", "HTTP-504"}
_DIAG_HEADERS = re.compile(r"(?i)(\b(?:authorization|cookie|set-cookie)\s*[:=]\s*)[^\n]*")
_DIAG_SECRETS = re.compile(
    r"(?i)(\b[a-z0-9_]*(?:token|password|secret|api[_-]?key)[a-z0-9_]*\b\s*[:=]\s*)([^\s,;]+)"
)
_DIAG_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+")


def _save_attachment(directory: Path, filename: str, content: str, *, redacted: bool) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(target)
    return {
        "path": target.resolve().as_posix(), "filename": target.name,
        "media_type": "text/plain; charset=utf-8", "redacted": redacted,
    }


def _one_line(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _diagnosis_report(app_id: str, commit_sha: str, release_id: int, events: list[dict]) -> tuple[str, bool]:
    lines = [
        "AppHub 发布诊断", f"应用 ID：{app_id}", f"提交 SHA：{commit_sha}",
        f"Release ID：{release_id}", "",
    ]
    for event in events:
        if event.get("level") == "hidden":
            continue
        seq = event.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
            raise ValueError("invalid diagnosis event sequence")
        level = event.get("level")
        message = event.get("message")
        if not isinstance(level, str) or not isinstance(message, str):
            raise ValueError("invalid diagnosis event text")
        status = event.get("status")
        if status is not None and not isinstance(status, str):
            raise ValueError("invalid diagnosis event status")
        label = f"#{seq} [{level}]" + (f" [{status}]" if status else "")
        lines.append(f"{label} {_one_line(message)}")
        for key, title in (("error_code", "错误码"), ("fix_hint", "修复建议")):
            value = event.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError("invalid diagnosis event detail")
                lines.append(f"  {title}：{_one_line(value)}")
        detail = event.get("detail")
        if isinstance(detail, dict):
            findings = detail.get("findings")
            locations = findings if isinstance(findings, list) else [detail]
            for location in locations:
                if not isinstance(location, dict):
                    continue
                parts = []
                file = location.get("file")
                line = location.get("line")
                rule_id = location.get("rule_id")
                if isinstance(file, str) and file.strip():
                    parts.append(f"文件：{_one_line(file)}")
                if isinstance(line, int) and not isinstance(line, bool) and line > 0:
                    parts.append(f"行：{line}")
                if isinstance(rule_id, str) and rule_id.strip():
                    parts.append(f"规则：{_one_line(rule_id)}")
                if parts:
                    lines.append("  问题定位：" + "；".join(parts))
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    text, headers = _DIAG_HEADERS.subn(r"\1[REDACTED]", text)
    text, secrets = _DIAG_SECRETS.subn(r"\1[REDACTED]", text)
    text, bearer = _DIAG_BEARER.subn("Bearer [REDACTED]", text)
    return text, headers + secrets + bearer > 0


def wait_for_deployment(
    client: AppHubClient,
    app_id: str,
    commit_sha: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    interval: float = INTERVAL_SECONDS,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log_dir: Path | None = None,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise AppProjectError("APP-COMMIT-INVALID", "提交 SHA 必须是 40 位小写十六进制。")
    if not 0 < timeout <= MAX_TIMEOUT_SECONDS or interval <= 0:
        raise AppProjectError("APP-WAIT-DURATION", "发布等待时长超出允许范围。")

    deadline = now() + timeout
    next_query = now()
    consecutive_errors = 0
    while True:
        remaining = deadline - now()
        if remaining < 0:
            return {"status": "unknown_timeout", "app_id": app_id, "commit_sha": commit_sha}
        sleep(max(0.0, min(next_query - now(), remaining)))
        if now() >= deadline:
            return {"status": "unknown_timeout", "app_id": app_id, "commit_sha": commit_sha}
        query_started = now()
        try:
            state = client.get_deployment_by_commit(app_id, commit_sha)
        except AppHubHttpError as exc:
            error = {
                "status": "query_error", "app_id": app_id, "commit_sha": commit_sha,
                "error_code": exc.code, "error_summary": str(exc),
            }
            consecutive_errors += 1
            if exc.code not in _RETRYABLE_ERRORS or consecutive_errors >= 3:
                return error
            next_query = query_started + interval
            continue
        consecutive_errors = 0
        if state.get("commit_sha") != commit_sha or state.get("app_id") != app_id:
            return {
                "status": "query_error", "app_id": app_id, "commit_sha": commit_sha,
                "error_code": "APPHUB-PROTOCOL", "error_summary": "发布查询返回的应用或提交不匹配。",
            }
        status = state.get("status")
        if status == "healthy" and (
            not state.get("is_current_release") or not state.get("entry_url")
        ):
            state["status"] = "healthy_not_current"
            state["entry_url"] = None
            status = "healthy_not_current"
        if status in _TERMINAL:
            if status == "failed":
                target_dir = log_dir or CONFIG_DIR / "app-build-logs"
                release_id = state.get("release_id")
                if isinstance(release_id, int) and not isinstance(release_id, bool) and release_id > 0:
                    try:
                        events = client.get_release_diagnosis(app_id, release_id)
                        if not events:
                            raise ValueError("release diagnosis has no visible events")
                        text, redacted = _diagnosis_report(app_id, commit_sha, release_id, events)
                        state["diagnosis_attachment"] = _save_attachment(
                            target_dir, f"{app_id}-{commit_sha}-diagnosis.log", text,
                            redacted=redacted,
                        )
                        state["diagnosis_attachment"]["event_count"] = len(events)
                    except (AppHubHttpError, OSError, ValueError):
                        state["diagnosis_unavailable"] = True
                else:
                    state["diagnosis_unavailable"] = True

                if state.get("deployment_id"):
                    try:
                        log = client.get_complete_build_log(app_id, state["deployment_id"])
                        if (
                            log.get("app_id") != app_id
                            or log.get("deployment_id") != state["deployment_id"]
                            or log.get("release_id") != release_id
                            or not isinstance(log.get("text"), str)
                            or not log["text"].strip()
                        ):
                            raise ValueError("build log identity mismatch")
                        state["build_log_attachment"] = _save_attachment(
                            target_dir, f"{app_id}-{commit_sha}.log", log["text"],
                            redacted=bool(log.get("redacted")),
                        )
                    except (AppHubHttpError, OSError, ValueError):
                        state["logs_unavailable"] = True
            return state
        next_query = query_started + interval
