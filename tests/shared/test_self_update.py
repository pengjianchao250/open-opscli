"""自升级模块测试。

全部测试不发真实网络请求、不执行真实子进程（铁律8）：
路径检测为纯函数直接断言，编排流程用 unittest.mock 打桩。
"""

import sys
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from opscli.shared.self_update import (
    INSTALL_METHOD_PIP,
    INSTALL_METHOD_PIPX,
    INSTALL_METHOD_UV_TOOL,
    build_upgrade_command,
    detect_install_method,
    run_self_update,
)


class TestDetectInstallMethod:
    """安装方式检测测试：仅依据解释器路径特征判断。"""

    def test_uv_tool_macos_path(self):
        """macOS 上 uv tool 虚拟环境路径含 /uv/tools/。"""
        path = "/Users/a/.local/share/uv/tools/aukeys-opscli/bin/python"
        assert detect_install_method(path) == INSTALL_METHOD_UV_TOOL

    def test_uv_tool_windows_path(self):
        """Windows 反斜杠路径同样能识别 uv tool。"""
        path = "C:\\Users\\a\\AppData\\Roaming\\uv\\tools\\aukeys-opscli\\Scripts\\python.exe"
        assert detect_install_method(path) == INSTALL_METHOD_UV_TOOL

    def test_pipx_path(self):
        """pipx 虚拟环境路径含 /pipx/venvs/。"""
        path = "/Users/a/.local/pipx/venvs/aukeys-opscli/bin/python"
        assert detect_install_method(path) == INSTALL_METHOD_PIPX

    def test_plain_venv_falls_back_to_pip(self):
        """普通项目 venv 不命中特征，按 pip 安装处理。"""
        path = "/Users/a/project/.venv/bin/python"
        assert detect_install_method(path) == INSTALL_METHOD_PIP

    def test_global_python_falls_back_to_pip(self):
        """系统全局 Python 同样按 pip 处理。"""
        assert detect_install_method("/usr/local/bin/python3") == INSTALL_METHOD_PIP

    def test_default_reads_sys_executable(self, monkeypatch):
        """不传参数时默认读取 sys.executable。"""
        monkeypatch.setattr(
            sys, "executable", "/x/uv/tools/aukeys-opscli/bin/python"
        )
        assert detect_install_method() == INSTALL_METHOD_UV_TOOL


class TestBuildUpgradeCommand:
    """升级命令构造测试。"""

    def test_uv_tool_command(self):
        """uv tool 安装走 uv tool upgrade。"""
        assert build_upgrade_command(INSTALL_METHOD_UV_TOOL) == [
            "uv", "tool", "upgrade", "aukeys-opscli",
        ]

    def test_pipx_command(self):
        """pipx 安装走 pipx upgrade。"""
        assert build_upgrade_command(INSTALL_METHOD_PIPX) == [
            "pipx", "upgrade", "aukeys-opscli",
        ]

    def test_pip_command_forces_only_binary(self):
        """pip 路径必须带 --only-binary :all:，防止退化为源码编译。"""
        command = build_upgrade_command(INSTALL_METHOD_PIP)
        assert command[0] == sys.executable
        assert command[1:4] == ["-m", "pip", "install"]
        assert "--upgrade" in command
        assert "--only-binary" in command
        # --only-binary 的值必须是 :all:，且紧跟在标志之后
        assert command[command.index("--only-binary") + 1] == ":all:"
        assert command[-1] == "aukeys-opscli"


class TestRunSelfUpdate:
    """升级编排流程测试：subprocess 与版本查询全部打桩。"""

    def _mock_run_factory(self, returncodes: list[int]):
        """构造按调用顺序返回指定退出码的 subprocess.run 桩函数。"""
        results = [MagicMock(returncode=code) for code in returncodes]
        mock = MagicMock(side_effect=results)
        return mock

    def test_already_latest_skips_everything(self, capsys):
        """已是最新版本：输出提示、返回 0、不执行任何子进程。"""
        with (
            patch("opscli.shared.self_update.get_version", return_value="0.0.139"),
            patch("opscli.shared.self_update._fetch_latest_version", return_value="0.0.139"),
            patch("opscli.shared.self_update.subprocess.run") as mock_run,
        ):
            assert run_self_update() == 0
            mock_run.assert_not_called()
            assert "已是最新" in capsys.readouterr().out

    def test_full_success_runs_upgrade_then_skills(self, capsys):
        """正常升级：依次执行 升级命令 → skills install --force → skills upgrade。"""
        mock_run = self._mock_run_factory([0, 0, 0])
        with (
            patch("opscli.shared.self_update.get_version", return_value="0.0.139"),
            patch("opscli.shared.self_update._fetch_latest_version", return_value="0.0.200"),
            patch("opscli.shared.self_update.subprocess.run", mock_run),
            patch("opscli.shared.self_update.shutil.which", return_value="/usr/local/bin/opscli"),
        ):
            assert run_self_update() == 0
        assert mock_run.call_count == 3
        # 第 1 次调用是升级命令（pip 路径，因测试环境不命中 uv/pipx 特征）
        first_argv = mock_run.call_args_list[0].args[0]
        assert "--only-binary" in first_argv
        # 第 2、3 次调用是 skills 同步，走 PATH 中解析到的 opscli 可执行文件
        assert mock_run.call_args_list[1].args[0] == [
            "/usr/local/bin/opscli", "skills", "install", "--force",
        ]
        assert mock_run.call_args_list[2].args[0] == [
            "/usr/local/bin/opscli", "skills", "upgrade",
        ]
        assert "√ 升级完成" in capsys.readouterr().out

    def test_upgrade_failure_stops_and_reports_platform(self, capsys):
        """升级命令失败：返回其退出码、不执行 skills 同步、输出平台信息。"""
        mock_run = self._mock_run_factory([1])
        with (
            patch("opscli.shared.self_update.get_version", return_value="0.0.139"),
            patch("opscli.shared.self_update._fetch_latest_version", return_value="0.0.200"),
            patch("opscli.shared.self_update.subprocess.run", mock_run),
        ):
            assert run_self_update() == 1
        assert mock_run.call_count == 1
        output = capsys.readouterr().out
        assert "× 升级失败" in output
        assert "Python" in output  # 平台信息帮助定位 wheel 缺失问题

    def test_skills_step_failure_returns_code_with_hint(self, capsys):
        """CLI 升级成功但 skills 同步失败：返回失败码并提示手动重试。"""
        mock_run = self._mock_run_factory([0, 1])
        with (
            patch("opscli.shared.self_update.get_version", return_value="0.0.139"),
            patch("opscli.shared.self_update._fetch_latest_version", return_value="0.0.200"),
            patch("opscli.shared.self_update.subprocess.run", mock_run),
            patch("opscli.shared.self_update.shutil.which", return_value="/usr/local/bin/opscli"),
        ):
            assert run_self_update() == 1
        assert mock_run.call_count == 2
        # 断言失败的是第二步（skills install --force），锁定步骤顺序
        assert mock_run.call_args_list[1].args[0] == [
            "/usr/local/bin/opscli", "skills", "install", "--force",
        ]
        assert "手动重试" in capsys.readouterr().out

    def test_fetch_failure_still_attempts_upgrade(self, capsys):
        """版本查询失败（网络不可达）：不阻断，仍尝试执行升级。"""
        mock_run = self._mock_run_factory([0, 0, 0])
        with (
            patch("opscli.shared.self_update.get_version", return_value="0.0.139"),
            patch("opscli.shared.self_update._fetch_latest_version", return_value=None),
            patch("opscli.shared.self_update.subprocess.run", mock_run),
            patch("opscli.shared.self_update.shutil.which", return_value="/usr/local/bin/opscli"),
        ):
            assert run_self_update() == 0
        assert mock_run.call_count == 3

    def test_opscli_not_in_path_falls_back_to_module(self):
        """PATH 找不到 opscli 时，回退为当前解释器直跑模块入口。"""
        mock_run = self._mock_run_factory([0, 0, 0])
        with (
            patch("opscli.shared.self_update.get_version", return_value="0.0.139"),
            patch("opscli.shared.self_update._fetch_latest_version", return_value="0.0.200"),
            patch("opscli.shared.self_update.subprocess.run", mock_run),
            patch("opscli.shared.self_update.shutil.which", return_value=None),
        ):
            assert run_self_update() == 0
        assert mock_run.call_args_list[1].args[0] == [
            sys.executable, "-m", "opscli.cli", "skills", "install", "--force",
        ]


class TestCliCommand:
    """CLI 命令注册测试：通过 CliRunner 走完整 Typer 链路。

    主回调中的版本检查与遥测均需打桩，避免测试发真实网络请求（铁律8）。
    """

    def _invoke(self, run_self_update_code: int):
        """打桩后执行 opscli self-update，返回 CliRunner 结果。"""
        from opscli.cli import app

        with (
            patch("opscli.shared.update_check.check_and_notify"),
            patch("opscli.telemetry.reporter.TelemetryReporter.fire"),
            patch(
                "opscli.shared.self_update.run_self_update",
                return_value=run_self_update_code,
            ) as mock_update,
        ):
            result = CliRunner().invoke(app, ["self-update"])
        return result, mock_update

    def test_success_exit_zero(self):
        """run_self_update 返回 0 时命令退出码为 0。"""
        result, mock_update = self._invoke(0)
        assert result.exit_code == 0
        mock_update.assert_called_once()

    def test_failure_propagates_exit_code(self):
        """run_self_update 返回非 0 时命令退出码透传。"""
        result, _ = self._invoke(1)
        assert result.exit_code == 1

    def test_help_lists_command(self):
        """opscli --help 中能看到 self-update 命令。"""
        from opscli.cli import app

        with (
            patch("opscli.shared.update_check.check_and_notify"),
            patch("opscli.telemetry.reporter.TelemetryReporter.fire"),
        ):
            result = CliRunner().invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "self-update" in result.output
