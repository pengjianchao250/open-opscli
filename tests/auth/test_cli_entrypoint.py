"""验证顶级 CLI 能加载认证命令入口。"""

from __future__ import annotations

import subprocess
import sys


def test_root_cli_imports_for_auth_entrypoint() -> None:
    """顶级 CLI 应能完成导入，以便认证命令正常启动。"""
    result = subprocess.run(
        [sys.executable, "-c", "from opscli.cli import app"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
