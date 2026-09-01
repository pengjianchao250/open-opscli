from __future__ import annotations

from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppValidationError
from opscli.app.services.project import ProjectLoader
from opscli.app.services.templates import render_template
from opscli.app.services.validator import AppValidator


class NoopScanner:
    def scan(self, root: Path) -> None:
        return None


def test_generated_template_passes_validation(tmp_path: Path) -> None:
    render_template(tmp_path, slug="demo-app", runtime="streamlit")
    project = ProjectLoader().load(tmp_path)
    report = AppValidator(NoopScanner()).validate(project)
    assert report.blocked is False


def test_database_file_blocks_even_when_ignored(tmp_path: Path) -> None:
    render_template(tmp_path, slug="demo-app", runtime="fastapi")
    (tmp_path / "local.db").write_bytes(b"not sqlite")
    project = ProjectLoader().load(tmp_path)

    with pytest.raises(AppValidationError) as caught:
        AppValidator(NoopScanner()).validate(project)

    assert caught.value.code == "VALIDATE_BLOCKED"
    assert any(item["code"] == "DB-001" for item in caught.value.detail["violations"])


def test_sql_interpolation_blocks(tmp_path: Path) -> None:
    render_template(tmp_path, slug="demo-app", runtime="fastapi")
    (tmp_path / "app.py").write_text('cursor.execute(f"SELECT * FROM t WHERE id={value}")\n', encoding="utf-8")
    project = ProjectLoader().load(tmp_path)
    with pytest.raises(AppValidationError) as caught:
        AppValidator(NoopScanner()).validate(project)
    assert any(item["code"] == "DB-005" for item in caught.value.detail["violations"])
