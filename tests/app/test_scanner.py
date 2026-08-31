"""gitleaks JSON 报告判定与脱敏测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppError
from opscli.app.services.scanner import GitleaksScanner, _sanitize_finding


def test_sanitize_finding_only_keeps_safe_fields(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    finding = {
        "RuleID": "generic-api-key",
        "File": str(source),
        "StartLine": 12,
        "Secret": "must-not-leak",
        "Match": "must-not-leak",
        "Author": "private@example.com",
    }

    safe = _sanitize_finding(finding, tmp_path)

    assert safe == {"rule_id": "generic-api-key", "file": "src/app.py", "line": 12}
    assert "must-not-leak" not in repr(safe)


def test_scanner_uses_report_file_not_exit_code(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "gitleaks")

    def fake_run(command, **kwargs):
        report_path = Path(command[command.index("--report-path") + 1])
        report_path.write_text("[]", encoding="utf-8")

        class Completed:
            returncode = 1
            stdout = "ignored"
            stderr = "ignored"

        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    GitleaksScanner().scan(tmp_path)


def test_scanner_missing_report_is_fail_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "gitleaks")

    def fake_run(command, **kwargs):
        class Completed:
            returncode = 1
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(AppError) as caught:
        GitleaksScanner().scan(tmp_path)

    assert caught.value.code == "ERR_UPSTREAM"


def test_scanner_hit_never_exposes_secret(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "gitleaks")
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        report_path = Path(command[command.index("--report-path") + 1])
        report = []
        if calls == 1:
            report = [{
                "RuleID": "generic-api-key",
                "File": "app.py",
                "StartLine": 2,
                "Secret": "must-not-leak",
            }]
        report_path.write_text(json.dumps(report), encoding="utf-8")

        class Completed:
            returncode = 1 if report else 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(AppError) as caught:
        GitleaksScanner().scan(tmp_path)

    assert caught.value.code == "AUTH-003"
    assert "must-not-leak" not in repr(caught.value.to_dict())

