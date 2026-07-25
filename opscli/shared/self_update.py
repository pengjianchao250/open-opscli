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

import platform
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from opscli.shared.update_check import _fetch_latest_version, _get_channel, is_newer_available
from opscli.version import PACKAGE_NAME, get_version

# 安装方式常量：检测结果只会是这三种之一
INSTALL_METHOD_UV_TOOL = "uv-tool"
INSTALL_METHOD_PIPX = "pipx"
INSTALL_METHOD_PIP = "pip"

# test 渠道的 pip 源：主源指向 TestPyPI，公网 PyPI 作为兜底源解析依赖
# （typer/httpx 等依赖不在 TestPyPI 上，缺少兜底源会导致全新环境安装失败）
_TESTPYPI_INDEX_URL = "https://test.pypi.org/simple/"
_PYPI_INDEX_URL = "https://pypi.org/simple/"


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
    command = [
        sys.executable, "-m", "pip", "install",
        "--upgrade", "--only-binary", ":all:",
    ]
    # test 渠道（内部发版验证）：切换到 TestPyPI 源；uv tool / pipx
    # 路径不支持测试渠道，内部验证统一走 pip 环境
    if _get_channel() == "test":
        command += [
            "--index-url", _TESTPYPI_INDEX_URL,
            "--extra-index-url", _PYPI_INDEX_URL,
        ]
    command.append(PACKAGE_NAME)
    return command


def _resolve_opscli_command() -> list[str]:
    """解析升级后执行 skills 同步所用的 opscli 命令前缀。

    必须优先取当前解释器同目录下的 opscli 可执行文件：升级发生在
    当前解释器所在环境，而 PATH 上的 opscli 可能属于另一个 Python
    环境（e2e 实测踩坑：PATH 优先曾解析到开发 venv，导致 skills
    同步跑错环境、用了旧版代码）。同目录找不到时回退为当前解释器
    直跑模块入口（等效 python -m opscli.cli）。
    """
    bin_dir = Path(sys.executable).parent
    # macOS/Linux 为 opscli，Windows 为 opscli.exe
    for name in ("opscli", "opscli.exe"):
        candidate = bin_dir / name
        if candidate.exists():
            return [str(candidate)]
    return [sys.executable, "-m", "opscli.cli"]


def _read_installed_version(opscli_cmd: list[str]) -> str | None:
    """通过子进程读取升级后环境中的 opscli 版本号。

    输出形如 "opscli v0.0.141"，解析失败或执行异常均返回 None
    （版本校验是尽力而为的增强，不因它阻断主流程）。
    """
    try:
        result = subprocess.run(
            opscli_cmd + ["--version"],
            capture_output=True, text=True, timeout=30,
        )
        text = (result.stdout or "").strip()
        # 取最后一个 "v" 之后的部分作为版本号
        if "v" in text:
            return text.rsplit("v", 1)[-1].strip()
    except Exception:
        pass
    return None


def run_self_update() -> int:
    """执行完整自升级流程：版本预检 → 升级 CLI → 同步 Skills。

    Returns:
        进程退出码，0 为成功；升级或 skills 同步失败时透传子进程退出码。
    """
    console = Console()
    current = get_version()

    # 第一步：版本预检。已是最新则直接跳过，避免无意义的升级动作；
    # 查询失败（返回 None，如离线）不阻断，交给包管理器自行判断
    latest = _fetch_latest_version()
    if latest is not None and not is_newer_available(current, latest):
        console.print(f"[green]√ 已是最新版本 v{current}，无需升级[/green]")
        return 0

    # 第二步：识别安装方式并执行升级（子进程继承终端，实时展示进度）
    method = detect_install_method()
    target = f"v{latest}" if latest else "最新版本"
    # test 渠道显式标注，方便发版验证时确认走的是 TestPyPI
    channel_note = "（测试渠道 TestPyPI）" if _get_channel() == "test" else ""
    console.print(
        f"[cyan]检测到安装方式: {method}{channel_note}，开始升级 v{current} → {target}[/cyan]"
    )
    result = subprocess.run(build_upgrade_command(method))
    if result.returncode != 0:
        # 升级失败：附平台信息帮助定位 wheel 缺失类问题（T1-2 防护）
        console.print(f"[red]× 升级失败（退出码 {result.returncode}）[/red]")
        console.print(
            f"[dim]当前平台: {platform.system()} {platform.machine()} / "
            f"Python {platform.python_version()}[/dim]"
        )
        console.print(
            "[dim]若提示找不到二进制包（wheel），说明当前平台/Python 版本"
            "暂未提供预编译包，请联系维护者[/dim]"
        )
        return result.returncode

    # 第三步：校验升级结果。pip 在源缓存延迟等场景下会输出
    # already satisfied 并返回 0 但实际未升级，必须如实告知用户
    opscli_cmd = _resolve_opscli_command()
    installed = _read_installed_version(opscli_cmd)
    if installed is not None:
        console.print(f"[dim]升级后版本: v{installed}[/dim]")
        if latest is not None and is_newer_available(installed, latest):
            console.print(
                f"[yellow][!] 升级命令已执行，但当前版本 v{installed} "
                f"仍低于目标 v{latest}，可能是安装源缓存延迟，请稍后重试[/yellow]"
            )
            return 1

    # 第四步：同步 Skills。必须用新进程执行，确保跑的是升级后的代码；
    # install 带 --yes 跳过交互式 TUI 选择（e2e 实测无 --yes 会阻塞在选择提示）
    for args in (["skills", "install", "--force", "--yes"], ["skills", "upgrade"]):
        step = subprocess.run(opscli_cmd + args)
        if step.returncode != 0:
            console.print(
                f"[yellow]× CLI 已升级，但 `opscli {' '.join(args)}` 执行失败，"
                "请手动重试该命令[/yellow]"
            )
            return step.returncode

    console.print("[green]√ 升级完成：CLI 与 Skills 均已同步到最新版本[/green]")
    return 0
