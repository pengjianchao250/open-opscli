"""Skills CLI 子命令定义。

注册到 opscli 顶级命令下，提供以下子命令：
  list / install / status / link / unlink / upgrade / report-usage — Skill 本地生命周期
  publish / edit / unpublish                                        — 技能广场发布管理
  marketplace categories / list / search / info / versions / rate  — 技能广场浏览
  sync-exclude add / remove / list                                  — 同步排除名单管理

所有命令输出统一 JSON 格式，方便脚本解析。
"""

from __future__ import annotations

import json
import sys
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from opscli.auth.exceptions import AuthError
from opscli.skills.domain.exceptions import SkillRemoteError, error_to_dict
from opscli.skills.domain.models import runtime_to_tool_name
from opscli.skills.marketplace.client import MarketplaceClient
from opscli.skills.marketplace.models import (
    SHARE_TYPES,
    SHARE_TYPE_PERSONAL,
    MarketplaceListResult,
    SkillItem,
    SkillVersionInfo,
)
from opscli.skills.marketplace.remote_installer import install_remote_skill
from opscli.skills.packaging import get_central_skills_dir
from opscli.skills.services.manager import SkillsManager
from opscli.skills.services.rule_injector import RuleInjector

# ── Typer 应用实例 ─────────────────────────────────────────────────────────────
app = typer.Typer(help="Skill 生命周期管理")

# 技能广场子命令组（marketplace categories/list/search/info/versions/rate）
marketplace_app = typer.Typer(help="技能广场：浏览、搜索、查看远程 Skill")
app.add_typer(marketplace_app, name="marketplace")

# 同步排除名单子命令组（sync-exclude add/remove/list）
sync_exclude_app = typer.Typer(help="管理不同步到本地的技能排除名单")
app.add_typer(sync_exclude_app, name="sync-exclude")

_console = Console()

# ── 常量 ──────────────────────────────────────────────────────────────────────

# AI 工具显示标签映射
_TOOL_LABELS = {
    "claude":    "Claude Code",
    "openclaw":  "OpenClaw",
    "codex":     "Codex CLI",
    "opencode":  "OpenCode",
    "workbuddy": "WorkBuddy",
    "trae-cn":   "Trae Solo",
    "agents":    "Agents",
    "auwork":    "AuWork",
    "central":   "中央存储",
}

# ops-amazon-rufus 安装后引导信息
_AMAZON_RUFUS_SKILL_NAME = "ops-amazon-rufus"
_AMAZON_RUFUS_NEXT_STEPS = [
    "先执行 opscli amazon-rufus remote-consent status <country> --pretty 读取该站点远程授权偏好。",
    "未询问过时让用户明确回复“允许”或“拒绝”；请建议使用独立干净的 Amazon 账号，且不建议绑定信用卡或支付方式。",
    "发起 Rufus 获取前执行 opscli amazon-rufus login-status <country> --pretty；没有可用登录态时执行 opscli amazon-rufus watch-login <asin> <country> --launch-if-needed --close-browser。",
    "允许远程授权且登录态可用时调用 amazon_rufus_get；如需恢复登录态，执行 watch-login 后重试 MCP 获取。",
    "拒绝远程授权且登录态可用时调用 opscli amazon-rufus get-backend <asin> <country>。",
]

# marketplace list 命令的参数枚举与面板标题
_SCOPE_CHOICES = ("all", "personal")
_SUB_CHOICES   = ("mine", "shared_with_me")
_SCOPE_TITLES: dict[str, str] = {
    "all":      "Skill 技能广场",
    "personal": "个人相关技能",
}
_SUB_TITLES: dict[str, str] = {
    "mine":           "我创建的",
    "shared_with_me": "分享给我的",
}


# ── 共用辅助函数 ───────────────────────────────────────────────────────────────

def _emit(payload: dict, pretty: bool) -> None:
    """统一的 JSON 输出函数，控制是否美化格式。"""
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _terminal_width() -> int:
    """获取当前终端宽度，宽度未知时默认 120 列。"""
    return shutil.get_terminal_size((120, 40)).columns


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


# ── marketplace 辅助函数 ──────────────────────────────────────────────────────

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
    table.add_column("分享",    style="dim",         width=6)
    table.add_column("版本",    style="dim",         width=7)
    table.add_column("已安装",  style="cyan",        width=6)
    table.add_column("安装数",  justify="right",     width=6)
    table.add_column("使用",    justify="right",     width=7)
    table.add_column("评分",    style="yellow",      width=6)
    if wide:
        table.add_column("简介", style="dim", min_width=20)

    for item in items:
        row = [
            item.identifier + (" ★" if item.is_official else ""),
            item.share_type_label,
            item.latest_version,
            item.install_badge,
            str(item.install_count),
            str(item.usage_count),
            item.rating_stars,
        ]
        if wide:
            row.append(item.short_desc)
        table.add_row(*row)

    return table


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
        f"[dim]分享权限[/dim] {item.share_type_label}",
        f"[dim]标  签  [/dim] {tags_str}",
        "",
    ]
    if item.summary:
        lines += [
            f"[dim]一句话  [/dim] {item.summary}",
            "",
        ]

    # 安装状态区块
    if item.is_installed:
        if item.is_latest_version:
            install_status = f"[green]√ 已安装最新版[/green]  [dim]({item.installed_version})[/dim]"
        else:
            install_status = (
                f"[yellow]↑ 可更新[/yellow]  "
                f"[dim]已安装 {item.installed_version} → 最新 {item.latest_version}[/dim]"
            )
    else:
        install_status = "[dim]未安装[/dim]"

    lines += [
        f"[dim]简  介  [/dim] {item.description or '（暂无描述）'}",
        "",
        f"[dim]安装状态[/dim] {install_status}",
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
        title="[bold]技能详情[/bold]",
        border_style="blue",
        expand=False,
    ))
    _console.print()
    _console.print(
        f"[dim]安装命令：[/dim] [green]opscli skills install {item.identifier}[/green]"
    )


# ── publish 辅助函数 ──────────────────────────────────────────────────────────

def _read_skill_file(skill_dir: Path) -> tuple[Path, dict]:
    """从技能目录读取 SKILL.md 和 data/VERSION.json，返回 (skill_md_path, version_data)。"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"未找到 SKILL.md：{skill_md}")

    ver_file = skill_dir / "data" / "VERSION.json"
    if not ver_file.exists():
        raise FileNotFoundError(f"未找到 data/VERSION.json：{ver_file}")

    version_data = json.loads(ver_file.read_text(encoding="utf-8"))
    return skill_md, version_data


def _zip_skill_dir(skill_dir: Path, skill_name: str) -> Path:
    """将技能目录打包为临时 zip 文件，返回 zip 路径（调用方负责删除）。

    打包规则：目录内所有文件，arcname 相对于 skill_dir；排除 __pycache__、*.pyc、*.pyo。
    """
    tmp = tempfile.NamedTemporaryFile(
        suffix=".zip", prefix=f"{skill_name}_", delete=False
    )
    tmp.close()
    zip_path = Path(tmp.name)

    skip = {"__pycache__"}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if any(p in skip for p in file_path.parts):
                continue
            if file_path.suffix in {".pyc", ".pyo"}:
                continue
            arcname = file_path.relative_to(skill_dir)
            zf.write(file_path, arcname)

    return zip_path


def _match_best_category(
    categories: list[dict],
    skill_name: str,
    title: str = "",
    tags: str = "",
    description: str = "",
) -> dict | None:
    """基于技能名/标题/标签/描述关键词匹配最合适的分类，返回得分最高的分类 dict 或 None。

    匹配策略：将关键词与分类 slug/name 做子串匹配，得分最高者胜出，得分为 0 返回 None。
    """
    if not categories:
        return None

    def tokenize(s: str) -> list[str]:
        """拆分为小写词列表，去掉常见分隔符。"""
        return [w.lower() for w in s.replace("-", " ").replace(",", " ").replace("，", " ").split() if w]

    keywords = (
        tokenize(skill_name)
        + tokenize(title)
        + tokenize(tags)
        + tokenize(description[:200] if description else "")
    )
    if not keywords:
        return None

    best_cat: dict | None = None
    best_score = 0

    for cat in categories:
        slug = (cat.get("slug") or "").lower()
        name = (cat.get("name") or "").lower()
        slug_words = slug.split("-") if slug else []
        score = 0

        for kw in keywords:
            # 整体子串命中 slug 或 name，得 2 分
            if kw in slug or kw in name:
                score += 2
            else:
                # 对 slug 的每个分词做子串匹配，得 1 分
                for sw in slug_words:
                    if sw and (kw == sw or kw in sw or sw in kw):
                        score += 1
                        break

        if score > best_score:
            best_score = score
            best_cat = cat

    return best_cat if best_score > 0 else None


# summary 上限 500 字符（与 --summary 选项文档约束一致），从 description 派生时需截断
_SUMMARY_MAX_LEN = 500


def _summary_from_desc(description: str | None) -> str:
    """从 frontmatter 的 description 派生 summary：去空白并截断到 500 字符。

    用于客户端未传 --summary 且 frontmatter 无 summary 字段时的回退，
    避免发布时 summary 为空。返回空串表示无可用 description。
    """
    if not description:
        return ""
    text = description.strip()
    return text[:_SUMMARY_MAX_LEN]


def _parse_skill_md_frontmatter(skill_md: Path) -> dict:
    """解析 SKILL.md 顶部 YAML frontmatter（--- 包裹），返回字段字典。

    支持字段：title, description, tags（逗号或空格分隔），category_id。
    """
    content = skill_md.read_text(encoding="utf-8")
    result: dict = {}
    if not content.startswith("---"):
        return result

    end = content.find("\n---", 3)
    if end == -1:
        return result

    frontmatter = content[3:end].strip()
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()

    return result


def _normalize_skill_version(version: str | None, label: str) -> str:
    normalized = (version or "").strip().lstrip("vV")
    if not normalized:
        raise ValueError(f"{label} 不能为空")
    if not re.match(r"^\d+\.\d+\.\d+$", normalized):
        raise ValueError(f"{label} 必须为 x.y.z 格式，收到：{version!r}")
    return normalized


def _validate_skill_version_consistency(
    skill_md_path: Path,
    version_data: dict,
    request_version: str | None = None,
) -> str:
    """校验请求版本、SKILL.md 和 data/VERSION.json 三者一致，返回归一化版本号。"""
    version_json = _normalize_skill_version(str(version_data.get("version", "")), "data/VERSION.json version")
    fm = _parse_skill_md_frontmatter(skill_md_path)
    skill_md_version = _normalize_skill_version(fm.get("version"), "SKILL.md frontmatter.version")
    if version_json != skill_md_version:
        raise ValueError(
            f"版本号不一致：data/VERSION.json 中为 '{version_json}'，"
            f"SKILL.md frontmatter 中为 '{skill_md_version}'。请确保两者一致。"
        )

    if request_version is not None:
        requested = _normalize_skill_version(request_version, "--version")
        if requested != version_json:
            raise ValueError(
                f"版本号不一致：--version 为 '{requested}'，"
                f"data/VERSION.json / SKILL.md 中为 '{version_json}'。请同步后重试。"
            )

    return version_json


def _validate_zip_skill_version_consistency(zip_path: Path, request_version: str | None = None) -> str:
    """校验 zip 包内 SKILL.md 和 data/VERSION.json 版本一致，返回归一化版本号。"""
    with zipfile.ZipFile(zip_path) as zf:
        skill_md_name = "SKILL.md" if "SKILL.md" in zf.namelist() else None
        root_prefix = ""
        if skill_md_name is None:
            for name in zf.namelist():
                parts = Path(name).parts
                if len(parts) == 2 and parts[1] == "SKILL.md" and parts[0] != "__MACOSX":
                    skill_md_name = name
                    root_prefix = f"{parts[0]}/"
                    break
        if skill_md_name is None:
            raise ValueError("zip 包中未找到 SKILL.md")

        version_json_name = f"{root_prefix}data/VERSION.json"
        if version_json_name not in zf.namelist():
            raise ValueError(f"zip 包中未找到 {version_json_name}")

        skill_md_text = zf.read(skill_md_name).decode("utf-8")
        version_data = json.loads(zf.read(version_json_name).decode("utf-8"))

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as tmp:
        tmp.write(skill_md_text)
        tmp_path = Path(tmp.name)
    try:
        return _validate_skill_version_consistency(tmp_path, version_data, request_version)
    finally:
        tmp_path.unlink(missing_ok=True)


# ── install 辅助函数 ───────────────────────────────────────────────────────────

def _tui_select_skills(manager: SkillsManager, *, yes: bool = False) -> list[str]:
    """TUI：展示内置 Skill 列表，用户选择要安装哪些。返回选中的 skill 名称列表。

    yes=True 时跳过 prompt，直接全选。
    """
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

    if yes:
        _console.print("[dim]--yes：自动全选所有 Skills[/dim]")
        return [tmpl["name"] for tmpl in templates]

    answer = typer.prompt(
        "请选择要安装的 Skills（逗号分隔编号，直接回车安装全部）",
        default="",
        show_default=False,
    )
    selected_indexes = _parse_multiselect(answer, len(templates))
    return [templates[i - 1]["name"] for i in selected_indexes]


def _tui_select_targets(manager: SkillsManager, *, yes: bool = False) -> list[tuple[str, Path]] | None:
    """TUI：展示全局检测到的工具列表，用户选择安装到哪些工具。

    使用 detect_global_install_targets() 按 ~/.claude/、which claude 等规则检测，
    而非项目级 CWD 目录。

    返回选中的 [(runtime, skills_dir), ...] 列表；未检测到任何工具时返回 None。
    yes=True 时跳过 prompt，直接全选。
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

    if yes:
        _console.print("[dim]--yes：自动全选所有安装目标[/dim]")
        return targets

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


def _print_install_line(install: object) -> None:
    """打印单条安装结果行。"""
    replaced = getattr(install, "replaced", False)
    status_icon = "↑" if replaced else "√"
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


def _print_sync_preview(
    to_install: list[dict],
    to_upgrade: list[dict],
    to_skip: list[dict],
) -> None:
    """打印 --dry-run 同步预览表格（不执行实际安装）。"""
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("标识符",  style="green", min_width=32)
    table.add_column("本地版本", style="dim",   width=10)
    table.add_column("市场版本", style="dim",   width=10)
    table.add_column("动作",    width=8)

    for item in to_install:
        table.add_row(
            item["identifier"],
            "× 未安装",
            item.get("latest_version", "?"),
            "[bold blue]新装[/bold blue]",
        )
    for item in to_upgrade:
        from_ver = item.get("_from_version", "未知")
        reinstall = item.get("_reinstall", False)
        table.add_row(
            item["identifier"],
            f"[yellow]{from_ver}[/yellow]" if not reinstall else "[red]版本未知[/red]",
            item.get("latest_version", "?"),
            "[bold yellow]↑ 升级[/bold yellow]",
        )
    for item in to_skip:
        table.add_row(
            item["identifier"],
            item.get("latest_version", "?"),
            item.get("latest_version", "?"),
            "[dim]√ 跳过[/dim]",
        )

    total = len(to_install) + len(to_upgrade) + len(to_skip)
    _console.print(Panel(
        table,
        title="[bold]同步预览（--dry-run，未实际安装）[/bold]",
        border_style="blue",
    ))
    _console.print(
        f"[dim]安装 {len(to_install)} 个 / 升级 {len(to_upgrade)} 个 / 跳过 {len(to_skip)} 个，共 {total} 项[/dim]"
    )


def _print_sync_result(
    installed_ok: list[str],
    upgraded_ok: list[str],
    skipped: list[dict],
    failed: list[tuple[str, str]],
) -> None:
    """打印同步执行结果汇总。"""
    _console.print("\n[bold green]同步完成[/bold green]")
    if installed_ok:
        items_str = "、".join(installed_ok)
        _console.print(f"   [blue]新装[/blue]  {len(installed_ok)} 个：{items_str}")
    if upgraded_ok:
        items_str = "、".join(upgraded_ok)
        _console.print(f"   [yellow]↑ 升级[/yellow]  {len(upgraded_ok)} 个：{items_str}")
    if skipped:
        _console.print(f"   [dim]√ 跳过[/dim]  {len(skipped)} 个：已是最新版")
    if failed:
        _console.print(f"   [red]× 失败[/red]  {len(failed)} 个：")
        for identifier, reason in failed:
            _console.print(f"      [red]{identifier}[/red]（{reason}，可稍后重试）")


def _install_sync_market(
    *,
    skills_dir: str | None,
    runtime: str | None,
    dry_run: bool,
    pretty: bool,
) -> None:
    """--sync-market 模式：拉取市场同步队列，补装缺失 + 升级旧版。"""
    from packaging.version import InvalidVersion, Version

    # Step 1：拉取市场待同步列表
    try:
        queue = MarketplaceClient().get_sync_queue()
    except Exception as exc:
        _emit({"success": False, "command": "skills install --sync-market",
               "error": error_to_dict(exc)}, pretty)
        raise typer.Exit(1)

    if not queue:
        _console.print("[dim]暂无需同步的技能（市场无安装记录，或全部已被加入排除名单）[/dim]")
        return

    # Step 2：扫描本地已安装版本 {skill_name: version_str}
    manager = SkillsManager()
    local_skills: dict[str, str] = {}
    try:
        detected = manager.list_skills(skills_dir=skills_dir)
        for s in detected:
            local_skills[s.name] = s.version or ""
    except Exception:
        pass  # 扫描失败时视为本地全部缺失

    # Step 3：分类（新装 / 升级 / 跳过）
    to_install: list[dict] = []
    to_upgrade: list[dict] = []
    to_skip:    list[dict] = []

    for item in queue:
        identifier     = item.get("identifier", "")
        skill_name     = identifier.split("@")[-1] if "@" in identifier else ""
        market_ver_str = item.get("latest_version", "0.0.0")
        local_ver_str  = local_skills.get(skill_name, "")

        if not local_ver_str:
            to_install.append(item)
            continue

        try:
            local_v  = Version(local_ver_str.lstrip("v"))
            market_v = Version(market_ver_str.lstrip("v"))
        except InvalidVersion:
            item["_reinstall"] = True
            to_upgrade.append(item)
            continue

        if local_v < market_v:
            item["_from_version"] = local_ver_str
            to_upgrade.append(item)
        else:
            to_skip.append(item)

    # Step 4：dry-run 预览
    if dry_run:
        _print_sync_preview(to_install, to_upgrade, to_skip)
        return

    # Step 5：实际执行
    installed_ok:  list[str] = []
    upgraded_ok:   list[str] = []
    failed:        list[tuple[str, str]] = []

    for item in to_install + to_upgrade:
        identifier  = item["identifier"]
        market_ver  = item.get("latest_version")
        is_upgrade  = item in to_upgrade
        try:
            payload = install_remote_skill(
                identifier=identifier,
                version=market_ver,
                skills_dir=skills_dir,
                runtime=runtime,
                force=True,
            )
            if payload.get("success"):
                if is_upgrade:
                    upgraded_ok.append(
                        f"{identifier} {item.get('_from_version', '?')} → {market_ver}"
                    )
                else:
                    installed_ok.append(f"{identifier} v{market_ver}")
            else:
                err = (payload.get("error") or {}).get("message", "未知错误")
                failed.append((identifier, err))
        except Exception as exc:
            failed.append((identifier, str(exc)))

    _print_sync_result(installed_ok, upgraded_ok, to_skip, failed)


def _install_interactive(
    manager: SkillsManager,
    *,
    skills_dir: str | None,
    runtime: str | None,
    force: bool,
    yes: bool,
    pretty: bool,
) -> None:
    """TUI 交互安装：选择 Skills → 选择目标工具 → 批量安装。

    交互模式默认 force=True（覆盖已有安装），无需手动传 --force。
    yes=True 时跳过所有 prompt，直接全选 Skills 和全部检测到的工具。
    """
    force = True  # TUI 模式始终覆盖，避免因已安装而中断

    # Step 1：选择要安装的 Skills
    try:
        skill_names = _tui_select_skills(manager, yes=yes)
    except ValueError as exc:
        _console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(1)

    # Step 2：确定安装目标列表 —— [(runtime, Path), ...]
    # 优先级：显式 skills_dir > 显式 runtime > TUI 全局检测（yes 时跳过确认）
    target_pairs: list[tuple[str, Path]] | None = None
    if skills_dir:
        target_pairs = [(runtime or "custom", Path(skills_dir).expanduser())]
    elif runtime:
        runtime_list = [r.strip() for r in runtime.split(",") if r.strip()]
        try:
            target_pairs = manager.detector.detect_install_targets(preferred_runtimes=runtime_list)
        except ValueError as exc:
            _console.print(f"[red]错误：{exc}[/red]")
            raise typer.Exit(1)
    else:
        try:
            target_pairs = _tui_select_targets(manager, yes=yes)
        except ValueError as exc:
            _console.print(f"[red]错误：{exc}[/red]")
            raise typer.Exit(1)

    # Step 3：批量安装（中央存储 + 链接模式，每个 skill 只调一次 install）
    _console.print()
    all_results: list[dict] = []
    all_installs: list[object] = []
    errors: list[str] = []

    for skill_name in skill_names:
        try:
            result = manager.install(
                skill_name,
                link_targets=target_pairs,
                force=force,
            )
            all_results.append(_with_post_install_guidance(result.to_dict(), skill_name))
            all_installs.extend(result.installs)
            for install in result.installs:
                _print_install_line(install)
        except Exception as exc:
            errors.append(f"{skill_name}: {exc}")
            _console.print(f"  [red]×[/red] [bold]{skill_name}[/bold] [red]{exc}[/red]")

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


# ══════════════════════════════════════════════════════════════════════════════
# marketplace 子命令组
# ══════════════════════════════════════════════════════════════════════════════

@marketplace_app.command("categories")
def list_categories(
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """查看所有技能分类（含 ID、slug 和中文名称）。

    发布或搜索技能时可用 slug 筛选：opscli skills marketplace list --category <slug>
    """
    command = "skills marketplace categories"
    try:
        cats = MarketplaceClient().get_categories()
    except Exception as exc:
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    if json_output:
        _emit({"success": True, "command": command, "data": cats}, json_output)
        return

    if not cats:
        _console.print("[yellow]暂无分类数据[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("ID",       style="dim",   width=6)
    table.add_column("Slug",     style="green", min_width=16)
    table.add_column("分类名称",               min_width=12)

    for cat in cats:
        table.add_row(
            str(cat.get("id", "")),
            cat.get("slug", ""),
            cat.get("name", ""),
        )

    _console.print(Panel(
        table,
        title="[bold]Skill 技能分类[/bold]",
        border_style="blue",
    ))
    _console.print(
        f"[dim]共 {len(cats)} 个分类，"
        "使用 [bold]--category <slug>[/bold] 筛选技能列表，"
        "发布时自动匹配最合适的分类[/dim]"
    )


@marketplace_app.command("list")
def list_marketplace(
    scope: str = typer.Option(
        "all",
        "--scope",
        help="范围：all（技能广场，department/company）| personal（个人相关）",
    ),
    sub: str | None = typer.Option(
        None,
        "--sub",
        help="personal 范围下的子筛选：mine（我创建的）| shared_with_me（分享给我的）；不传则展示两者",
    ),
    category: str | None = typer.Option(None, "--category", help="按分类 slug 筛选（如 auth）"),
    share_type: str | None = typer.Option(None, "--share-type", help=f"按分享类型筛选：{'/'.join(SHARE_TYPES)}"),
    sort: str = typer.Option("install_count", "--sort", help="排序：install_count/usage_count/rating_avg/new"),
    order: str = typer.Option("desc", "--order", help="asc 或 desc"),
    page: int  = typer.Option(1,  "--page",  help="页码"),
    limit: int = typer.Option(20, "--limit", help="每页条数（最多100）"),
    official: bool = typer.Option(False, "--official", help="只看官方技能"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """浏览技能列表。

    \b
    --scope all       技能广场（share_type 为 department / company，默认）
    --scope personal  个人相关（我创建的 + 分享给我的）
      --sub mine            仅我创建的
      --sub shared_with_me  仅分享给我的（他人创建且我安装过）
    """
    # ── 参数校验 ────────────────────────────────────────────
    if scope not in _SCOPE_CHOICES:
        _console.print(f"[red]错误：--scope 必须为 {'/'.join(_SCOPE_CHOICES)}，收到: {scope!r}[/red]")
        raise typer.Exit(1)

    if sub is not None:
        if scope != "personal":
            _console.print("[red]错误：--sub 仅在 --scope personal 时有效[/red]")
            raise typer.Exit(1)
        if sub not in _SUB_CHOICES:
            _console.print(f"[red]错误：--sub 必须为 {'/'.join(_SUB_CHOICES)}，收到: {sub!r}[/red]")
            raise typer.Exit(1)

    if share_type and share_type not in SHARE_TYPES:
        _console.print(f"[red]错误：--share-type 必须为 {'/'.join(SHARE_TYPES)}，收到: {share_type!r}[/red]")
        raise typer.Exit(1)

    # ── 构建请求参数 ─────────────────────────────────────────
    params: dict = {"sort": sort, "order": order, "page": page, "limit": limit, "scope": scope}
    if sub:
        params["sub"] = sub
    if category:
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
    if share_type:
        params["share_type"] = share_type

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

    # ── 面板标题 ─────────────────────────────────────────────
    base_title = _SCOPE_TITLES.get(scope, "Skill 列表")
    if scope == "personal" and sub:
        base_title += f" — {_SUB_TITLES[sub]}"
    if category:
        base_title += f" — {category}"

    table = _build_list_table(items, result)
    wide_note = "（简介列在宽度≥120终端显示）" if _terminal_width() < 120 else ""
    _console.print(Panel(
        table,
        title=f"[bold]{base_title}[/bold]",
        border_style="blue",
    ))
    _console.print(
        f"[dim]第 {page} 页 / 共 {result.total_pages} 页，总计 {total} 个技能{wide_note}[/dim]"
    )


@marketplace_app.command("search")
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


@marketplace_app.command("info")
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


@marketplace_app.command("versions")
def skill_versions(
    identifier: str = typer.Argument(..., help="技能标识符，如 pengjianchao@ops-auth"),
    json_output: bool = typer.Option(False, "--json"),
):
    """查看技能版本历史。"""
    if "@" not in identifier:
        _console.print("[red]错误：标识符格式应为 username@skill_name[/red]")
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


@marketplace_app.command("rate")
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

    stars = "*" * int_score
    _console.print(
        f"[green]已为 [bold]{identifier}[/bold] 提交评分：{stars} ({int_score}/5)[/green]"
    )
    if comment:
        _console.print(f"[dim]评价：{comment}[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
# sync-exclude 子命令组
# ══════════════════════════════════════════════════════════════════════════════

@sync_exclude_app.command("add")
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

    _console.print(f"[green]√[/green] 已将 [bold]{identifier}[/bold] 加入排除名单，同步时将自动跳过")


@sync_exclude_app.command("remove")
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

    _console.print(f"[green]√[/green] 已将 [bold]{identifier}[/bold] 移出排除名单，下次同步将重新纳入")


@sync_exclude_app.command("list")
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


# ══════════════════════════════════════════════════════════════════════════════
# publish / edit / unpublish 命令
# ══════════════════════════════════════════════════════════════════════════════

@app.command("publish")
def publish_skill(
    skill_dir: str = typer.Option(".", "--dir", "-d", help="技能目录，默认为当前目录"),
    title: str | None = typer.Option(None, "--title", help="技能标题（覆盖 SKILL.md frontmatter）"),
    description: str | None = typer.Option(None, "--desc", help="技能详细描述"),
    summary: str | None = typer.Option(None, "--summary", help="一句话简介（列表页展示，最多500字符）"),
    share_type: str = typer.Option(
        SHARE_TYPE_PERSONAL,
        "--share-type",
        help=f"分享权限类型：{'/'.join(SHARE_TYPES)}（默认 personal=仅本人）",
    ),
    tags: str | None = typer.Option(None, "--tags", help="标签，逗号分隔"),
    category_id: int | None = typer.Option(None, "--category", help="分类 ID"),
    changelog: str | None = typer.Option(None, "--changelog", help="本次版本变更说明"),
    depts: str | None = typer.Option(
        None, "--depts",
        help="可见部门，逗号分隔，支持中文名或ID（仅 share-type=department 时生效）。"
             "不传则默认使用发布者所在全部部门。示例：项目二部,项目六部",
    ),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """发布本地 Skill 到技能广场。

    首次发布时创建技能，再次发布时追加新版本。
    技能目录须包含 SKILL.md 和 data/VERSION.json。
    """
    command = "skills publish"

    if share_type not in SHARE_TYPES:
        _emit({
            "success": False, "command": command,
            "error": {"type": "ValueError", "message": f"share-type 必须为 {'/'.join(SHARE_TYPES)}，收到: {share_type!r}"},
        }, json_output)
        raise typer.Exit(1)

    resolved_dir = Path(skill_dir).expanduser().resolve()

    try:
        skill_md_path, version_data = _read_skill_file(resolved_dir)
    except FileNotFoundError as exc:
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    skill_name = version_data.get("name", "")
    if not skill_name:
        _emit({
            "success": False, "command": command,
            "error": {"type": "ValueError", "message": "data/VERSION.json 中 name 字段不能为空"},
        }, json_output)
        raise typer.Exit(1)

    try:
        version = _validate_skill_version_consistency(skill_md_path, version_data)
    except ValueError as exc:
        _emit({
            "success": False, "command": command,
            "error": {"type": "ValueError", "message": str(exc)},
        }, json_output)
        raise typer.Exit(1)

    # 从 SKILL.md frontmatter 读取元数据，CLI 参数优先
    fm = _parse_skill_md_frontmatter(skill_md_path)
    resolved_title      = title or fm.get("title") or skill_name
    resolved_desc       = description or fm.get("description") or ""
    # summary 回退链：CLI 参数 > frontmatter summary > frontmatter description（截断到 500 字符）
    resolved_summary    = summary or fm.get("summary") or _summary_from_desc(fm.get("description"))
    resolved_tags       = tags or fm.get("tags") or ""
    resolved_cat        = category_id or (int(fm["category_id"]) if "category_id" in fm else None)
    resolved_share_type = share_type or fm.get("share_type") or SHARE_TYPE_PERSONAL

    client = MarketplaceClient()

    # 判断是否已存在
    existing = None
    try:
        existing = client.get_my_skill_by_name(skill_name)
    except Exception:
        pass

    # 若未显式传入 category_id，尝试从分类列表中自动匹配最合适的分类
    if resolved_cat is None:
        try:
            all_categories = client.get_categories()
            matched_cat = _match_best_category(
                all_categories,
                skill_name=skill_name,
                title=resolved_title,
                tags=resolved_tags,
                description=resolved_desc,
            )
            if matched_cat:
                resolved_cat = matched_cat["id"]
                if not json_output:
                    _console.print(
                        f"[dim]已自动匹配分类：[bold]{matched_cat.get('name', '')}[/bold] "
                        f"(id={matched_cat['id']}, slug={matched_cat.get('slug', '')})[/dim]"
                    )
        except Exception:
            pass

    zip_path: Path | None = None
    try:
        zip_path = _zip_skill_dir(resolved_dir, skill_name)
        resolved_dept_ids = [d.strip() for d in depts.split(",") if d.strip()] if depts else None

        if existing is None:
            # 首次发布
            fields: dict = {
                "skill_name":  skill_name,
                "title":       resolved_title,
                "description": resolved_desc,
                "summary":     resolved_summary,
                "tags":        resolved_tags,
                "version":     version,
                "share_type":  resolved_share_type,
            }
            if resolved_cat:
                fields["category_id"] = str(resolved_cat)
            if changelog:
                fields["changelog"] = changelog
            if resolved_dept_ids is not None:
                fields["dept_ids"] = resolved_dept_ids

            data = client.create_skill(fields, zip_path)
            action = "created"
        else:
            # 发布新版本：同时同步元数据 + 上传文件 + 创建版本
            skill_id = existing["id"]
            fields = {
                "version":     version,
                "title":       resolved_title,
                "description": resolved_desc,
                "summary":     resolved_summary,
                "tags":        resolved_tags,
                "share_type":  resolved_share_type,
            }
            if resolved_cat:
                fields["category_id"] = str(resolved_cat)
            if changelog:
                fields["changelog"] = changelog
            if resolved_dept_ids is not None:
                fields["dept_ids"] = resolved_dept_ids

            data = client.full_update_skill(skill_id, fields, zip_path)
            if "identifier" not in data:
                data["identifier"] = existing.get("identifier", "")
            action = "version_published"
    except Exception as exc:
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)
    finally:
        if zip_path and zip_path.exists():
            zip_path.unlink(missing_ok=True)

    if json_output:
        _emit({"success": True, "command": command, "data": data, "action": action}, json_output)
        return

    from opscli.skills.marketplace.models import _SHARE_TYPE_LABELS
    identifier = data.get("identifier") or skill_name
    share_label = _SHARE_TYPE_LABELS.get(resolved_share_type, resolved_share_type)
    dept_display = ", ".join(resolved_dept_ids) if resolved_dept_ids else ""

    if action == "created":
        body = (
            f"[green]技能发布成功！[/green]\n\n"
            f"[dim]标识符  [/dim] {identifier}\n"
            f"[dim]版  本  [/dim] {version}\n"
            f"[dim]分享权限[/dim] {share_label}\n"
        )
        if resolved_summary:
            body += f"[dim]一句话  [/dim] {resolved_summary}\n"
        if resolved_share_type == "department" and dept_display:
            body += f"[dim]可见部门[/dim] {dept_display}\n"
        elif resolved_share_type == "department":
            body += "[dim]可见部门[/dim] （全部门，由服务端自动确定）\n"
        body += f"\n[dim]安装命令：[/dim] [green]opscli skills install {identifier}[/green]"
        _console.print(Panel(
            body,
            title="[bold]技能广场 — 发布成功[/bold]",
            border_style="green",
            expand=False,
        ))
    else:
        body = (
            f"[green]新版本发布成功！[/green]\n\n"
            f"[dim]标识符  [/dim] {identifier}\n"
            f"[dim]版  本  [/dim] {version}\n"
            f"[dim]分享权限[/dim] {share_label}\n"
        )
        if resolved_summary:
            body += f"[dim]一句话  [/dim] {resolved_summary}\n"
        if changelog:
            body += f"[dim]变更说明[/dim] {changelog}\n"
        if resolved_share_type == "department" and dept_display:
            body += f"[dim]可见部门[/dim] {dept_display}\n"
        elif resolved_share_type == "department":
            body += "[dim]可见部门[/dim] （全部门，由服务端自动确定）\n"
        _console.print(Panel(
            body,
            title="[bold]技能广场 — 版本发布[/bold]",
            border_style="green",
            expand=False,
        ))


@app.command("edit")
def edit_skill(
    identifier: str = typer.Argument(..., help="技能标识符，如 pengjianchao@ops-auth"),
    skill_dir: str | None = typer.Option(
        None, "--dir", "-d",
        help="技能目录：若指定则打包整目录为 zip 重新上传（同时从 SKILL.md frontmatter 读取元数据）",
    ),
    skill_file: str | None = typer.Option(
        None, "--file", "-f",
        help="直接指定 zip/md 文件路径重新上传（与 --dir 互斥）",
    ),
    title: str | None       = typer.Option(None, "--title",       help="技能标题"),
    description: str | None = typer.Option(None, "--desc",        help="技能详细描述"),
    summary: str | None     = typer.Option(None, "--summary",     help="一句话简介（最多500字符）"),
    share_type: str | None  = typer.Option(None, "--share-type",  help=f"分享权限：{'/'.join(SHARE_TYPES)}"),
    tags: str | None        = typer.Option(None, "--tags",        help="标签，逗号分隔"),
    category_id: int | None = typer.Option(None, "--category",    help="分类 ID"),
    version: str | None     = typer.Option(None, "--version",     help="版本号（如 1.2.0；不传则不变）"),
    changelog: str | None   = typer.Option(None, "--changelog",   help="本次版本变更说明"),
    depts: str | None       = typer.Option(
        None, "--depts",
        help="可见部门，逗号分隔，支持中文名或ID（仅 share-type=department 时生效）。"
             "不传则重置为发布者所在全部部门。示例：项目二部,项目六部",
    ),
    json_output: bool       = typer.Option(False, "--json",       help="输出原始 JSON"),
):
    """编辑已发布的技能信息。

    支持修改任意字段组合，--dir / --file 可选：
    - 不传文件：仅更新元数据和/或版本号
    - 传 --dir ：重新打包整目录上传（推荐，可同时刷新 frontmatter 读取）
    - 传 --file：直接上传指定 zip/md 文件
    """
    command = f"skills edit {identifier}"

    if "@" not in identifier:
        _console.print(f"[red]错误：标识符格式应为 username@skill_name，收到: {identifier!r}[/red]")
        raise typer.Exit(1)

    if skill_dir and skill_file:
        _console.print("[red]错误：--dir 和 --file 不能同时使用[/red]")
        raise typer.Exit(1)

    if share_type and share_type not in SHARE_TYPES:
        _console.print(f"[red]错误：share-type 必须为 {'/'.join(SHARE_TYPES)}，收到: {share_type!r}[/red]")
        raise typer.Exit(1)

    username, skill_name_str = identifier.split("@", 1)

    # ── 解析文件来源 ────────────────────────────────────────
    zip_path: Path | None = None
    _auto_zip = False

    if skill_dir:
        resolved_dir = Path(skill_dir).expanduser().resolve()
        try:
            skill_md_path, version_data = _read_skill_file(resolved_dir)
        except FileNotFoundError as exc:
            _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
            raise typer.Exit(1)

        fm = _parse_skill_md_frontmatter(skill_md_path)
        title       = title       or fm.get("title")
        description = description or fm.get("description")
        # summary 回退链：CLI 参数 > frontmatter summary > frontmatter description（截断到 500 字符）
        summary     = summary     or fm.get("summary") or _summary_from_desc(fm.get("description"))
        share_type  = share_type  or fm.get("share_type")
        tags        = tags        or fm.get("tags")
        if category_id is None and "category_id" in fm:
            category_id = int(fm["category_id"])
        try:
            ver_from_file = _validate_skill_version_consistency(skill_md_path, version_data, version)
        except ValueError as exc:
            _emit({
                "success": False, "command": command,
                "error": {"type": "ValueError", "message": str(exc)},
            }, json_output)
            raise typer.Exit(1)
        if version is None:
            version = ver_from_file

        try:
            zip_path  = _zip_skill_dir(resolved_dir, skill_name_str)
            _auto_zip = True
        except Exception as exc:
            _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
            raise typer.Exit(1)

    elif skill_file:
        zip_path = Path(skill_file).expanduser().resolve()
        if not zip_path.exists():
            _emit({
                "success": False, "command": command,
                "error": {"type": "FileNotFoundError", "message": f"文件不存在：{zip_path}"},
            }, json_output)
            raise typer.Exit(1)
        if zip_path.suffix.lower() != ".zip":
            _emit({
                "success": False, "command": command,
                "error": {"type": "ValueError", "message": "--file 仅支持 zip 目录型 Skill 包，且包内必须包含 SKILL.md 与 data/VERSION.json"},
            }, json_output)
            raise typer.Exit(1)
        try:
            ver_from_file = _validate_zip_skill_version_consistency(zip_path, version)
        except Exception as exc:
            _emit({
                "success": False, "command": command,
                "error": {"type": exc.__class__.__name__, "message": str(exc)},
            }, json_output)
            raise typer.Exit(1)
        if version is None:
            version = ver_from_file

    if version and zip_path is None:
        _emit({
            "success": False, "command": command,
            "error": {"type": "ValueError", "message": "禁止只修改版本号：发布新版本必须同时传 --dir 或 --file 上传对应 zip 包"},
        }, json_output)
        raise typer.Exit(1)

    # ── 获取技能 ID ──────────────────────────────────────────
    client = MarketplaceClient()
    try:
        skill_data = client.get_by_identifier(username, skill_name_str)
    except Exception as exc:
        if zip_path and _auto_zip:
            zip_path.unlink(missing_ok=True)
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    skill_id = skill_data.get("id")
    current_version = skill_data.get("latest_version", "")

    # 若未显式传入 category_id，尝试自动匹配最合适的分类
    if category_id is None:
        try:
            _match_title = title or skill_data.get("title", skill_name_str)
            _match_tags  = tags or skill_data.get("tags", "")
            _match_desc  = description or skill_data.get("description", "")
            all_categories = client.get_categories()
            matched_cat = _match_best_category(
                all_categories,
                skill_name=skill_name_str,
                title=_match_title,
                tags=_match_tags,
                description=_match_desc,
            )
            if matched_cat:
                category_id = matched_cat["id"]
                if not json_output:
                    _console.print(
                        f"[dim]已自动匹配分类：[bold]{matched_cat.get('name', '')}[/bold] "
                        f"(id={matched_cat['id']}, slug={matched_cat.get('slug', '')})[/dim]"
                    )
        except Exception:
            pass

    # ── 构造请求字段 ─────────────────────────────────────────
    fields: dict = {}
    if title:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if summary is not None:
        fields["summary"] = summary
    if share_type:
        fields["share_type"] = share_type
    if tags is not None:
        fields["tags"] = tags
    if category_id is not None:
        fields["category_id"] = str(category_id)
    if version:
        fields["version"] = version
    if changelog:
        fields["changelog"] = changelog
    resolved_dept_ids = [d.strip() for d in depts.split(",") if d.strip()] if depts else None
    if resolved_dept_ids is not None:
        fields["dept_ids"] = resolved_dept_ids

    if not fields and zip_path is None:
        _console.print("[yellow]未指定任何修改内容，操作跳过。[/yellow]")
        raise typer.Exit(0)

    # ── 调用 API ─────────────────────────────────────────────
    try:
        data = client.full_update_skill(skill_id, fields, zip_path)
    except Exception as exc:
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)
    finally:
        if zip_path and _auto_zip:
            zip_path.unlink(missing_ok=True)

    if json_output:
        _emit({"success": True, "command": command, "data": data}, json_output)
        return

    from opscli.skills.marketplace.models import _SHARE_TYPE_LABELS
    new_share  = data.get("share_type", share_type or skill_data.get("share_type", ""))
    share_lbl  = _SHARE_TYPE_LABELS.get(new_share, new_share)
    new_ver    = data.get("latest_version", version or current_version)

    lines = ["[green]技能信息更新成功！[/green]", ""]
    lines.append(f"[dim]标识符  [/dim] {identifier}")
    lines.append(f"[dim]版  本  [/dim] {new_ver}")
    lines.append(f"[dim]分享权限[/dim] {share_lbl}")
    if zip_path:
        lines.append("[dim]文件    [/dim] 已重新上传 √")
    if new_share == "department":
        dept_display = ", ".join(resolved_dept_ids) if resolved_dept_ids else "（全部门，由服务端自动确定）"
        lines.append(f"[dim]可见部门[/dim] {dept_display}")
    _console.print(Panel(
        "\n".join(lines),
        title="[bold]技能广场 — 编辑成功[/bold]",
        border_style="green",
        expand=False,
    ))


@app.command("unpublish")
def unpublish_skill(
    identifier: str = typer.Argument(..., help="技能标识符，如 pengjianchao@ops-auth"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认提示"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
):
    """下架已发布的技能（软删除，可联系管理员恢复）。"""
    command = f"skills unpublish {identifier}"

    if "@" not in identifier:
        _console.print(f"[red]错误：标识符格式应为 username@skill_name，收到: {identifier!r}[/red]")
        raise typer.Exit(1)

    username, skill_name = identifier.split("@", 1)

    if not force and not json_output:
        confirm = typer.confirm(f"确认下架技能 [bold]{identifier}[/bold]？下架后广场用户将无法搜索或安装。")
        if not confirm:
            _console.print("[yellow]已取消[/yellow]")
            raise typer.Exit(0)

    client = MarketplaceClient()

    try:
        skill_data = client.get_by_identifier(username, skill_name)
    except Exception as exc:
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    skill_id = skill_data.get("id")

    try:
        client.delete_skill(skill_id)
    except Exception as exc:
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    if json_output:
        _emit({"success": True, "command": command, "data": {"identifier": identifier}}, json_output)
        return

    _console.print(f"[green]已下架技能 [bold]{identifier}[/bold][/green]")
    _console.print("[dim]注意：已安装到本地的技能不受影响，仅对广场新用户生效。[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
# 主命令：list / install / status / link / unlink / report-usage / upgrade
# ══════════════════════════════════════════════════════════════════════════════

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
    name: str | None = typer.Argument(None, help="Skill 名称或远程标识符（如 pengjianchao@ops-auth）"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定安装目录"),
    runtime: str | None = typer.Option(None, "--runtime", help="claude、openclaw、auwork、all，或逗号分隔多个值"),
    force: bool = typer.Option(False, "--force", help="覆盖已存在目录"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认，自动全选所有 Skills 和检测到的 AI 工具"),
    version: str | None = typer.Option(None, "--version", help="安装指定版本（仅远程安装有效）"),
    sync_market: bool = typer.Option(False, "--sync-market", help="从市场安装记录同步：补装缺失 + 升级旧版"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览同步计划，不实际安装（需配合 --sync-market）"),
    share_code: str | None = typer.Option(None, "--share-code", help="分享码，绕过 personal/department 权限限制安装广场技能"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """安装 Skill 到本地目录。

    \b
    - 不指定 NAME 时进入 TUI 交互模式，可多选 Skills 和安装目标。
    - NAME 不含 @ 时从内置模板安装（如 ops-auth）。
    - NAME 含 @ 时从技能广场远程安装（如 pengjianchao@ops-auth）。
    - --sync-market 从市场安装记录同步，补装缺失 + 升级旧版（不能与 NAME 同时使用）。
    - --dry-run 配合 --sync-market 仅预览同步计划，不实际安装。

    加 --yes / -y 可跳过确认，直接安装全部到所有检测到的工具。
    """
    # ── --sync-market 模式 ─────────────────────────────────
    if sync_market:
        if name is not None:
            _console.print("[red]错误：--sync-market 不能与指定 NAME 同时使用[/red]")
            raise typer.Exit(1)
        if version is not None:
            _console.print("[red]错误：--sync-market 模式下版本由市场决定，请勿指定 --version[/red]")
            raise typer.Exit(1)
        _install_sync_market(
            skills_dir=skills_dir,
            runtime=runtime,
            dry_run=dry_run,
            pretty=pretty,
        )
        return

    manager = SkillsManager()
    # 显式指定 --runtime auwork 但 ~/.auwork 下无纯数字用户目录时，提示已跳过
    # （AuWork 客户端尚未登录过，无法凭空知道用户 ID）
    if runtime and "auwork" in [r.strip().lower() for r in runtime.split(",")]:
        if not manager.detector._auwork_targets():
            _console.print("[dim]未发现 AuWork 用户目录（~/.auwork 下无纯数字子目录），已跳过 AuWork 安装[/dim]")
    try:
        if name is None:
            _install_interactive(manager, skills_dir=skills_dir, runtime=runtime, force=force, yes=yes, pretty=pretty)
            return

        # 远程广场安装（标识符含 @）；远程安装默认直接覆盖，无需 --force
        if "@" in name:
            payload = install_remote_skill(
                identifier=name,
                version=version,
                skills_dir=skills_dir,
                runtime=runtime,
                force=True,
                share_code=share_code,
            )
            _emit(payload, pretty)
            if not payload.get("success"):
                raise typer.Exit(1)
            return

        # 本地内置模板安装
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
    except typer.Exit:
        raise
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


@app.command("link")
def link_skill(
    name: str = typer.Argument(..., help="Skill 名称"),
    runtime: str | None = typer.Option(None, "--runtime", help="claude、openclaw、all，或逗号分隔多个值"),
    force: bool = typer.Option(False, "--force", help="覆盖已有链接"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """将中央存储中的 Skill 链接到 AI 工具的 skills 目录。

    适用场景：安装新 AI 工具后，把已有 Skill 接入该工具。
    """
    manager = SkillsManager()
    try:
        central_skill_dir = get_central_skills_dir() / name
        if not central_skill_dir.exists():
            raise ValueError(
                f"中央存储中未找到 Skill: {name}\n"
                f"请先执行 opscli skills install {name}"
            )

        runtime_list = [r.strip() for r in runtime.split(",") if r.strip()] if runtime else None
        targets = manager.detector.detect_install_targets(preferred_runtimes=runtime_list)

        version = manager._read_version(central_skill_dir)
        installs = []
        for target_runtime, tool_skills_dir in targets:
            link_result = manager.linker.link(name, central_skill_dir, tool_skills_dir, force=force)
            manager._record_install(
                name, link_result.link_path, target_runtime,
                central_dir=central_skill_dir, link_method=link_result.method,
            )
            installs.append({
                "tool": runtime_to_tool_name(target_runtime),
                "path": str(link_result.link_path),
                "method": link_result.method,
                "replaced": link_result.replaced,
            })
            action = "↑" if link_result.replaced else "√"
            label = _TOOL_LABELS.get(target_runtime, target_runtime)
            _console.print(f"  [green]{action}[/green] [bold]{name}[/bold] → [cyan]{label}[/cyan] [dim]({link_result.link_path})[/dim]")

        payload = {
            "success": True,
            "command": "skills link",
            "data": {"name": name, "version": version, "central_path": str(central_skill_dir), "links": installs},
            "error": None,
        }
    except Exception as exc:
        payload = {
            "success": False,
            "command": "skills link",
            "data": None,
            "error": error_to_dict(exc),
        }
        _emit(payload, pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("unlink")
def unlink_skill(
    name: str = typer.Argument(..., help="Skill 名称"),
    runtime: str | None = typer.Option(None, "--runtime", help="指定工具（不指定则移除所有工具的链接）"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """移除 AI 工具 skills 目录中的 Skill 链接（不删除中央存储内容）。"""
    manager = SkillsManager()
    try:
        runtime_list = [r.strip() for r in runtime.split(",") if r.strip()] if runtime else None
        targets = manager.detector.detect_install_targets(preferred_runtimes=runtime_list)

        removed = []
        skipped = []
        for target_runtime, tool_skills_dir in targets:
            link_path = tool_skills_dir / name
            ok = manager.linker.unlink(link_path)
            label = _TOOL_LABELS.get(target_runtime, target_runtime)
            if ok:
                removed.append({"tool": runtime_to_tool_name(target_runtime), "path": str(link_path)})
                _console.print(f"  [green]√[/green] 已移除 [bold]{name}[/bold] 的链接（{label}）")
            else:
                skipped.append({"tool": runtime_to_tool_name(target_runtime), "path": str(link_path)})
                _console.print(f"  [dim]- {name} 在 {label} 中不存在，跳过[/dim]")

        payload = {
            "success": True,
            "command": "skills unlink",
            "data": {"name": name, "removed": removed, "skipped": skipped},
            "error": None,
        }
    except Exception as exc:
        payload = {
            "success": False,
            "command": "skills unlink",
            "data": None,
            "error": error_to_dict(exc),
        }
        _emit(payload, pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("report-usage")
def report_usage(
    identifier: str = typer.Argument(..., help="Skill 标识符（username@skill_name 或纯 skill_name，如 ops-auth）"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """直接上报一次 Skill 使用记录到服务端（不经过本地队列）。

    \b
    identifier 支持两种格式：
      - 完整标识符：username@skill_name，如 pengjianchao@ops-auth
      - 纯 skill_name：如 ops-auth（适用于 Hook 自动上报场景）
    """
    from datetime import datetime, timezone

    from opscli.skills.marketplace.usage_reporter import _get_client_id

    record = {
        "identifier": identifier,
        "used_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "client_id": _get_client_id(),
    }
    try:
        result = MarketplaceClient().batch_usage([record])
        payload = {
            "success": True,
            "command": "skills report-usage",
            "data": {"reported": True, "identifier": identifier, "result": result},
            "error": None,
        }
    except Exception as exc:
        payload = {
            "success": False,
            "command": "skills report-usage",
            "data": {"reported": False, "identifier": identifier},
            "error": error_to_dict(exc),
        }
        _emit(payload, pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


def _is_auth_failure(exc: BaseException) -> bool:
    """判断异常是否属于认证类失败（可通过重新登录恢复）。

    覆盖两类信号：
    - 预检未登录：SkillRemoteError 由 AuthError 包装而来（本地无凭证）
    - 执行中鉴权失效：HTTP/业务 401，或业务 407（服务端 session 已登出，
      本地凭证看似有效——长时间未使用的典型场景）
    """
    if not isinstance(exc, SkillRemoteError):
        return False
    if isinstance(exc.__cause__, AuthError):
        return True
    return exc.status_code in (401, 407)


def _stdin_is_tty() -> bool:
    """判断 stdin 是否为交互终端（独立函数便于测试打桩）。"""
    return sys.stdin.isatty()


def _prompt_and_login(progress: Console) -> bool:
    """交互终端下询问用户是否登录，同意则内联执行 Device Flow 登录。

    非交互环境（stdin 非 TTY，如 AI Agent / 管道 / self-update 子进程）
    直接返回 False，绝不发起会阻塞等待浏览器授权的登录流程。
    登录只给一次机会：失败（超时/拒绝/网络）不重试，返回 False 走原失败路径。

    Returns:
        True 表示登录成功、调用方可自动重试一次；False 表示保持原失败行为。
    """
    if not _stdin_is_tty():
        return False
    # 询问输出到 stderr（err=True），避免污染 stdout 的 JSON 结果
    if not typer.confirm("检测到未登录或登录已失效，是否现在登录 ops？", default=False, err=True):
        return False
    try:
        # 复用 auth login 命令的完整流程（打开浏览器 + 轮询授权 + 同步系统列表）
        from opscli.auth.cli import login as _auth_login

        _auth_login()
    except typer.Exit:
        # 登录命令内部失败（Device Flow 超时/用户拒绝）以 typer.Exit 退出，
        # 此处转为"登录失败"信号，交由调用方按原失败路径处理
        progress.print("[yellow]登录未完成，本次升级保持失败状态[/yellow]")
        return False
    return True


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
        try:
            result = manager.upgrade(name=name, skills_dir=skills_dir, force=force, on_step=on_step)
        except Exception as exc:
            # 认证类失败且用户在交互终端完成登录时，自动重试一次；
            # 其余情况（非交互 / 拒绝 / 登录失败 / 非认证错误）按原失败路径处理
            if _is_auth_failure(exc) and _prompt_and_login(_progress):
                result = manager.upgrade(name=name, skills_dir=skills_dir, force=force, on_step=on_step)
            else:
                raise
        _progress.print("[bold green]升级完成[/bold green]\n")
        payload = {
            "success": True,
            "command": "skills upgrade",
            "data": result.to_dict(),
            "error": None,
        }
    except Exception as exc:
        _progress.print("[bold red]升级失败[/bold red]\n")
        payload = {
            "success": False,
            "command": "skills upgrade",
            "data": None,
            "error": error_to_dict(exc),
        }
        _emit(payload, pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)
