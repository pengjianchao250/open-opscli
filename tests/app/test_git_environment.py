"""Git 本地环境探测与安装决策测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from opscli.app.services.git_environment import (
    GitEnvironmentService,
    _parse_git_version,
)


def _missing_state(*, platform: str, architecture: str) -> dict:
    return {
        "ready": False,
        "status": "missing",
        "platform": platform,
        "architecture": architecture,
        "translated": False,
        "git_path": None,
        "detected_via": None,
        "git_version": None,
        "minimum_version": "2.30.0",
        "install_method": None,
        "message": "未检测到可用 Git。",
    }


def test_parse_git_version_accepts_git_for_windows_suffix() -> None:
    assert _parse_git_version("git version 2.55.0.windows.1") == (2, 55, 0)


def test_windows_uses_native_architecture_over_process_architecture() -> None:
    service = GitEnvironmentService(
        system="Windows",
        machine="x86_64",
        environ={
            "PROCESSOR_ARCHITECTURE": "AMD64",
            "PROCESSOR_ARCHITEW6432": "ARM64",
        },
    )

    assert service._native_architecture("windows") == ("arm64", False)


def test_check_prefers_highest_supported_git(monkeypatch, tmp_path: Path) -> None:
    old_git = tmp_path / "old-git"
    new_git = tmp_path / "new-git"
    old_git.write_text("", encoding="utf-8")
    new_git.write_text("", encoding="utf-8")
    service = GitEnvironmentService(system="Linux", machine="x86_64")
    monkeypatch.setattr(service, "_git_candidates", lambda *_: [old_git, new_git])
    monkeypatch.setattr(
        service,
        "_git_version",
        lambda executable: (2, 20, 0) if executable == old_git else (2, 45, 2),
    )

    result = service.check()

    assert result["ready"] is True
    assert result["git_path"] == str(new_git)
    assert result["detected_via"] == "standard_location"
    assert result["git_version"] == "2.45.2"


def test_check_reports_path_detection_source(monkeypatch, tmp_path: Path) -> None:
    git = tmp_path / "git"
    git.write_text("", encoding="utf-8")
    service = GitEnvironmentService(system="Linux", machine="x86_64")
    monkeypatch.setattr(service, "_git_candidates", lambda *_: [(git, "path")])
    monkeypatch.setattr(service, "_git_version", lambda executable: (2, 45, 2))

    result = service.check()

    assert result["detected_via"] == "path"


def test_windows_installer_url_matches_requested_architecture(monkeypatch) -> None:
    class FakeResponse:
        text = (
            '<a href="https://github.com/git-for-windows/git/releases/download/'
            'v2.55.0.windows.5/Git-2.55.0.5-64-bit.exe">x64</a>'
            '<a href="https://github.com/git-for-windows/git/releases/download/'
            'v2.55.0.windows.5/Git-2.55.0.5-arm64.exe">arm64</a>'
            '<a href="https://github.com/git-for-windows/git/releases/download/'
            'v2.55.0.windows.5/PortableGit-2.55.0.5-arm64.7z.exe">portable</a>'
        )

        def raise_for_status(self) -> None:
            pass

    monkeypatch.setattr(
        "opscli.app.services.git_environment.httpx.get",
        lambda *args, **kwargs: FakeResponse(),
    )
    service = GitEnvironmentService(system="Windows", machine="ARM64")

    assert service._windows_installer_url("arm64").endswith(
        "Git-2.55.0.5-arm64.exe"
    )
    assert service._windows_installer_url("x64").endswith("Git-2.55.0.5-64-bit.exe")


def test_ensure_returns_elevation_state_without_claiming_ready(monkeypatch) -> None:
    service = GitEnvironmentService(system="Windows", machine="AMD64")
    monkeypatch.setattr(
        service,
        "check",
        lambda: _missing_state(platform="windows", architecture="x64"),
    )
    monkeypatch.setattr(
        service,
        "_install_windows",
        lambda architecture: {
            "status": "elevation_required",
            "install_method": "git-scm-official-installer",
            "message": "需要权限",
        },
    )

    result = service.ensure(install=True)

    assert result["ready"] is False
    assert result["status"] == "elevation_required"
    assert result["install_method"] == "git-scm-official-installer"


def test_ensure_returns_unsupported_architecture_without_installing(monkeypatch) -> None:
    service = GitEnvironmentService(system="Windows", machine="x86")
    monkeypatch.setattr(
        service,
        "check",
        lambda: _missing_state(platform="windows", architecture="x86"),
    )

    result = service.ensure(install=True)

    assert result["ready"] is False
    assert result["status"] == "platform_unsupported"
    assert result["install_method"] is None


def test_macos_without_package_manager_requests_system_confirmation(monkeypatch) -> None:
    service = GitEnvironmentService(system="Darwin", machine="arm64")
    monkeypatch.setattr(service, "_brew_path", lambda *args, **kwargs: None)
    monkeypatch.setattr("opscli.app.services.git_environment.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "opscli.app.services.git_environment.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    result = service._install_macos("arm64", translated=False)

    assert result["status"] == "user_confirmation_required"
    assert result["install_method"] == "apple-command-line-tools"
