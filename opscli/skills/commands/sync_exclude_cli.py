"""Skills 同步排除名单子命令组。

提供 opscli skills sync-exclude 下的命令：
  add     — 将指定技能加入不同步排除名单
  remove  — 将指定技能移出排除名单
  list    — 查看当前排除名单
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from opscli.skills.domain.exceptions import error_to_dict
from opscli.skills.marketplace.client import MarketplaceClient

app = typer.Typer(help="管理不同步到本地的技能排除名单")
_console = Console()


def _emit(payload: dict, pretty: bool) -> None:
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


# ──────────────────────────────────────────
# add
# ──────────────────────────────────────────

@app.command("add")
def add_exclude(
    identifier: str = typer.Argument(..., help="技能标识符，格式 username@skill_name"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """将指定技能加入不同步排除名单。

    加入后，执行 opscli skills install --sync-market 时将跳过此技能。
    """
    if "@" not in identifier:
        _console.print(f"[red]错误：标识符格式应为 username@skill_name，收到: {identifier!r}[/red]")
        raise typer.Exit(1)

    try:
        result = MarketplaceClient().add_sync_exclude(identifier)
    except Exception as exc:
        payload = {"success": False, "command": f"skills sync-exclude add {identifier}", "error": error_to_dict(exc)}
        _emit(payload, json_output)
        raise typer.Exit(1)

    if json_output:
        _emit({"success": True, "command": f"skills sync-exclude add {identifier}", "data": result}, json_output)
        return

    _console.print(f"[green]✓[/green] 已将 [bold]{identifier}[/bold] 加入排除名单，同步时将自动跳过")


# ──────────────────────────────────────────
# remove
# ──────────────────────────────────────────

@app.command("remove")
def remove_exclude(
    identifier: str = typer.Argument(..., help="技能标识符，格式 username@skill_name"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """将指定技能移出不同步排除名单。

    移除后，执行 opscli skills install --sync-market 时将重新纳入同步范围。
    """
    if "@" not in identifier:
        _console.print(f"[red]错误：标识符格式应为 username@skill_name，收到: {identifier!r}[/red]")
        raise typer.Exit(1)

    # 先通过 identifier 查询 skill_id（借助 list_sync_excludes 匹配）
    try:
        client = MarketplaceClient()
        excludes = client.list_sync_excludes()
        matched = next((e for e in excludes if e.get("identifier") == identifier), None)
        if matched is None:
            _console.print(f"[yellow]排除名单中未找到 {identifier!r}，可能从未加入过[/yellow]")
            raise typer.Exit(0)
        client.remove_sync_exclude(matched["skill_id"])
    except typer.Exit:
        raise
    except Exception as exc:
        payload = {"success": False, "command": f"skills sync-exclude remove {identifier}", "error": error_to_dict(exc)}
        _emit(payload, json_output)
        raise typer.Exit(1)

    if json_output:
        _emit({"success": True, "command": f"skills sync-exclude remove {identifier}"}, json_output)
        return

    _console.print(f"[green]✓[/green] 已将 [bold]{identifier}[/bold] 移出排除名单，下次同步将重新纳入")


# ──────────────────────────────────────────
# list
# ──────────────────────────────────────────

@app.command("list")
def list_excludes(
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """查看当前不同步排除名单。"""
    try:
        items = MarketplaceClient().list_sync_excludes()
    except Exception as exc:
        _emit({"success": False, "command": "skills sync-exclude list", "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    if json_output:
        _emit({"success": True, "command": "skills sync-exclude list", "data": items}, json_output)
        return

    if not items:
        _console.print("[dim]排除名单为空，所有市场安装记录都会纳入同步[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("标识符",  style="green", min_width=30)
    table.add_column("标题",    style="dim",   min_width=16)
    table.add_column("简介",    style="dim",   min_width=20)
    table.add_column("加入时间", style="dim",   width=12)

    for item in items:
        created = (item.get("created_at") or "")[:10]
        table.add_row(
            item.get("identifier") or "—",
            item.get("title")      or "—",
            (item.get("summary") or "")[:30],
            created,
        )

    _console.print(Panel(
        table,
        title="[bold]同步排除名单[/bold]",
        border_style="yellow",
    ))
    _console.print(f"[dim]共 {len(items)} 个技能被排除在自动同步之外[/dim]")
