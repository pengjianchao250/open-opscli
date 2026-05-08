"""Skills CLI 子命令定义。

注册到 opscli 顶级命令下，提供 skills list/install/status/upgrade 四个子命令。
所有命令输出统一 JSON 格式，方便脚本解析。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from opscli.skills.domain.exceptions import error_to_dict
from opscli.skills.services.manager import SkillsManager
from opscli.skills.services.rule_injector import RuleInjector

app = typer.Typer(help="Skill 生命周期管理")
_console = Console()

_TOOL_LABELS = {
    "claude":   "Claude Code",
    "openclaw": "OpenClaw",
    "codex":    "Codex CLI",
    "opencode": "OpenCode",
}

_AMAZON_RUFUS_SKILL_NAME = "ops-amazon-rufus"
_AMAZON_RUFUS_NEXT_STEPS = [
    "使用前必须先登录对应国家站点的 Amazon 账户。",
    "请先执行 opscli amazon-rufus init <country>，在新窗口完成登录。",
    "登录后再执行 opscli amazon-rufus get <asin> <country> --new-chrome。",
]


def _emit(payload: dict, pretty: bool) -> None:
    """统一的 JSON 输出函数，控制是否美化格式。"""
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _with_post_install_guidance(data: dict, skill_name: str) -> dict:
    """为特定 Skill 追加安装后指引，避免污染通用安装模型。"""
    if skill_name != _AMAZON_RUFUS_SKILL_NAME:
        return data
    guided = dict(data)
    guided["requires_amazon_login"] = True
    guided["next_steps"] = list(_AMAZON_RUFUS_NEXT_STEPS)
    return guided


def _parse_multiselect(answer: str, total: int) -> list[int]:
    """将逗号分隔的编号字符串解析为 1-based 索引列表（空字符串返回全选）。"""
    if not answer.strip():
        return list(range(1, total + 1))
    indexes: list[int] = []
    for part in answer.split(","):
        normalized = part.strip()
        if not normalized:
            continue
        if not normalized.isdigit():
            raise ValueError(f"无效的编号: {normalized!r}")
        idx = int(normalized)
        if idx < 1 or idx > total:
            raise ValueError(f"编号 {idx} 超出范围（1~{total}）")
        indexes.append(idx)
    return indexes or list(range(1, total + 1))


def _tui_select_skills(manager: SkillsManager) -> list[str]:
    """TUI：展示内置 Skill 列表，用户选择要安装哪些。返回选中的 skill 名称列表。"""
    templates = manager.list_templates()
    if not templates:
        raise ValueError("未找到任何内置 Skill 模板")

    # 根据总数动态计算序号列宽，避免两位数以上被截断
    idx_width = max(3, len(str(len(templates))) + 2)
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("#", style="bold yellow", width=idx_width)
    table.add_column("名称", style="green", min_width=20)
    table.add_column("版本", style="dim", width=8)
    table.add_column("说明")
    for idx, tmpl in enumerate(templates, start=1):
        table.add_row(f"[{idx}]", tmpl["name"], tmpl["version"], tmpl["description"])

    _console.print(Panel(table, title="[bold]可安装的 Skills[/bold]", border_style="blue"))

    answer = typer.prompt(
        "请选择要安装的 Skills（逗号分隔编号，直接回车安装全部）",
        default="",
        show_default=False,
    )
    selected_indexes = _parse_multiselect(answer, len(templates))
    return [templates[i - 1]["name"] for i in selected_indexes]


def _tui_select_targets(manager: SkillsManager) -> list[tuple[str, Path]] | None:
    """TUI：展示全局检测到的工具列表，用户选择安装到哪些工具。

    使用 detect_global_install_targets() 按 ~/.claude/、which claude 等规则检测，
    而非项目级 CWD 目录。

    返回选中的 [(runtime, skills_dir), ...] 列表；未检测到任何工具时返回 None。
    """
    targets = manager.detector.detect_global_install_targets()
    if not targets:
        return None

    idx_width = max(3, len(str(len(targets))) + 2)
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("#", style="bold yellow", width=idx_width)
    table.add_column("工具", style="green", min_width=14)
    table.add_column("安装路径", style="dim")
    for idx, (runtime, path) in enumerate(targets, start=1):
        label = _TOOL_LABELS.get(runtime, runtime)
        table.add_row(f"[{idx}]", label, str(path))

    _console.print(Panel(table, title="[bold]检测到的安装目标[/bold]", border_style="blue"))

    answer = typer.prompt(
        "请选择安装目标（逗号分隔编号，直接回车安装全部）",
        default="",
        show_default=False,
    )
    selected_indexes = _parse_multiselect(answer, len(targets))
    return [targets[i - 1] for i in selected_indexes]


def _resolve_install_runtime(
    manager: SkillsManager,
    *,
    runtime: str | None,
    skills_dir: str | None,
) -> str | list[str] | None:
    """在单 Skill 安装场景下解析目标 runtime（复用原有逻辑）。"""
    if runtime or skills_dir:
        return runtime

    detector = getattr(manager, "detector", None)
    if detector is None:
        return runtime
    targets = detector.detect_available_install_targets(cwd=Path.cwd())
    if not targets:
        return runtime

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("#", style="bold yellow", width=3)
    table.add_column("工具", style="green", min_width=14)
    table.add_column("安装路径", style="dim")
    for idx, (target_runtime, target_path) in enumerate(targets, start=1):
        label = _TOOL_LABELS.get(target_runtime, target_runtime)
        table.add_row(f"[{idx}]", label, str(target_path))

    _console.print(Panel(table, title="[bold]检测到的安装目标[/bold]", border_style="blue"))

    answer = typer.prompt(
        "请选择安装目标（逗号分隔编号，直接回车安装全部）",
        default="",
        show_default=False,
    )
    selected_indexes = _parse_multiselect(answer, len(targets))
    return [targets[i - 1][0] for i in selected_indexes]


@app.command("list")
def list_skills(
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定扫描目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """列出所有已安装的 Skill。"""
    manager = SkillsManager()
    status_data = manager.status(skills_dir=skills_dir)
    _emit(
        {
            "success": True,
            "command": "skills list",
            "data": {"skills": status_data["skills"]},
            "error": None,
        },
        pretty,
    )


@app.command("install")
def install_skill(
    name: str | None = typer.Argument(None, help="Skill 名称，不指定则进入交互模式安装全部"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定安装目录"),
    runtime: str | None = typer.Option(None, "--runtime", help="claude、openclaw、all，或逗号分隔多个值"),
    force: bool = typer.Option(False, "--force", help="覆盖已存在目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """从内置模板安装 Skill 到本地目录。

    不指定 NAME 时进入 TUI 交互模式，可多选 Skills 和安装目标。
    """
    manager = SkillsManager()
    try:
        if name is None:
            # TUI 模式：交互选择 Skills 和安装目标
            _install_interactive(manager, skills_dir=skills_dir, runtime=runtime, force=force, pretty=pretty)
            return
        # 单 Skill 安装（原有逻辑）
        resolved_runtime = _resolve_install_runtime(
            manager,
            runtime=runtime,
            skills_dir=skills_dir,
        )
        result = manager.install(
            name,
            skills_dir=skills_dir,
            runtime=resolved_runtime,
            force=force,
        )
        # CLI 层统一注入铁律：仅安装 ops-feedback 时触发
        if name == "ops-feedback" and not skills_dir:
            _inject_rules_for_installs(result.installs)

        payload = {
            "success": True,
            "command": "skills install",
            "data": _with_post_install_guidance(result.to_dict(), name),
            "error": None,
        }
    except Exception as exc:
        payload = {
            "success": False,
            "command": "skills install",
            "data": None,
            "error": error_to_dict(exc),
        }
        _emit(payload, pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


def _install_interactive(
    manager: SkillsManager,
    *,
    skills_dir: str | None,
    runtime: str | None,
    force: bool,
    pretty: bool,
) -> None:
    """TUI 交互安装：选择 Skills → 选择目标工具 → 批量安装。

    交互模式默认 force=True（覆盖已有安装），无需手动传 --force。
    """
    force = True  # TUI 模式始终覆盖，避免因已安装而中断
    # Step 1：选择要安装的 Skills
    try:
        skill_names = _tui_select_skills(manager)
    except ValueError as exc:
        _console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(1)

    # Step 2：确定安装目标列表 —— [(runtime, Path), ...]
    # 优先级：显式 skills_dir > 显式 runtime > TUI 全局检测
    target_pairs: list[tuple[str, Path]] | None = None
    if skills_dir:
        # 用户显式指定目录：安装到唯一路径
        target_pairs = [(runtime or "custom", Path(skills_dir).expanduser())]
    elif runtime:
        # 用户显式指定 runtime：通过 detector 解析为具体路径（保持原有行为）
        runtime_list = [r.strip() for r in runtime.split(",") if r.strip()]
        try:
            target_pairs = manager.detector.detect_install_targets(preferred_runtimes=runtime_list)
        except ValueError as exc:
            _console.print(f"[red]错误：{exc}[/red]")
            raise typer.Exit(1)
    else:
        # TUI 全局检测：使用 ~/.claude/、~/.openclaw/ 等全局路径
        try:
            target_pairs = _tui_select_targets(manager)
        except ValueError as exc:
            _console.print(f"[red]错误：{exc}[/red]")
            raise typer.Exit(1)

    # Step 3：批量安装（skill × target 二重循环）
    _console.print()
    all_results: list[dict] = []
    all_installs: list[object] = []  # 收集所有安装结果用于统一注入铁律
    errors: list[str] = []

    for skill_name in skill_names:
        if target_pairs:
            # 有明确路径：逐目标安装，每次传入显式 skills_dir
            for target_runtime, target_path in target_pairs:
                try:
                    result = manager.install(
                        skill_name,
                        skills_dir=str(target_path),
                        runtime=target_runtime,
                        force=force,
                    )
                    all_results.append(_with_post_install_guidance(result.to_dict(), skill_name))
                    all_installs.extend(result.installs)
                    for install in result.installs:
                        _print_install_line(install)
                except Exception as exc:
                    key = f"{skill_name}@{target_path}"
                    errors.append(f"{key}: {exc}")
                    _console.print(f"  [red]✗[/red] [bold]{skill_name}[/bold] [red]{exc}[/red]")
        else:
            # 未检测到任何全局工具：交由 manager 使用默认逻辑
            try:
                result = manager.install(skill_name, force=force)
                all_results.append(_with_post_install_guidance(result.to_dict(), skill_name))
                all_installs.extend(result.installs)
                for install in result.installs:
                    _print_install_line(install)
            except Exception as exc:
                errors.append(f"{skill_name}: {exc}")
                _console.print(f"  [red]✗[/red] [bold]{skill_name}[/bold] [red]{exc}[/red]")

    # 批量安装结束后：如果安装了 ops-feedback，统一注入铁律（去重）
    if "ops-feedback" in skill_names and not skills_dir and all_installs:
        _inject_rules_for_installs(all_installs)

    _console.print()
    if errors:
        _console.print(f"[yellow]完成：{len(all_results)} 个成功，{len(errors)} 个失败[/yellow]")
        payload = {
            "success": False,
            "command": "skills install",
            "data": {"results": all_results},
            "error": {
                "type": "BatchInstallError",
                "message": "; ".join(errors),
            },
        }
        _emit(payload, pretty)
        raise typer.Exit(1)
    else:
        _console.print(f"[green]全部安装完成，共 {len(all_results)} 个 Skill[/green]")
        payload = {
            "success": True,
            "command": "skills install",
            "data": {"results": all_results},
            "error": None,
        }
        _emit(payload, pretty)


def _print_install_line(install: object) -> None:
    """打印单条安装结果行。"""
    replaced = getattr(install, "replaced", False)
    status_icon = "↻" if replaced else "✓"
    name = getattr(install, "name", "")
    version = getattr(install, "version", "")
    runtime = getattr(install, "runtime", "")
    target_dir = getattr(install, "target_dir", "")
    tool_label = _TOOL_LABELS.get(runtime, runtime)
    _console.print(
        f"  [green]{status_icon}[/green] [bold]{name}[/bold] "
        f"[dim]{version}[/dim] → [cyan]{tool_label}[/cyan] "
        f"[dim]({target_dir})[/dim]"
    )


def _inject_rules_for_installs(installs: list[object]) -> None:
    """对安装结果涉及的编辑器目录统一注入反馈铁律。

    按 (runtime, skills_dir) 去重，避免同一编辑器目录重复注入。
    注入成功后打印提示信息。
    """
    injector = RuleInjector()
    seen: set[tuple[str, str]] = set()
    for install in installs:
        runtime = getattr(install, "runtime", "")
        target_dir = getattr(install, "target_dir", None)
        if not runtime or not target_dir:
            continue
        skills_parent = Path(target_dir).parent
        key = (runtime, str(skills_parent))
        if key in seen:
            continue
        seen.add(key)
        config_path = injector.inject(runtime, skills_parent)
        if config_path:
            _console.print(
                f"  [dim]⚙ 已追加反馈铁律到 {config_path}[/dim]"
            )


@app.command("status")
def status(
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定扫描目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """查看 Skill 安装状态，包含远端版本对比。"""
    manager = SkillsManager()
    try:
        data = manager.status(skills_dir=skills_dir)
        payload = {
            "success": True,
            "command": "skills status",
            "data": data,
            "error": None,
        }
    except Exception as exc:
        payload = {
            "success": False,
            "command": "skills status",
            "data": None,
            "error": error_to_dict(exc),
        }
        _emit(payload, pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("upgrade")
def upgrade(
    name: str = typer.Argument("ops-dataset-query", help="Skill 名称"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定扫描目录"),
    force: bool = typer.Option(False, "--force", help="强制覆盖本地版本"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """升级 Skill 到远端最新版本。"""
    # 进度输出到 stderr，不干扰 stdout 的 JSON 结果
    _progress = Console(stderr=True)

    def on_step(msg: str) -> None:
        """将升级各阶段进度打印到 stderr。"""
        _progress.print(f"  [dim]{msg}[/dim]")

    manager = SkillsManager()
    try:
        _progress.print(f"[bold]正在升级 {name}...[/bold]")
        result = manager.upgrade(name=name, skills_dir=skills_dir, force=force, on_step=on_step)
        _progress.print("[bold green]升级完成[/bold green]\n")
        payload = {
            "success": True,
            "command": "skills upgrade",
            "data": result.to_dict(),
            "error": None,
        }
    except Exception as exc:
        _progress.print(f"[bold red]升级失败[/bold red]\n")
        payload = {
            "success": False,
            "command": "skills upgrade",
            "data": None,
            "error": error_to_dict(exc),
        }
        _emit(payload, pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)
