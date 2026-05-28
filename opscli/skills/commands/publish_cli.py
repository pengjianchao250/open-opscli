"""Skills Publish 子命令组。

提供 opscli skills publish / edit / unpublish 命令：
  publish    — 发布本地 Skill 到技能广场（首次创建或新增版本）
  edit       — 编辑已发布技能（元数据 + 可选重传 zip + 可选版本变更）
  unpublish  — 下架已发布的技能（软删除）
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from opscli.skills.domain.exceptions import error_to_dict
from opscli.skills.marketplace.client import MarketplaceClient
from opscli.skills.marketplace.models import SHARE_TYPES, SHARE_TYPE_PERSONAL

app = typer.Typer(help="发布 / 下架技能到广场")
_console = Console()


def _emit(payload: dict, pretty: bool) -> None:
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


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

    打包规则：
    - 目录内所有文件，arcname 相对于 skill_dir
    - 排除 __pycache__、*.pyc、*.pyo
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

    匹配策略：
    - 将 skill_name、title、tags、description 拆分为小写关键词
    - 遍历所有分类，统计关键词与 slug/name 的匹配得分
    - 直接包含（整体子串）得 2 分，slug 单词粒度子串匹配得 1 分
    - 得分为 0 时返回 None（无有效匹配）
    """
    if not categories:
        return None

    def tokenize(s: str) -> list[str]:
        """拆分为小写词列表，去掉常见分隔符。"""
        return [w.lower() for w in s.replace("-", " ").replace(",", " ").replace("，", " ").split() if w]

    # 构建所有关键词（描述只取前 200 字，避免噪声过多）
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
        # slug 按 "-" 拆分为单词列表，用于粒度更细的子串匹配
        slug_words = slug.split("-") if slug else []
        score = 0

        for kw in keywords:
            # 整体子串命中 slug 或 name，得 2 分
            if kw in slug or kw in name:
                score += 2
            # 对 slug 的每个分词做子串匹配，得 1 分（避免与上一条重复计分）
            else:
                for sw in slug_words:
                    if sw and (kw == sw or kw in sw or sw in kw):
                        score += 1
                        break  # 同一关键词只对该分类得 1 次

        if score > best_score:
            best_score = score
            best_cat = cat

    return best_cat if best_score > 0 else None


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


# ──────────────────────────────────────────
# publish
# ──────────────────────────────────────────

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

    # 校验 share_type
    if share_type not in SHARE_TYPES:
        _emit({
            "success": False, "command": command,
            "error": {"type": "ValueError", "message": f"share-type 必须为 {'/'.join(SHARE_TYPES)}，收到: {share_type!r}"},
        }, json_output)
        raise typer.Exit(1)

    resolved_dir = Path(skill_dir).expanduser().resolve()

    # 读取本地文件
    try:
        skill_md_path, version_data = _read_skill_file(resolved_dir)
    except FileNotFoundError as exc:
        _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
        raise typer.Exit(1)

    skill_name = version_data.get("name", "")
    version = version_data.get("version", "1.0.0").lstrip("v")
    if not skill_name:
        _emit({
            "success": False, "command": command,
            "error": {"type": "ValueError", "message": "data/VERSION.json 中 name 字段不能为空"},
        }, json_output)
        raise typer.Exit(1)

    # 从 SKILL.md frontmatter 读取元数据，CLI 参数优先
    fm = _parse_skill_md_frontmatter(skill_md_path)
    resolved_title      = title or fm.get("title") or skill_name
    resolved_desc       = description or fm.get("description") or ""
    resolved_summary    = summary or fm.get("summary") or ""
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
            # 获取分类失败时静默跳过，不阻断发布主流程
            pass

    # 打包整个目录为 zip
    zip_path: Path | None = None
    try:
        zip_path = _zip_skill_dir(resolved_dir, skill_name)

        # 解析部门列表
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
            # 发布新版本：使用 full_update_skill 同时同步元数据 + 上传文件 + 创建版本
            # （publish_version 只接受 version/changelog，不接受元数据字段）
            skill_id = existing["id"]
            fields: dict = {
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
            # full_update_skill 返回技能数据，补充 identifier
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

    identifier = data.get("identifier") or f"{skill_name}"

    # 分享类型标签（复用 models 中的映射）
    from opscli.skills.marketplace.models import _SHARE_TYPE_LABELS
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
            body += f"[dim]可见部门[/dim] （全部门，由服务端自动确定）\n"
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
            body += f"[dim]可见部门[/dim] （全部门，由服务端自动确定）\n"
        _console.print(Panel(
            body,
            title="[bold]技能广场 — 版本发布[/bold]",
            border_style="green",
            expand=False,
        ))


# ──────────────────────────────────────────
# edit
# ──────────────────────────────────────────

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
    title: str | None      = typer.Option(None, "--title",       help="技能标题"),
    description: str | None= typer.Option(None, "--desc",        help="技能详细描述"),
    summary: str | None    = typer.Option(None, "--summary",     help="一句话简介（最多500字符）"),
    share_type: str | None = typer.Option(None, "--share-type",  help=f"分享权限：{'/'.join(SHARE_TYPES)}"),
    tags: str | None       = typer.Option(None, "--tags",        help="标签，逗号分隔"),
    category_id: int | None= typer.Option(None, "--category",    help="分类 ID"),
    version: str | None    = typer.Option(None, "--version",     help="版本号（如 1.2.0；不传则不变）"),
    changelog: str | None  = typer.Option(None, "--changelog",   help="本次版本变更说明"),
    depts: str | None      = typer.Option(
        None, "--depts",
        help="可见部门，逗号分隔，支持中文名或ID（仅 share-type=department 时生效）。"
             "不传则重置为发布者所在全部部门。示例：项目二部,项目六部",
    ),
    json_output: bool      = typer.Option(False, "--json",       help="输出原始 JSON"),
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

    # ── 解析文件来源 ────────────────────────────────
    zip_path: Path | None = None
    _auto_zip = False  # 是否为自动打包（需要后续删除临时文件）

    if skill_dir:
        resolved_dir = Path(skill_dir).expanduser().resolve()
        # 从目录的 SKILL.md frontmatter 读取默认元数据
        try:
            skill_md_path, version_data = _read_skill_file(resolved_dir)
        except FileNotFoundError as exc:
            _emit({"success": False, "command": command, "error": error_to_dict(exc)}, json_output)
            raise typer.Exit(1)

        fm = _parse_skill_md_frontmatter(skill_md_path)
        # CLI 参数优先，frontmatter 兜底
        title       = title       or fm.get("title")
        description = description or fm.get("description")
        summary     = summary     or fm.get("summary")
        share_type  = share_type  or fm.get("share_type")
        tags        = tags        or fm.get("tags")
        if category_id is None and "category_id" in fm:
            category_id = int(fm["category_id"])
        if version is None:
            ver_from_file = version_data.get("version", "").lstrip("v")
            if ver_from_file:
                version = ver_from_file

        # 打包整目录
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

    # ── 获取技能 ID ──────────────────────────────────
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
            # 从 API 返回数据或命令行参数提取用于匹配的信息
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
            # 获取分类失败时静默跳过，不阻断编辑主流程
            pass

    # ── 构造请求字段 ─────────────────────────────────
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

    # ── 调用 API ─────────────────────────────────────
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
        lines.append(f"[dim]文件    [/dim] 已重新上传 ✓")
    if new_share == "department":
        dept_display = ", ".join(resolved_dept_ids) if resolved_dept_ids else "（全部门，由服务端自动确定）"
        lines.append(f"[dim]可见部门[/dim] {dept_display}")
    _console.print(Panel(
        "\n".join(lines),
        title="[bold]技能广场 — 编辑成功[/bold]",
        border_style="green",
        expand=False,
    ))


# ──────────────────────────────────────────
# unpublish
# ──────────────────────────────────────────

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

    # 先获取 skill_id
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
