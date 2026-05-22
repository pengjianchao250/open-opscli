"""Skills Marketplace 子命令组。

提供 opscli skills marketplace 下的广场浏览命令：
  list      — 浏览广场技能列表
  search    — 关键词搜索
  info      — 查看技能详情
  versions  — 查看版本历史
  rate      — 提交评分（1-5 分，小数向下取整）
"""

from __future__ import annotations

import json
import os
import shutil

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from opscli.skills.domain.exceptions import error_to_dict
from opscli.skills.marketplace.client import MarketplaceClient
from opscli.skills.marketplace.models import MarketplaceListResult, SkillItem, SkillVersionInfo

app = typer.Typer(help="技能广场：浏览、搜索、查看远程 Skill")
_console = Console()


def _emit(payload: dict, pretty: bool) -> None:
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _terminal_width() -> int:
    return shutil.get_terminal_size((120, 40)).columns


def _build_list_table(items: list[SkillItem], result: MarketplaceListResult) -> Table:
    """构造富文本列表表格，简介列在宽终端（≥120列）时才显示。"""
    wide = _terminal_width() >= 120

    table = Table(
        show_header=True,
        header_style="bold cyan",
        box=None,
        padding=(0, 1),
    )
    table.add_column("标识符",  style="green",      min_width=28)
    table.add_column("版本",    style="dim",         width=7)
    table.add_column("安装",    justify="right",     width=6)
    table.add_column("使用",    justify="right",     width=7)
    table.add_column("评分",    style="yellow",      width=6)
    if wide:
        table.add_column("简介", style="dim", min_width=20)

    for item in items:
        official_mark = " [bold yellow]★[/bold yellow]" if item.is_official else ""
        identifier_text = Text()
        identifier_text.append(item.identifier, style="green")
        if item.is_official:
            identifier_text.append(" ★", style="bold yellow")

        row = [
            item.identifier + (" ★" if item.is_official else ""),
            item.latest_version,
            str(item.install_count),
            str(item.usage_count),
            item.rating_stars,
        ]
        if wide:
            row.append(item.short_desc)
        table.add_row(*row)

    return table


# ──────────────────────────────────────────
# list
# ──────────────────────────────────────────

@app.command("list")
def list_marketplace(
    category: str | None = typer.Option(None, "--category", help="按分类 slug 筛选（如 auth）"),
    sort: str = typer.Option("install_count", "--sort", help="排序：install_count/usage_count/rating_avg/new"),
    order: str = typer.Option("desc", "--order", help="asc 或 desc"),
    page: int  = typer.Option(1,  "--page",  help="页码"),
    limit: int = typer.Option(20, "--limit", help="每页条数（最多100）"),
    official: bool = typer.Option(False, "--official", help="只看官方技能"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """浏览技能广场列表。"""
    params: dict = {"sort": sort, "order": order, "page": page, "limit": limit}
    if category:
        # 先把 slug 转为 category_id
        try:
            cats = MarketplaceClient().get_categories()
            for c in cats:
                if c.get("slug") == category:
                    params["category_id"] = c["id"]
                    break
        except Exception:
            pass
    if official:
        params["is_official"] = "true"

    try:
        client = MarketplaceClient()
        raw = client.list_skills(params)
    except Exception as exc:
        _emit({"success": False, "command": "skills marketplace list", "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    items = [SkillItem.from_dict(d) for d in raw.get("list", [])]
    total = raw.get("total", 0)
    result = MarketplaceListResult(items=items, total=total, page=page, limit=limit)

    if json_output:
        _emit({"success": True, "command": "skills marketplace list", "data": raw}, json_output)
        return

    table = _build_list_table(items, result)
    wide_note = "（简介列在宽度≥120终端显示）" if _terminal_width() < 120 else ""
    _console.print(Panel(
        table,
        title=f"[bold]Skill 技能广场[/bold]{' — ' + category if category else ''}",
        border_style="blue",
    ))
    _console.print(
        f"[dim]第 {page} 页 / 共 {result.total_pages} 页，总计 {total} 个技能{wide_note}[/dim]"
    )


# ──────────────────────────────────────────
# search
# ──────────────────────────────────────────

@app.command("search")
def search_marketplace(
    keyword: str = typer.Argument(..., help="搜索关键词"),
    sort: str  = typer.Option("install_count", "--sort"),
    page: int  = typer.Option(1,  "--page"),
    limit: int = typer.Option(20, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
):
    """在技能广场中关键词搜索。"""
    params = {"keyword": keyword, "sort": sort, "page": page, "limit": limit}
    try:
        raw = MarketplaceClient().list_skills(params)
    except Exception as exc:
        _emit({"success": False, "command": f"skills marketplace search {keyword}", "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    items = [SkillItem.from_dict(d) for d in raw.get("list", [])]
    total = raw.get("total", 0)
    result = MarketplaceListResult(items=items, total=total, page=page, limit=limit)

    if json_output:
        _emit({"success": True, "command": "skills marketplace search", "data": raw}, json_output)
        return

    if not items:
        _console.print(f"[yellow]未找到与 [bold]{keyword}[/bold] 相关的技能[/yellow]")
        return

    table = _build_list_table(items, result)
    _console.print(Panel(
        table,
        title=f"[bold]搜索结果：{keyword}[/bold]",
        border_style="blue",
    ))
    _console.print(f"[dim]共找到 {total} 个技能，当前第 {page}/{result.total_pages} 页[/dim]")


# ──────────────────────────────────────────
# info
# ──────────────────────────────────────────

@app.command("info")
def skill_info(
    identifier: str = typer.Argument(..., help="技能标识符，如 pengjianchao@ops-auth"),
    json_output: bool = typer.Option(False, "--json"),
):
    """查看技能详情（含版本、统计、标签）。"""
    if "@" not in identifier:
        _console.print(f"[red]错误：标识符格式应为 username@skill_name，收到: {identifier!r}[/red]")
        raise typer.Exit(1)

    username, skill_name = identifier.split("@", 1)
    try:
        client = MarketplaceClient()
        raw = client.get_by_identifier(username, skill_name)
    except Exception as exc:
        _emit({"success": False, "command": f"skills marketplace info {identifier}", "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    if json_output:
        _emit({"success": True, "command": "skills marketplace info", "data": raw}, json_output)
        return

    item = SkillItem.from_dict(raw)
    _print_skill_info(item)


def _print_skill_info(item: SkillItem) -> None:
    """富文本输出技能详情面板。"""
    official_badge = " [bold yellow][官方认证][/bold yellow]" if item.is_official else ""
    cat_name = item.category.name if item.category else "未分类"
    tags_str = "  ".join(f"[cyan]{t}[/cyan]" for t in item.tags) if item.tags else "[dim]无[/dim]"

    lines = [
        f"[bold]{item.title}[/bold]{official_badge}",
        "",
        f"[dim]标识符  [/dim] {item.identifier}",
        f"[dim]当前版本[/dim] {item.latest_version}",
        f"[dim]分  类  [/dim] {cat_name}",
        f"[dim]标  签  [/dim] {tags_str}",
        "",
        f"[dim]简  介  [/dim] {item.description or '（暂无描述）'}",
        "",
        f"[dim]安装次数[/dim] {item.install_count}    "
        f"[dim]使用次数[/dim] {item.usage_count}    "
        f"[dim]收  藏  [/dim] {item.favorite_count}    "
        f"[dim]评  分  [/dim] {item.rating_stars} ({item.rating_count} 人评价)",
        "",
        f"[dim]发布时间[/dim] {item.created_at[:10] if item.created_at else '-'}",
    ]

    _console.print(Panel(
        "\n".join(lines),
        title=f"[bold]技能详情[/bold]",
        border_style="blue",
        expand=False,
    ))

    _console.print()
    _console.print(
        f"[dim]安装命令：[/dim] [green]opscli skills install {item.identifier}[/green]"
    )


# ──────────────────────────────────────────
# versions
# ──────────────────────────────────────────

@app.command("versions")
def skill_versions(
    identifier: str = typer.Argument(..., help="技能标识符，如 pengjianchao@ops-auth"),
    json_output: bool = typer.Option(False, "--json"),
):
    """查看技能版本历史。"""
    if "@" not in identifier:
        _console.print(f"[red]错误：标识符格式应为 username@skill_name[/red]")
        raise typer.Exit(1)

    username, skill_name = identifier.split("@", 1)
    try:
        client = MarketplaceClient()
        skill_data = client.get_by_identifier(username, skill_name)
        versions_raw = client.get_versions(skill_data["id"])
    except Exception as exc:
        _emit({"success": False, "command": f"skills marketplace versions {identifier}", "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    if json_output:
        _emit({"success": True, "command": "skills marketplace versions", "data": versions_raw}, json_output)
        return

    if not versions_raw:
        _console.print(f"[yellow]{identifier} 暂无版本记录[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("版本",     style="green",  width=10)
    table.add_column("文件大小", style="dim",    width=10)
    table.add_column("发布时间", style="dim",    width=22)
    table.add_column("变更说明")

    for v in versions_raw:
        ver = SkillVersionInfo.from_dict(v)
        size_str = f"{ver.file_size // 1024} KB" if ver.file_size else "-"
        changelog = (ver.changelog[:50] + "...") if ver.changelog and len(ver.changelog) > 50 else (ver.changelog or "-")
        table.add_row(ver.version, size_str, ver.created_at[:19], changelog)

    latest = versions_raw[0].get("version", "")
    _console.print(Panel(
        table,
        title=f"[bold]{identifier}[/bold] 版本历史（最新: {latest}）",
        border_style="blue",
    ))


# ──────────────────────────────────────────
# rate
# ──────────────────────────────────────────

@app.command("rate")
def rate_skill(
    identifier: str = typer.Argument(..., help="技能标识符，如 pengjianchao@ops-auth"),
    score: float = typer.Argument(..., help="评分（1-5 分；小数自动向下取整，如 4.7 → 4）"),
    comment: str | None = typer.Option(None, "--comment", "-c", help="评价文字（可选，最多 500 字符）"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """给广场技能打分（1-5 分整数；已评分则更新）。"""
    command = f"skills marketplace rate {identifier} {score}"

    if "@" not in identifier:
        _console.print("[red]错误：标识符格式应为 username@skill_name[/red]")
        raise typer.Exit(1)

    # 向下取整 + 范围限制
    int_score = max(1, min(5, int(score)))
    if int_score != score:
        _console.print(f"[dim]评分 {score} 向下取整为 {int_score}[/dim]")

    username, skill_name = identifier.split("@", 1)
    try:
        client = MarketplaceClient()
        skill_data = client.get_by_identifier(username, skill_name)
        result = client.submit_rating(skill_data["id"], int_score, comment)
    except Exception as exc:
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    if json_output:
        _emit({"success": True, "command": command, "data": result}, json_output)
        return

    _console.print(
        f"[green]已为 [bold]{identifier}[/bold] 提交评分：{'⭐' * int_score} ({int_score}/5)[/green]"
    )
    if comment:
        _console.print(f"[dim]评价：{comment}[/dim]")
