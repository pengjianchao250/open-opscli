"""ops-skill-sync 核心脚本。

提供 scan 和 sync 两个子命令，实现同机跨 AI 工具的 Skill 目录同步。
文件操作策略：macOS/Linux 使用符号链接，Windows 优先 Directory Junction，
降级时使用 shutil.copytree 完整复制。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import NoReturn


# ─────────────────────────────────────────────────────────────
# 工具路径注册表
# 与 opscli SkillDetector 保持一致，统一使用 Path.home() 构建路径
# ─────────────────────────────────────────────────────────────

def _opencode_skills_dir() -> Path:
    """OpenCode 的 Skills 目录（所有平台统一为 ~/.config/opencode/skills/）。"""
    return Path.home() / ".config" / "opencode" / "skills"


# 工具标识 → (配置根目录, skills子目录) 映射
_TOOL_REGISTRY: dict[str, tuple[Path, Path]] = {
    "claude":    (Path.home() / ".claude",            Path.home() / ".claude"    / "skills"),
    "openclaw":  (Path.home() / ".openclaw",          Path.home() / ".openclaw"  / "skills"),
    "codex":     (Path.home() / ".codex",             Path.home() / ".codex"     / "skills"),
    "opencode":  (Path.home() / ".config" / "opencode", _opencode_skills_dir()),
    "workbuddy": (Path.home() / ".workbuddy",         Path.home() / ".workbuddy" / "skills"),
    "trae-cn":   (Path.home() / ".trae-cn",           Path.home() / ".trae-cn"   / "skills"),
}

# 工具对应的可执行命令名（用于 which 检测）
_TOOL_COMMANDS: dict[str, str] = {
    "claude":    "claude",
    "openclaw":  "openclaw",
    "codex":     "codex",
    "opencode":  "opencode",
    "workbuddy": "workbuddy",
    "trae-cn":   "trae",
}


# ─────────────────────────────────────────────────────────────
# 工具检测
# ─────────────────────────────────────────────────────────────

def _is_tool_detected(tool: str) -> bool:
    """检测 AI 工具是否已安装（配置目录存在 或 命令可用）。"""
    config_dir, _ = _TOOL_REGISTRY[tool]
    if config_dir.exists():
        return True
    cmd = _TOOL_COMMANDS.get(tool)
    if cmd and shutil.which(cmd) is not None:
        return True
    return False



# ─────────────────────────────────────────────────────────────
# Skill 扫描
# ─────────────────────────────────────────────────────────────

def _scan_skills_in_dir(skills_dir: Path, *, scan_type: str = "opscli") -> list[dict]:
    """扫描指定目录下已安装的 Skills。

    scan_type 控制识别范围：
    - "opscli"（默认）：只识别带 data/VERSION.json 的 opscli 规范 Skill
    - "all"           ：额外识别只有 SKILL.md 的 superpowers 类 Skill

    识别优先级：
    1. data/VERSION.json 存在 → 读取版本号（两种 type 均识别）
    2. data/ 目录存在但无 VERSION.json → 版本 v0.0.0（两种 type 均识别）
    3. SKILL.md 存在且无 data/ 目录 → 版本 unknown（仅 type=all 识别）
    4. 以上均无 → 跳过

    解析失败时静默跳过，不中断整体扫描。
    """
    skills: list[dict] = []
    if not skills_dir.exists():
        return skills

    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        version_file = skill_dir / "data" / "VERSION.json"
        data_dir = skill_dir / "data"
        skill_md = skill_dir / "SKILL.md"

        if version_file.exists():
            # 正常情况：读取版本号
            try:
                payload = json.loads(version_file.read_text(encoding="utf-8"))
                version = str(payload.get("version", "unknown"))
            except Exception:
                continue
        elif data_dir.exists():
            # data/ 存在但缺 VERSION.json（安装后从未升级）
            version = "v0.0.0"
        elif skill_md.exists() and scan_type == "all":
            # superpowers 类 Skill：只有 SKILL.md，仅 --type all 时识别
            version = "unknown"
        else:
            continue

        skills.append({"name": skill_dir.name, "version": version})

    return skills


def cmd_scan(args: argparse.Namespace) -> None:
    """scan 子命令：扫描各 AI 工具下已安装的 Skills，输出 JSON。"""
    # 确定要扫描的工具列表
    if args.tool:
        # 验证用户指定的工具名是否合法
        if args.tool not in _TOOL_REGISTRY:
            result = {
                "success": False,
                "command": "skill-sync scan",
                "data": None,
                "error": {
                    "type": "ValueError",
                    "message": f"未知工具: {args.tool}，支持的工具: {', '.join(_TOOL_REGISTRY)}",
                },
            }
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(1)
        tools_to_scan = [args.tool]
    else:
        # 未指定时扫描全部工具
        tools_to_scan = list(_TOOL_REGISTRY.keys())

    tool_results: list[dict] = []
    for tool in tools_to_scan:
        _, skills_dir = _TOOL_REGISTRY[tool]
        detected = _is_tool_detected(tool)
        skills = _scan_skills_in_dir(skills_dir, scan_type=args.type) if detected else []
        tool_results.append({
            "tool":       tool,
            "skills_dir": str(skills_dir),
            "detected":   detected,
            "skills":     skills,
        })

    result = {
        "success": True,
        "command": "skill-sync scan",
        "data":    {"tools": tool_results},
        "error":   None,
    }
    print(json.dumps(result, ensure_ascii=False))


# ─────────────────────────────────────────────────────────────
# 文件链接操作（跨平台）
# ─────────────────────────────────────────────────────────────

def _safe_remove(path: Path) -> None:
    """安全删除链接或目录，避免误删 Junction 指向的源内容。

    策略：
      - Unix symlink        : path.unlink()（只删链接本身）
      - Windows Junction / 空目录 : os.rmdir()（不递归目标）
      - 普通目录             : shutil.rmtree()
    """
    if sys.platform != "win32" and path.is_symlink():
        path.unlink()
        return

    if sys.platform == "win32":
        # 先尝试 rmdir，成功则为 Junction 或空目录，不会删目标内容
        try:
            os.rmdir(str(path))
            return
        except OSError:
            pass
        # rmdir 失败说明是有内容的普通目录
        shutil.rmtree(path)
    else:
        # Unix 非 symlink（普通目录）
        shutil.rmtree(path)


def _create_link(source: Path, link: Path) -> str:
    """创建链接并返回实际使用的方式（symlink / junction / copy_fallback）。

    macOS/Linux 使用标准符号链接；
    Windows 优先创建 Directory Junction（无需管理员权限），失败时降级复制。
    """
    if sys.platform == "win32":
        try:
            # Directory Junction：普通用户权限即可创建
            os.symlink(source, link, target_is_directory=True)
            return "junction"
        except OSError:
            # 受限环境降级为完整复制
            shutil.copytree(
                source,
                link,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            return "copy_fallback"
    else:
        os.symlink(source, link)
        return "symlink"


def _sync_one(
    skill_name: str,
    source_skills_dir: Path,
    target_skills_dir: Path,
    target_tool: str,
) -> dict:
    """将单个 Skill 从来源目录同步到目标目录，返回单条结果字典。

    目标已存在时直接覆盖（先删后建），无需 --force 确认。
    """
    source_skill_dir = source_skills_dir / skill_name
    target_skill_dir = target_skills_dir / skill_name

    # 验证来源 Skill 目录存在且合法
    if not source_skill_dir.exists():
        return {
            "skill":       skill_name,
            "target_tool": target_tool,
            "target_path": str(target_skill_dir),
            "method":      None,
            "replaced":    False,
            "success":     False,
            "error":       f"来源 Skill 目录不存在: {source_skill_dir}",
        }

    replaced = False

    # 删除目标已有内容（覆盖模式）
    if target_skill_dir.exists() or target_skill_dir.is_symlink():
        _safe_remove(target_skill_dir)
        replaced = True

    # 确保目标父目录存在
    target_skills_dir.mkdir(parents=True, exist_ok=True)

    # 创建链接
    try:
        method = _create_link(source_skill_dir, target_skill_dir)
    except Exception as exc:
        return {
            "skill":       skill_name,
            "target_tool": target_tool,
            "target_path": str(target_skill_dir),
            "method":      None,
            "replaced":    replaced,
            "success":     False,
            "error":       str(exc),
        }

    return {
        "skill":       skill_name,
        "target_tool": target_tool,
        "target_path": str(target_skill_dir),
        "method":      method,
        "replaced":    replaced,
        "success":     True,
        "error":       None,
    }


# ─────────────────────────────────────────────────────────────
# sync 子命令
# ─────────────────────────────────────────────────────────────

def cmd_sync(args: argparse.Namespace) -> None:
    """sync 子命令：将 Skills 从来源目录同步到目标 AI 工具目录，输出 JSON。"""

    # ── 解析来源 ──────────────────────────────────────────────
    if args.from_dir:
        # 用户显式指定来源路径
        source_skills_dir = Path(args.from_dir).expanduser()
        source_tool_label = str(source_skills_dir)
        source_info = {"tool": "custom", "skills_dir": str(source_skills_dir)}
    elif args.from_tool:
        # 用户指定来源工具名
        if args.from_tool not in _TOOL_REGISTRY:
            _exit_error(
                "skill-sync sync",
                f"未知来源工具: {args.from_tool}，支持的工具: {', '.join(_TOOL_REGISTRY)}",
            )
        _, source_skills_dir = _TOOL_REGISTRY[args.from_tool]
        source_tool_label = args.from_tool
        source_info = {"tool": args.from_tool, "skills_dir": str(source_skills_dir)}
    else:
        # 自动检测：取第一个有 Skills 的工具作为来源
        source_skills_dir, source_tool_label = _auto_detect_source()
        source_info = {"tool": source_tool_label, "skills_dir": str(source_skills_dir)}

    # 验证来源目录存在
    if not source_skills_dir.exists():
        _exit_error("skill-sync sync", f"来源 skills 目录不存在: {source_skills_dir}")

    # ── 解析目标 ──────────────────────────────────────────────
    if args.to_dir:
        # 用户显式指定目标路径（单目标）
        targets: list[tuple[str, Path]] = [
            ("custom", Path(args.to_dir).expanduser())
        ]
    elif args.to:
        # 用户指定目标工具名（逗号分隔，支持多个）
        targets = _resolve_tool_targets(args.to.split(","))
    else:
        # 自动检测所有已安装工具，排除来源工具自身
        targets = _auto_detect_targets(exclude_tool=source_tool_label)

    if not targets:
        _exit_error("skill-sync sync", "未检测到可用的目标 AI 工具，请通过 --to 或 --to-dir 手动指定")

    # ── 确定要同步的 Skill 列表 ───────────────────────────────
    if args.skills:
        # 用户指定了具体 Skill 名
        skill_names = [s.strip() for s in args.skills.split(",") if s.strip()]
    else:
        # 扫描来源目录，同步全部有效 Skill
        skill_names = [s["name"] for s in _scan_skills_in_dir(source_skills_dir, scan_type=args.type)]

    if not skill_names:
        _exit_error("skill-sync sync", f"来源目录 {source_skills_dir} 中未找到任何有效 Skill")

    # ── 执行同步 ──────────────────────────────────────────────
    all_results: list[dict] = []
    for skill_name in skill_names:
        for target_tool, target_skills_dir in targets:
            # 跳过来源工具自身（路径相同时跳过）
            if target_skills_dir.resolve() == source_skills_dir.resolve():
                continue
            record = _sync_one(skill_name, source_skills_dir, target_skills_dir, target_tool)
            all_results.append(record)

    # 汇总统计
    success_count = sum(1 for r in all_results if r["success"])
    failed_count = len(all_results) - success_count

    result = {
        "success": failed_count == 0,
        "command": "skill-sync sync",
        "data": {
            "from":    source_info,
            "results": all_results,
            "summary": {
                "total":   len(all_results),
                "success": success_count,
                "failed":  failed_count,
            },
        },
        "error": None if failed_count == 0 else {
            "type":    "PartialFailure",
            "message": f"{failed_count} 个同步操作失败，详见 data.results",
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    if failed_count > 0:
        sys.exit(1)


# ─────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────

def _auto_detect_source() -> tuple[Path, str]:
    """自动检测来源：遍历已检测到的工具，返回第一个有 Skill 的工具路径。

    若无工具有已安装的 Skill，抛出 SystemExit。
    """
    for tool in _TOOL_REGISTRY:
        if not _is_tool_detected(tool):
            continue
        _, skills_dir = _TOOL_REGISTRY[tool]
        if skills_dir.exists() and any(
            (p / "data" / "VERSION.json").exists() or (p / "SKILL.md").exists()
            for p in skills_dir.iterdir()
            if p.is_dir()
        ):
            return skills_dir, tool

    _exit_error("skill-sync sync", "未检测到任何 AI 工具中有已安装的 Skill，请通过 --from 或 --from-dir 手动指定来源")


def _resolve_tool_targets(tool_names: list[str]) -> list[tuple[str, Path]]:
    """将工具名列表解析为 (tool, skills_dir) 二元组列表，去重。"""
    seen: set[str] = set()
    targets: list[tuple[str, Path]] = []
    for name in tool_names:
        name = name.strip().lower()
        if not name or name in seen:
            continue
        if name not in _TOOL_REGISTRY:
            print(
                json.dumps({
                    "success": False,
                    "command": "skill-sync sync",
                    "data": None,
                    "error": {
                        "type": "ValueError",
                        "message": f"未知目标工具: {name}，支持的工具: {', '.join(_TOOL_REGISTRY)}",
                    },
                }, ensure_ascii=False)
            )
            sys.exit(1)
        _, skills_dir = _TOOL_REGISTRY[name]
        targets.append((name, skills_dir))
        seen.add(name)
    return targets


def _auto_detect_targets(exclude_tool: str) -> list[tuple[str, Path]]:
    """检测所有已安装的 AI 工具，返回目标列表（排除来源工具自身）。"""
    targets: list[tuple[str, Path]] = []
    for tool in _TOOL_REGISTRY:
        if tool == exclude_tool:
            continue
        if _is_tool_detected(tool):
            _, skills_dir = _TOOL_REGISTRY[tool]
            targets.append((tool, skills_dir))
    return targets


def _exit_error(command: str, message: str) -> NoReturn:
    """输出 JSON 错误并退出（exit code 1）。"""
    print(json.dumps({
        "success": False,
        "command": command,
        "data":    None,
        "error":   {"type": "ValueError", "message": message},
    }, ensure_ascii=False))
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# 命令行解析入口
# ─────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="sync.py",
        description="ops-skill-sync：扫描 AI 工具已安装 Skills 并跨工具同步",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan 子命令
    scan_p = sub.add_parser("scan", help="扫描各 AI 工具下已安装的 Skills")
    scan_p.add_argument(
        "--tool",
        metavar="TOOL",
        help=f"只扫描指定工具（不填则扫描全部），可选: {', '.join(_TOOL_REGISTRY)}",
    )
    scan_p.add_argument(
        "--type",
        choices=["opscli", "all"],
        default="opscli",
        help="扫描类型：opscli（默认，仅识别 data/VERSION.json）/ all（同时识别只有 SKILL.md 的 Skill）",
    )

    # sync 子命令
    sync_p = sub.add_parser("sync", help="将 Skills 从来源工具同步到目标工具")
    # 来源（--from 与 --from-dir 互斥）
    src_group = sync_p.add_mutually_exclusive_group()
    src_group.add_argument(
        "--from",
        dest="from_tool",
        metavar="TOOL",
        help=f"来源工具（不填则自动检测），可选: {', '.join(_TOOL_REGISTRY)}",
    )
    src_group.add_argument(
        "--from-dir",
        metavar="PATH",
        help="来源 skills 目录完整路径",
    )
    # 目标（--to 与 --to-dir 互斥）
    dst_group = sync_p.add_mutually_exclusive_group()
    dst_group.add_argument(
        "--to",
        metavar="TOOL[,TOOL]",
        help="目标工具（逗号分隔多个，不填则同步到所有检测到的工具）",
    )
    dst_group.add_argument(
        "--to-dir",
        metavar="PATH",
        help="目标 skills 目录完整路径",
    )
    # 可选：指定 Skill 名称
    sync_p.add_argument(
        "--skills",
        metavar="NAME[,NAME]",
        help="只同步指定 Skill（逗号分隔，不填则同步全部）",
    )
    # 扫描类型（影响不指定 --skills 时的来源目录扫描范围）
    sync_p.add_argument(
        "--type",
        choices=["opscli", "all"],
        default="opscli",
        help="扫描类型：opscli（默认，仅识别 data/VERSION.json）/ all（同时识别只有 SKILL.md 的 Skill）",
    )

    return parser


def main() -> None:
    """脚本入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "sync":
        cmd_sync(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
