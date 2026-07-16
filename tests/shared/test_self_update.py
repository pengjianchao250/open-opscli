"""自升级模块测试。

全部测试不发真实网络请求、不执行真实子进程（铁律8）：
路径检测为纯函数直接断言，编排流程用 unittest.mock 打桩。
"""

import sys

from opscli.shared.self_update import (
    INSTALL_METHOD_PIP,
    INSTALL_METHOD_PIPX,
    INSTALL_METHOD_UV_TOOL,
    build_upgrade_command,
    detect_install_method,
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
