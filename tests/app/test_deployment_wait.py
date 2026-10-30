"""Commit-scoped release waiting and complete log retention."""

from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.services.deployment_wait import wait_for_deployment


SHA = "a" * 40


class Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def test_wait_queries_immediately_then_every_fifteen_seconds() -> None:
    clock = Clock()
    calls = []

    class Client:
        def get_deployment_by_commit(self, app_id, sha):
            calls.append((clock.now(), app_id, sha))
            status = "healthy" if len(calls) == 3 else "deploying"
            return {
                "app_id": app_id, "commit_sha": sha, "status": status,
                "is_current_release": status == "healthy",
                "entry_url": "https://ops.example/iframeEntry?menuId=apphub:Ab123" if status == "healthy" else None,
            }

    state = wait_for_deployment(Client(), "Ab123", SHA, now=clock.now, sleep=clock.sleep)
    assert [call[0] for call in calls] == [0, 15, 30]
    assert state["status"] == "healthy"


def test_failure_saves_complete_log_for_same_release(tmp_path) -> None:
    class Client:
        def get_deployment_by_commit(self, app_id, sha):
            return {
                "app_id": app_id, "commit_sha": sha, "status": "failed",
                "release_id": 7, "deployment_id": "dep-7", "error_code": "BUILD-FAILED",
            }

        def get_complete_build_log(self, app_id, dep):
            assert (app_id, dep) == ("Ab123", "dep-7")
            return {
                "app_id": app_id, "deployment_id": dep, "release_id": 7,
                "text": "first\n" + "middle\n" * 1500 + "last\n", "redacted": True,
            }

        def get_release_diagnosis(self, app_id, release_id):
            assert (app_id, release_id) == ("Ab123", 7)
            return [
                {"seq": 1, "level": "info", "message": "开始校验"},
                {
                    "seq": 4, "level": "error", "status": "failed",
                    "message": "构建失败 token=secret-value", "error_code": "BUILD-FAILED",
                    "fix_hint": "检查依赖", "detail": {
                        "findings": [{"rule_id": "rule-1", "file": "src/app.py", "line": 12,
                                      "secret": "must-not-appear"}],
                    },
                },
                {"seq": 5, "level": "warn", "message": "Authorization: Bearer private-token"},
            ]

    state = wait_for_deployment(Client(), "Ab123", SHA, log_dir=tmp_path)
    attachment = state["build_log_attachment"]
    assert attachment["redacted"] is True
    assert (tmp_path / attachment["filename"]).read_text(encoding="utf-8").endswith("last\n")
    assert len((tmp_path / attachment["filename"]).read_text(encoding="utf-8").splitlines()) == 1502
    diagnosis = state["diagnosis_attachment"]
    text = (tmp_path / diagnosis["filename"]).read_text(encoding="utf-8")
    assert diagnosis["event_count"] == 3
    assert "#4 [error] [failed]" in text
    assert "错误码：BUILD-FAILED" in text
    assert "文件：src/app.py；行：12；规则：rule-1" in text
    assert "token=[REDACTED]" in text
    assert "secret-value" not in text
    assert "private-token" not in text
    assert "must-not-appear" not in text
    assert "first\n" not in text


def test_timeout_does_not_poll_after_deadline() -> None:
    clock = Clock()
    calls = []

    class Client:
        def get_deployment_by_commit(self, app_id, sha):
            calls.append(clock.now())
            return {"app_id": app_id, "commit_sha": sha, "status": "not_started"}

    state = wait_for_deployment(Client(), "Ab123", SHA, timeout=20, now=clock.now, sleep=clock.sleep)
    assert state["status"] == "unknown_timeout"
    assert calls == [0, 15]


def test_predeployment_failure_has_no_fake_log_attachment(tmp_path) -> None:
    class Client:
        def get_deployment_by_commit(self, app_id, sha):
            return {
                "app_id": app_id, "commit_sha": sha, "status": "failed",
                "release_id": 8, "deployment_id": None, "error_code": "VALIDATION-FAILED",
            }

        def get_complete_build_log(self, *_args):
            raise AssertionError("predeployment failure has no Coolify log")

        def get_release_diagnosis(self, app_id, release_id):
            assert (app_id, release_id) == ("Ab123", 8)
            return [{"seq": 1, "level": "error", "status": "failed", "message": "配置校验失败"}]

    state = wait_for_deployment(Client(), "Ab123", SHA, log_dir=tmp_path)
    assert state["status"] == "failed"
    assert "build_log_attachment" not in state
    assert (tmp_path / state["diagnosis_attachment"]["filename"]).exists()
    assert len(list(tmp_path.iterdir())) == 1


def test_diagnosis_failure_does_not_drop_complete_build_log(tmp_path) -> None:
    class Client:
        def get_deployment_by_commit(self, app_id, sha):
            return {"app_id": app_id, "commit_sha": sha, "status": "failed",
                    "release_id": 7, "deployment_id": "dep-7"}

        def get_release_diagnosis(self, *_args):
            raise AppHubHttpError("UPSTREAM_ERROR", "event stream unavailable")

        def get_complete_build_log(self, app_id, deployment_id):
            return {"app_id": app_id, "deployment_id": deployment_id,
                    "release_id": 7, "text": "complete build log", "redacted": False}

    state = wait_for_deployment(Client(), "Ab123", SHA, log_dir=tmp_path)
    assert state["diagnosis_unavailable"] is True
    assert "diagnosis_attachment" not in state
    assert (tmp_path / state["build_log_attachment"]["filename"]).read_text() == "complete build log"


def test_build_log_failure_does_not_drop_release_diagnosis(tmp_path) -> None:
    class Client:
        def get_deployment_by_commit(self, app_id, sha):
            return {"app_id": app_id, "commit_sha": sha, "status": "failed",
                    "release_id": 7, "deployment_id": "dep-7"}

        def get_release_diagnosis(self, *_args):
            return [{"seq": 1, "level": "error", "status": "failed", "message": "构建失败"}]

        def get_complete_build_log(self, *_args):
            raise AppHubHttpError("UPSTREAM_ERROR", "build log unavailable")

    state = wait_for_deployment(Client(), "Ab123", SHA, log_dir=tmp_path)
    assert state["logs_unavailable"] is True
    assert "build_log_attachment" not in state
    assert (tmp_path / state["diagnosis_attachment"]["filename"]).exists()


def test_transient_query_error_retries_at_fifteen_second_intervals() -> None:
    clock = Clock()
    calls = []

    class Client:
        def get_deployment_by_commit(self, app_id, sha):
            calls.append(clock.now())
            if len(calls) < 3:
                raise AppHubHttpError("UPSTREAM_ERROR", "temporary")
            return {"app_id": app_id, "commit_sha": sha, "status": "healthy", "is_current_release": True, "entry_url": "https://ops.example/iframeEntry?menuId=apphub:Ab123"}

    state = wait_for_deployment(Client(), "Ab123", SHA, now=clock.now, sleep=clock.sleep)
    assert calls == [0, 15, 30]
    assert state["status"] == "healthy"
