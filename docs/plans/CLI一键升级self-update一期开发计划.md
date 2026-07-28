# CLI 一键升级 self-update 一期开发计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 关联规划：`docs/plans/CLI与MCP更新机制治理规划与实施计划.md`（一期 T1-1 ~ T1-5）
> 文档日期：2026-07-16
> 状态：待执行

**Goal:** 新增 `opscli self-update` 一键升级命令（识别安装方式 → 升级 CLI → 自动同步 Skills），并把启动时的新版本提示从三条命令简化为一条。

**Architecture:** 新增 `opscli/shared/self_update.py` 承载全部升级逻辑（安装方式检测、升级命令构造、子进程编排三层纯函数 + 一个编排入口），`opscli/cli.py` 仅注册一个顶级命令薄壳。升级动作全部走子进程，不在当前进程内替换正在运行的 Cython 二进制代码。复用 `opscli/shared/update_check.py` 已有的 PyPI 版本查询与版本比较函数。

**Tech Stack:** Python >= 3.10、Typer、rich、httpx、pytest + respx + unittest.mock、typer.testing.CliRunner

## Global Constraints

以下约束对本计划所有任务生效（摘自项目 CLAUDE.md 铁律，值为原文照抄）：

- 测试禁止真实网络请求和真实 Keychain：网络用 `respx` mock，文件路径用 `tmp_path`（铁律8）
- 所有代码注释必须使用中文，公开方法必须有中文 docstring（铁律17）
- 终端输出字符必须 GBK 兼容：成功用 `√`（U+221A）、失败用 `×`（U+00D7），禁止 `✓` `✗` `✅` `❌` `⚠️` 及任何 emoji（铁律23）
- 只写解决问题所需的最少代码，不加未请求的参数/配置项（铁律20）；只改必须改的行，不美化邻里代码（铁律21）
- 每次 Edit/Write 修改代码后，必须向 `docs/change-log-pending.md` 追加变更记录（铁律18），本计划将该动作合并进每个任务的提交步骤
- 允许 `git commit` 到本地分支，**任何时候不 `git push`**（用户全局规范）
- 运行环境：项目内 uv 虚拟环境（`source .venv/bin/activate`），测试命令统一为 `pytest tests/shared/... -v`（铁律24）
- 回归基线：全量套件存在 23 个预存收集错误、`tests/mcp` 有 7 个预存失败，与本计划无关；本计划的回归范围限定为 `pytest tests/shared/ -v`，必须全绿
- 包名常量取 `opscli/version.py` 的 `PACKAGE_NAME = "aukeys-opscli"`，禁止硬编码字符串重复出现

## 文件结构总览

| 文件 | 动作 | 职责 |
|---|---|---|
| `opscli/shared/self_update.py` | 新建 | 安装方式检测、升级命令构造、self-update 编排 |
| `opscli/cli.py` | 修改 | 注册顶级 `self-update` 命令（约 +10 行） |
| `opscli/shared/update_check.py` | 修改 | `_print_update_hint()` 提示语简化（仅该函数） |
| `tests/shared/test_self_update.py` | 新建 | self_update 模块全部单测 |
| `tests/shared/test_update_check.py` | 修改 | 提示语断言从 `pip install` 改为 `self-update` |
| `docs/guide/CLI升级指南.md` | 新建 | 三种安装方式的升级操作文档 |
| `README.md` | 修改 | 安装/升级章节补充 self-update |
| `docs/change-log-pending.md` | 追加 | 每任务一条变更记录 |

---

### Task 1: 安装方式检测与升级命令构造（`detect_install_method` / `build_upgrade_command`）

**Files:**
- Create: `opscli/shared/self_update.py`
- Test: `tests/shared/test_self_update.py`

**Interfaces:**
- Consumes: `opscli/version.py` 的 `PACKAGE_NAME: str`（已存在，值 `"aukeys-opscli"`）
- Produces（Task 2 依赖）:
  - `detect_install_method(executable: str | None = None) -> str`，返回三个模块常量之一：`INSTALL_METHOD_UV_TOOL = "uv-tool"`、`INSTALL_METHOD_PIPX = "pipx"`、`INSTALL_METHOD_PIP = "pip"`
  - `build_upgrade_command(method: str) -> list[str]`，返回可直接传给 `subprocess.run` 的 argv

- [ ] **Step 1: 写失败测试**

新建 `tests/shared/test_self_update.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/mask/python3/opscli && source .venv/bin/activate
pytest tests/shared/test_self_update.py -v
```

预期：collection 阶段报 `ModuleNotFoundError: No module named 'opscli.shared.self_update'`（FAIL/ERROR）

- [ ] **Step 3: 写最小实现**

新建 `opscli/shared/self_update.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/shared/test_self_update.py -v
```

预期：9 个测试全部 PASS

- [ ] **Step 5: 追加变更记录并提交**

向 `docs/change-log-pending.md` 追加：

```markdown
## 2026-07-16 shared - 新增自升级模块：安装方式检测与升级命令构造

**变更原因**：一期升级体验优化（T1-1/T1-2），为 opscli self-update 命令提供实现层基础
**改动点**：新增 opscli/shared/self_update.py（detect_install_method + build_upgrade_command），pip 路径强制 --only-binary :all: 防源码编译退化
**验证结果**：pytest tests/shared/test_self_update.py -v 9 个测试全绿
**影响范围**：纯新增模块，不影响现有功能
**回滚方式**：删除 opscli/shared/self_update.py 与 tests/shared/test_self_update.py
---
```

```bash
git add opscli/shared/self_update.py tests/shared/test_self_update.py docs/change-log-pending.md
git commit -m "feat(shared): 新增自升级安装方式检测与升级命令构造"
```

---

### Task 2: 升级编排流程（`run_self_update`）

**Files:**
- Modify: `opscli/shared/self_update.py`（追加内容，不改 Task 1 已写代码）
- Test: `tests/shared/test_self_update.py`（追加测试类）

**Interfaces:**
- Consumes:
  - Task 1 的 `detect_install_method()` / `build_upgrade_command()`
  - `opscli/shared/update_check.py` 的 `_fetch_latest_version() -> str | None` 与 `is_newer_available(current: str, latest: str) -> bool`（同包内复用私有函数，避免重复实现版本查询）
  - `opscli/version.py` 的 `get_version() -> str`
- Produces（Task 3 依赖）: `run_self_update() -> int`，返回进程退出码，0 为成功

- [ ] **Step 1: 写失败测试**

向 `tests/shared/test_self_update.py` 追加（文件顶部 import 区补充 `from unittest.mock import MagicMock, patch` 和 `from opscli.shared.self_update import run_self_update`）：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/shared/test_self_update.py::TestRunSelfUpdate -v
```

预期：collection 报 `ImportError: cannot import name 'run_self_update'`

- [ ] **Step 3: 写最小实现**

向 `opscli/shared/self_update.py` 追加（import 区补充 `import platform`、`import shutil`、`import subprocess`、`from rich.console import Console`、`from opscli.shared.update_check import _fetch_latest_version, is_newer_available`、`from opscli.version import get_version`）：

```python
def _resolve_opscli_command() -> list[str]:
    """解析升级后执行 skills 同步所用的 opscli 命令前缀。

    优先用 PATH 中的 opscli 可执行文件（升级后其指向新版本代码）；
    找不到时回退为当前解释器直跑模块入口（等效 python -m opscli.cli）。
    """
    exe = shutil.which("opscli")
    if exe:
        return [exe]
    return [sys.executable, "-m", "opscli.cli"]


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
    console.print(f"[cyan]检测到安装方式: {method}，开始升级 v{current} → {target}[/cyan]")
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

    # 第三步：同步 Skills。必须用新进程执行，确保跑的是升级后的代码
    opscli_cmd = _resolve_opscli_command()
    for args in (["skills", "install", "--force"], ["skills", "upgrade"]):
        step = subprocess.run(opscli_cmd + args)
        if step.returncode != 0:
            console.print(
                f"[yellow]× CLI 已升级，但 `opscli {' '.join(args)}` 执行失败，"
                "请手动重试该命令[/yellow]"
            )
            return step.returncode

    console.print("[green]√ 升级完成：CLI 与 Skills 均已同步到最新版本[/green]")
    return 0
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/shared/test_self_update.py -v
```

预期：15 个测试全部 PASS（Task 1 的 9 个 + 本任务 6 个）

- [ ] **Step 5: 追加变更记录并提交**

向 `docs/change-log-pending.md` 追加：

```markdown
## 2026-07-16 shared - 新增 run_self_update 升级编排流程

**变更原因**：一期 T1-1，实现"升级 CLI + 自动同步 Skills"完整编排
**改动点**：opscli/shared/self_update.py 追加 run_self_update() 与 _resolve_opscli_command()；复用 update_check 的版本查询与比较
**验证结果**：pytest tests/shared/test_self_update.py -v 15 个测试全绿
**影响范围**：纯新增函数，未被任何入口调用（Task 3 接线）
**回滚方式**：回退本次 commit
---
```

```bash
git add opscli/shared/self_update.py tests/shared/test_self_update.py docs/change-log-pending.md
git commit -m "feat(shared): 新增 run_self_update 升级编排流程"
```

---

### Task 3: 注册顶级 `opscli self-update` 命令

**Files:**
- Modify: `opscli/cli.py`（在 `app.add_typer(mcp_app, name="mcp")` 之后、`def _get_current_user_email` 之前插入）
- Test: `tests/shared/test_self_update.py`（追加 CLI 层测试类）

**Interfaces:**
- Consumes: Task 2 的 `run_self_update() -> int`
- Produces: 用户可执行的 `opscli self-update` 命令，失败时退出码非 0

- [ ] **Step 1: 写失败测试**

向 `tests/shared/test_self_update.py` 追加（import 区补充 `from typer.testing import CliRunner`）：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/shared/test_self_update.py::TestCliCommand -v
```

预期：FAIL，`result.exit_code == 2`（Typer 报 "No such command 'self-update'"）

- [ ] **Step 3: 写最小实现**

修改 `opscli/cli.py`，在 `app.add_typer(mcp_app, name="mcp")` 一行之后追加：

```python
@app.command("self-update")
def self_update():
    """一键升级 opscli 并自动同步 Skills（等效于 pip 升级 + skills install/upgrade）。"""
    # 延迟导入：避免拖慢所有命令的启动耗时
    from opscli.shared.self_update import run_self_update

    code = run_self_update()
    if code != 0:
        raise typer.Exit(code)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/shared/test_self_update.py -v
```

预期：18 个测试全部 PASS。再做一次真机烟测（不打桩，验证命令注册与"已是最新"路径）：

```bash
opscli self-update
```

预期：因本地为开发版本（`0.0.139-dev` fallback 或已安装版本），输出版本预检结果后按流程执行或提示已是最新；命令不崩溃

- [ ] **Step 5: 追加变更记录并提交**

向 `docs/change-log-pending.md` 追加：

```markdown
## 2026-07-16 cli - 注册顶级 self-update 命令

**变更原因**：一期 T1-1，向用户暴露一键升级入口
**改动点**：opscli/cli.py 新增 @app.command("self-update")，薄壳调用 run_self_update 并透传退出码
**验证结果**：pytest tests/shared/test_self_update.py -v 18 个测试全绿；真机 opscli self-update 烟测通过
**影响范围**：新增顶级命令，不影响既有命令
**回滚方式**：回退本次 commit
---
```

```bash
git add opscli/cli.py tests/shared/test_self_update.py docs/change-log-pending.md
git commit -m "feat(cli): 注册 opscli self-update 一键升级命令"
```

---

### Task 4: 启动提示语简化（三条命令 → 一条）

**Files:**
- Modify: `opscli/shared/update_check.py:107-118`（仅 `_print_update_hint` 函数体）
- Modify: `tests/shared/test_update_check.py:197`（断言 `"pip install" in captured.err` 一行）

**Interfaces:**
- Consumes: Task 3 已注册的 `opscli self-update` 命令（提示文案指向它）
- Produces: 无新接口，仅文案变更

- [ ] **Step 1: 修改测试断言（先让测试表达新预期）**

修改 `tests/shared/test_update_check.py` 中 `test_cache_hit_with_update` 的最后一行断言：

```python
            # 旧断言：assert "pip install" in captured.err
            assert "opscli self-update" in captured.err
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/shared/test_update_check.py::TestCheckAndNotify::test_cache_hit_with_update -v
```

预期：FAIL，stderr 中尚无 `opscli self-update` 字样

- [ ] **Step 3: 修改实现**

修改 `opscli/shared/update_check.py` 的 `_print_update_hint`，将三条命令提示替换为一条：

```python
def _print_update_hint(current: str, latest: str) -> None:
    """输出更新提示到 stderr，不干扰 stdout 的正常输出。"""
    console = Console(stderr=True)
    console.print()
    console.print(
        f"[yellow]opscli 有新版本可用，建议更新最新版本: v{current} → v{latest}[/yellow]"
    )
    console.print("[dim]请运行以下命令一键更新（升级 CLI 并自动同步 Skills）：[/dim]")
    console.print("[cyan]  opscli self-update[/cyan]")
    console.print()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/shared/test_update_check.py -v
```

预期：全部 PASS（其余用例不受影响）

- [ ] **Step 5: 追加变更记录并提交**

向 `docs/change-log-pending.md` 追加：

```markdown
## 2026-07-16 shared - 版本更新提示语简化为 self-update 单命令

**变更原因**：一期 T1-3，升级提示从三条手动命令简化为一条一键命令，降低升级摩擦
**改动点**：opscli/shared/update_check.py 的 _print_update_hint 文案；tests/shared/test_update_check.py 对应断言
**验证结果**：pytest tests/shared/test_update_check.py -v 全绿
**影响范围**：仅启动时 stderr 提示文案
**回滚方式**：回退本次 commit
---
```

```bash
git add opscli/shared/update_check.py tests/shared/test_update_check.py docs/change-log-pending.md
git commit -m "feat(shared): 版本更新提示简化为 opscli self-update 单命令"
```

---

### Task 5: 用户文档（升级指南 + README）

**Files:**
- Create: `docs/guide/CLI升级指南.md`
- Modify: `README.md`（安装/升级相关章节，若无升级章节则新增）
- Modify: `CLAUDE.md`（"文档索引"表格追加一行）

**Interfaces:**
- Consumes: Task 1–4 的最终命令行为
- Produces: 无代码接口，交付文档

- [ ] **Step 1: 新建升级指南**

新建 `docs/guide/CLI升级指南.md`：

```markdown
# CLI 升级指南

> 适用版本：aukeys-opscli >= 0.0.140
> 文档日期：2026-07-16

## 一键升级（推荐）

```bash
opscli self-update
```

该命令自动完成三件事：

1. 识别当前安装方式（uv tool / pipx / pip），执行对应升级命令
2. 升级完成后自动执行 `opscli skills install --force`（刷新内置 Skill 模板）
3. 自动执行 `opscli skills upgrade`（拉取远端最新 Skill 数据）

已是最新版本时输出 `√ 已是最新版本` 并直接退出，可放心重复执行。

## 手动升级（备用）

按你的安装方式选择其一：

| 安装方式 | 升级命令 |
|---|---|
| uv tool | `uv tool upgrade aukeys-opscli` |
| pipx | `pipx upgrade aukeys-opscli` |
| pip | `pip install --upgrade --only-binary :all: aukeys-opscli` |

手动升级后必须补两条命令：

```bash
opscli skills install --force
opscli skills upgrade
```

## 常见问题

### 提示找不到二进制包（no matching distribution / wheel）

opscli 以预编译二进制 wheel 分发（不支持源码编译安装）。出现该提示说明
当前平台或 Python 版本暂未提供预编译包，请将 `opscli self-update` 输出的
平台信息（系统 / 架构 / Python 版本）反馈给维护者。

### 升级成功但 skills 同步失败

CLI 本体已是新版本，只需手动重试失败的那条命令：

```bash
opscli skills install --force   # 或 opscli skills upgrade
```

### 如何确认升级成功

```bash
opscli --version
```
```

- [ ] **Step 2: 更新 README 与 CLAUDE.md 文档索引**

`README.md` 安装章节之后补充（若已有升级说明则替换为以下内容）：

```markdown
## 升级

```bash
opscli self-update
```

一条命令完成 CLI 升级与 Skills 同步。详见 [docs/guide/CLI升级指南.md](docs/guide/CLI升级指南.md)。
```

`CLAUDE.md` 的"文档索引"表格追加一行：

```markdown
| 使用指南 | CLI 升级指南               | `docs/guide/CLI升级指南.md`                 |
```

- [ ] **Step 3: 验证文档**

```bash
ls docs/guide/CLI升级指南.md && grep -n "self-update" README.md CLAUDE.md
```

预期：文件存在；README 与 CLAUDE.md 均能 grep 到 self-update

- [ ] **Step 4: 提交**

```bash
git add docs/guide/CLI升级指南.md README.md CLAUDE.md
git commit -m "docs: 新增 CLI 升级指南并更新 README 升级说明"
```

---

### Task 6: 回归验证与发版真机验收

**Files:**
- 无代码改动，验证性任务

**Interfaces:**
- Consumes: Task 1–5 全部产出

- [ ] **Step 1: 范围内回归**

```bash
pytest tests/shared/ -v
```

预期：全部 PASS（0 failed）。注意：不跑全量套件，全量存在 23 个与本计划无关的预存收集错误（见 Global Constraints 回归基线）

- [ ] **Step 2: 本地真机烟测清单**

```bash
opscli --help              # 预期：命令列表含 self-update
opscli self-update         # 预期：走完整流程或提示"已是最新"，退出码 0
echo $?
```

- [ ] **Step 3: 发版与旧版本升级闭环验证（需用户确认后执行）**

此步骤涉及打 tag 触发 CI 发版（外部动作），**执行前需向用户确认**：

1. `pyproject.toml` 版本号 bump（如 0.0.139 → 0.0.140），提交
2. 打 tag：`git tag v0.0.140`（push 由用户执行，AI 不做 push）
3. CI 发布成功后，在装有旧版本的 macOS 与 Windows 真机各执行一次 `opscli self-update`
4. 验收标准：旧版 → 新版一键完成，`opscli --version` 显示新版本，skills 两条同步命令自动执行成功

- [ ] **Step 4: 收尾归档**

确认 `docs/change-log-pending.md` 含 Task 1–4 的四条记录；若记忆服务（memory-lancedb-pro-sse）已恢复，按规范补写 `memory_store`（decision + fact 各一条，projectName=opscli）

---

## Self-Review 结论

- **规格覆盖**：治理规划一期 T1-1（Task 1/2/3）、T1-2（Task 1 的 --only-binary + Task 2 的失败指引）、T1-3（Task 4）、T1-4（测试内嵌各任务 + Task 5 文档）、T1-5（Task 6 Step 3）全部有对应任务
- **占位符检查**：所有代码步骤均含完整可落地代码，无 TBD/TODO
- **类型一致性**：`run_self_update() -> int` 在 Task 2 定义、Task 3 消费一致；`detect_install_method` / `build_upgrade_command` 签名在 Task 1 定义后未变；`PACKAGE_NAME`、`get_version`、`_fetch_latest_version`、`is_newer_available` 均为现存代码实名引用（已核对 `opscli/version.py`、`opscli/shared/update_check.py`）
- **已知取舍**：复用 `update_check._fetch_latest_version` 私有函数属同包内复用，避免重复实现（铁律20 DRY 优先于封装洁癖）；`self-update` 执行时主回调会先跑一次 `check_and_notify`，因 24h 缓存存在，重复网络开销可忽略
