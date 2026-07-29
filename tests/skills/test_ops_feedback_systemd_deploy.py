"""反馈日报 systemd 定时部署包契约测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path


DEPLOY_DIR = Path("opscli/skills/templates/ops-feedback-query/deploy")
SERVICE_PATH = DEPLOY_DIR / "systemd" / "ops-feedback-report.service.in"
TIMER_PATH = DEPLOY_DIR / "systemd" / "ops-feedback-report.timer"
INSTALL_PATH = DEPLOY_DIR / "install_systemd.sh"


def test_service_runs_daily_report_once_with_restricted_write_path():
    """服务必须以 oneshot 运行推送命令，并限制项目目录写入范围。"""
    service = SERVICE_PATH.read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert "User=@SERVICE_USER@" in service
    assert "ExecStart=@PYTHON_BIN@ @REPORT_SCRIPT@ --send" in service
    assert "NoNewPrivileges=true" in service
    assert "PrivateTmp=true" in service
    assert "ProtectSystem=strict" in service
    assert "ReadOnlyPaths=@PROJECT_ROOT@" in service
    assert "ReadWritePaths=@OUTPUT_DIR@" in service
    assert "Restart=" not in service


def test_timer_runs_at_nine_in_shanghai_and_catches_up():
    """定时器必须在上海时区每天 09:00 执行并支持错过后补跑。"""
    timer = TIMER_PATH.read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 09:00:00 Asia/Shanghai" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec" not in timer
    assert "Unit=ops-feedback-report.service" in timer


def test_units_do_not_contain_feedback_or_wecom_credentials():
    """systemd 模板不得携带反馈密钥、Webhook 或相关配置字段。"""
    units = SERVICE_PATH.read_text(encoding="utf-8") + TIMER_PATH.read_text(encoding="utf-8")

    assert "feedback_api_key" not in units
    assert "wecom_webhook_url" not in units
    assert "X-Feedback-Api-Key" not in units
    assert "qyapi.weixin.qq.com" not in units


def test_installer_validates_inputs_and_enables_timer():
    """安装脚本必须校验关键文件、收紧权限并启用 timer。"""
    installer = INSTALL_PATH.read_text(encoding="utf-8")

    assert "--project-root" in installer
    assert "--venv" in installer
    assert "--user" in installer
    assert "daily_feedback_report.py" in installer
    assert "credentials.json" in installer
    assert "chmod 0600" in installer
    assert "systemd-analyze verify" in installer
    assert 'systemctl enable --now "${SERVICE_NAME}.timer"' in installer


def test_installer_has_valid_bash_syntax():
    """安装脚本必须通过 Bash 静态语法检查。"""
    result = subprocess.run(
        ["bash", "-n", INSTALL_PATH.as_posix()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
