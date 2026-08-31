"""本地 gitleaks fail-closed 门禁。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from opscli.app.domain.exceptions import AppError


class GitleaksScanner:
    """在任何 commit/push 前扫描仓库与未提交改动。"""

    def __init__(self, *, timeout: float = 180.0) -> None:
        self.timeout = timeout

    def scan(self, root: Path) -> None:
        """分别扫描工作区与 origin/main..HEAD，报告缺失时 fail-closed。"""
        executable = shutil.which("gitleaks")
        if not executable:
            raise AppError(
                "AUTH-003",
                "未找到 gitleaks，发布已按 fail-closed 策略阻断。",
                fix_hint="安装受信任的 gitleaks 后重试。",
            )
        findings = self._scan_target(executable, root, mode="dir")
        findings.extend(self._scan_target(executable, root, mode="git"))
        if findings:
            raise AppError(
                "AUTH-003",
                "gitleaks 检测到疑似密钥，已阻止 commit 和 push。",
                fix_hint=(
                    "先吊销源系统中的泄漏凭据，再移除代码中的密钥；"
                    "若命中来自本地领先提交，还需重写本地 Git 历史。"
                ),
                detail={"findings": findings},
            )

    def _scan_target(self, executable: str, root: Path, *, mode: str) -> list[dict]:
        env = os.environ.copy()
        env.update({"LC_ALL": "C", "LANG": "C"})
        fd, report_name = tempfile.mkstemp(prefix=f"opscli-gitleaks-{mode}-", suffix=".json")
        os.close(fd)
        report_path = Path(report_name)
        report_path.unlink()
        command = [
            executable,
            mode,
            str(root),
            "--redact",
            "--report-format",
            "json",
            "--report-path",
            str(report_path),
        ]
        if mode == "git":
            command.extend(["--log-opts", "origin/main..HEAD"])
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AppError(
                "AUTH-003",
                "gitleaks 执行异常，发布已按 fail-closed 策略阻断。",
                fix_hint="修复 gitleaks 安装或执行环境后重试。",
            ) from exc
        try:
            if not report_path.is_file():
                raise AppError(
                    "ERR_UPSTREAM",
                    "gitleaks 未生成 JSON 报告，发布已按 fail-closed 策略阻断。",
                    fix_hint="检查 gitleaks 版本与执行环境后重试；本次未提交或推送。",
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, list):
                raise ValueError("report is not a list")
            return [_sanitize_finding(item, root) for item in report if isinstance(item, dict)]
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise AppError(
                "ERR_UPSTREAM",
                "gitleaks JSON 报告无法解析，发布已按 fail-closed 策略阻断。",
                fix_hint="检查 gitleaks 版本与配置后重试；本次未提交或推送。",
            ) from exc
        finally:
            report_path.unlink(missing_ok=True)


def _sanitize_finding(item: dict, root: Path) -> dict:
    file_value = str(item.get("File") or "")
    file_path = Path(file_value)
    if file_path.is_absolute():
        try:
            file_value = file_path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            file_value = file_path.name
    else:
        file_value = file_path.as_posix()
    return {
        "rule_id": str(item.get("RuleID") or "unknown"),
        "file": file_value,
        "line": int(item.get("StartLine") or 0),
    }
