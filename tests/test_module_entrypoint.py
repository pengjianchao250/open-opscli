"""opscli Python 模块入口回归测试。"""

import subprocess
import sys


def test_python_module_entrypoint_runs_cli_version():
    """`python -m opscli` 应转发到正式 Typer CLI。"""
    completed = subprocess.run(
        [sys.executable, "-m", "opscli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "opscli v" in completed.stdout
    assert "opscli.__main__" not in completed.stderr
