"""opscli 自升级模块（opscli self-update 命令的实现层）。

职责分三层：
1. detect_install_method()  —— 识别当前 opscli 的安装方式（uv tool / pipx / pip）
2. build_upgrade_command()  —— 构造对应安装方式的升级命令 argv
3. run_self_update()        —— 编排完整升级流程（Task 2 实现）

设计约束：
- 终端输出仅使用 GBK 安全字符（铁律23），成功用 √、失败用 ×
- 升级动作全部通过子进程执行，避免在当前进程内替换
  正在运行的 Cython 二进制代码产生未定义行为
"""

from __future__ import annotations

import sys

from opscli.version import PACKAGE_NAME

# 安装方式常量：检测结果只会是这三种之一
INSTALL_METHOD_UV_TOOL = "uv-tool"
INSTALL_METHOD_PIPX = "pipx"
INSTALL_METHOD_PIP = "pip"


def detect_install_method(executable: str | None = None) -> str:
    """依据解释器路径特征识别安装方式。

    uv tool 的虚拟环境固定位于 .../uv/tools/<包名>/ 下，
    pipx 的虚拟环境固定位于 .../pipx/venvs/<包名>/ 下，
    两者都不命中时按普通 pip 安装处理（覆盖项目 venv 与全局 site-packages）。

    Args:
        executable: 供测试注入的解释器路径，默认取 sys.executable。

    Returns:
        INSTALL_METHOD_UV_TOOL / INSTALL_METHOD_PIPX / INSTALL_METHOD_PIP 之一。
    """
    # Windows 路径统一转正斜杠后再做特征匹配，避免双份判断逻辑
    path = (executable or sys.executable).replace("\\", "/")
    if "/uv/tools/" in path:
        return INSTALL_METHOD_UV_TOOL
    if "/pipx/venvs/" in path:
        return INSTALL_METHOD_PIPX
    return INSTALL_METHOD_PIP


def build_upgrade_command(method: str) -> list[str]:
    """构造对应安装方式的升级命令 argv，可直接传给 subprocess.run。

    pip 路径强制 --only-binary :all:：本包为 Cython 编译 wheel，
    源码编译在用户机器上大概率失败（需要完整编译工具链），
    宁可快速失败并给出指引，也不让用户进入漫长编译后再报错。

    Args:
        method: detect_install_method() 的返回值。
    """
    if method == INSTALL_METHOD_UV_TOOL:
        return ["uv", "tool", "upgrade", PACKAGE_NAME]
    if method == INSTALL_METHOD_PIPX:
        return ["pipx", "upgrade", PACKAGE_NAME]
    # pip 路径：用当前解释器的 pip，保证装进 opscli 所在环境而非别的 Python
    return [
        sys.executable, "-m", "pip", "install",
        "--upgrade", "--only-binary", ":all:", PACKAGE_NAME,
    ]
