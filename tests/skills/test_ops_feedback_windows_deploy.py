"""反馈日报 Windows 计划任务安装脚本契约测试。"""

from pathlib import Path


INSTALLER = Path(
    "opscli/skills/templates/ops-feedback-query/deploy/install_windows.ps1"
)


def test_windows_installer_registers_prepare_only_at_0830():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "New-ScheduledTaskTrigger -Daily" in text
    assert ".AddHours(8).AddMinutes(30)" in text
    assert '" --prepare-only\')' in text
    assert "New-ScheduledTaskAction" in text
    assert "-WorkingDirectory $resolvedProjectRoot" in text
    assert "Register-ScheduledTask" in text
    assert "--insight" not in text
    assert "--send" not in text


def test_windows_installer_keeps_local_interactive_execution_boundary():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "-LogonType Interactive" in text
    assert "-RunLevel Limited" in text
    assert "-StartWhenAvailable" in text
    assert "-ExecutionTimeLimit (New-TimeSpan -Hours 2)" in text
