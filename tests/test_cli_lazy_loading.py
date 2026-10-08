"""CLI 子命令懒加载回归测试。

守护 docs/plans/CLI子命令懒加载方案.md 的验收标准：
① -V / --help 不导入任何子命令模块
② 单个子命令只导入自身依赖
③ --help 文案与懒加载前的现状快照逐字一致
④ 注册表 help 与子模块 typer.Typer(help=...) 逐字一致
⑤ asin-review 缺包时不列出
⑥ 输错命令名的 "Did you mean" 建议覆盖懒加载子命令
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

import opscli.cli
from opscli.cli import _SUBCOMMANDS, app

REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _newly_loaded_opscli_modules() -> set[str]:
    """返回当前 sys.modules 中 opscli 模块名的完整快照。"""
    return {
        m
        for m in sys.modules
        if m == "opscli" or m.startswith("opscli.")
    }


def _subcommand_module_paths() -> set[str]:
    return {module_path for _name, module_path, _help in _SUBCOMMANDS}


# ---------- ① -V / --help 不导入任何子命令模块 ----------

@pytest.mark.parametrize("argv", [["-V"], ["--help"]])
def test_lightweight_commands_do_not_import_subcommands(argv):
    before = _newly_loaded_opscli_modules()
    result = runner.invoke(app, argv)
    assert result.exit_code == 0
    newly = _newly_loaded_opscli_modules() - before
    loaded_subcommands = newly & _subcommand_module_paths()
    assert not loaded_subcommands, f"轻量命令不应导入子命令模块: {sorted(loaded_subcommands)}"


# ---------- ② 单个子命令只导入自身依赖 ----------

def test_single_subcommand_loads_only_itself():
    before = _newly_loaded_opscli_modules()
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    # 全量测试下 opscli.auth.cli 可能已被其他用例导入，只断言"调用后已加载"
    assert "opscli.auth.cli" in sys.modules, "应加载被调用的子命令自身"
    newly = _newly_loaded_opscli_modules() - before
    others = (newly & _subcommand_module_paths()) - {"opscli.auth.cli"}
    assert not others, f"不应加载无关子命令模块: {sorted(others)}"


# ---------- ③ --help 文案与现状快照逐字一致 ----------

def test_help_output_matches_snapshot():
    env = {k: v for k, v in os.environ.items() if k != "COLUMNS"}
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "opscli", "--help"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    snapshot = (
        REPO_ROOT / "tests" / "test_cli_lazy_loading_help_snapshot.txt"
    ).read_text(encoding="utf-8")
    # Rich 会按当前命令表宽度调整行尾填充空格；快照只比较可见内容，
    # 避免新增命令或终端宽度变化造成无意义的空白差异。
    def normalize(text: str) -> str:
        return "\n".join(line.rstrip() for line in text.splitlines())

    assert normalize(result.stdout) == normalize(snapshot), (
        "opscli --help 输出与懒加载前快照不一致"
    )


# ---------- ④ 注册表 help 与子模块 typer.Typer(help=...) 一致 ----------

@pytest.mark.parametrize("name,module_path,help_text", _SUBCOMMANDS)
def test_registry_help_matches_submodule(name, module_path, help_text):
    import importlib

    import typer

    module = importlib.import_module(module_path)
    real_group = typer.main.get_group(module.app)
    assert real_group.help == help_text, (
        f"注册表中 {name} 的 help 与 {module_path} 的 typer.Typer(help=...) 不一致，"
        f"请同步 opscli/cli.py 的 _SUBCOMMANDS 注册表"
    )


# ---------- ⑤ asin-review 缺包时不列出 ----------

def test_missing_optional_subcommand_not_listed(monkeypatch):
    monkeypatch.setattr(
        opscli.cli, "_is_subcommand_available", lambda name: name != "asin-review"
    )
    # 可用性在 Group 构造时消费，需在补丁生效后构造新实例
    group = opscli.cli.LazyTyperGroup(name="test")
    assert "asin-review" not in group.list_commands(None)
    assert group.get_command(None, "asin-review") is None
    assert "auth" in group.list_commands(None)


# ---------- ⑥ typo 建议覆盖懒加载子命令 ----------

def test_typo_suggestion_includes_lazy_commands():
    result = runner.invoke(app, ["ath"])
    assert result.exit_code != 0
    assert "Did you mean 'auth'?" in result.output
