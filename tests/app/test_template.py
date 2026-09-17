"""统一模板安全克隆服务测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.template import TemplateService


def test_clone_uses_detected_git_and_removes_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "project"
    commands: list[list[str]] = []

    monkeypatch.setattr(
        "opscli.app.services.template.GitEnvironmentService.ensure",
        lambda self, install: {
            "ready": True,
            "git_path": "C:/runtime/git.exe",
            "status": "ready",
            "message": "ready",
        },
    )

    def run(args, **kwargs):
        commands.append(list(args))
        (target / ".git").mkdir(parents=True)
        (target / ".gitignore").write_text(".opscli/\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("opscli.app.services.template.subprocess.run", run)

    result = TemplateService().clone(target)

    assert commands[0][0] == "C:/runtime/git.exe"
    assert commands[0][1:4] == ["clone", "--branch", "master"]
    assert result["path"] == str(target.resolve())
    assert not (target / ".git").exists()
    assert (target / ".gitignore").is_file()


def test_clone_rejects_non_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(AppProjectError, match="项目目录必须为空"):
        TemplateService().clone(target)


def test_clone_failure_cleans_new_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "project"
    monkeypatch.setattr(
        "opscli.app.services.template.GitEnvironmentService.ensure",
        lambda self, install: {
            "ready": True,
            "git_path": "git",
            "status": "ready",
            "message": "ready",
        },
    )

    def run(args, **kwargs):
        target.mkdir()
        (target / "partial.txt").write_text("partial", encoding="utf-8")
        return subprocess.CompletedProcess(args, 128, "", "network failed")

    monkeypatch.setattr("opscli.app.services.template.subprocess.run", run)

    with pytest.raises(AppProjectError, match="network failed"):
        TemplateService().clone(target)

    assert not target.exists()
