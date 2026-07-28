"""Skill 模板发版准入与收集工具。

该模块是 Skill 模板发布范围的单一判断入口，供 setup.py、二进制打包
脚本和发版检查脚本复用。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_FILENAME = "manifest.json"
PROFILE_ENV = "OPSCLI_SKILL_PROFILE"
DEFAULT_PROFILE = "dev"
RELEASE_PROFILE = "python-release"


def get_central_skills_dir() -> Path:
    """返回跨平台中央 Skills 存储目录。

    macOS / Linux : ~/.opscli/skills/
    Windows       : %LOCALAPPDATA%\\opscli\\skills\\
    环境变量 OPSCLI_CENTRAL_SKILLS_DIR 可覆盖（测试隔离用）。
    """
    override = os.environ.get("OPSCLI_CENTRAL_SKILLS_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        # 优先使用 %LOCALAPPDATA%（避免漫游配置冲突）
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path.home()
        return base / "opscli" / "skills"

    return Path.home() / ".opscli" / "skills"

_PROFILE_KEYS = {
    "python-release": {
        "sdist": "source",
        "wheel": "wheel",
    },
    "binary-minimal": {
        "binary": "binary",
    },
    "binary-full": {
        "binary": "binary_full",
    },
}


class SkillReleaseManifestError(ValueError):
    """Skill 发版清单错误。"""


def get_builtin_templates_dir() -> Path:
    """返回当前运行环境中的内置 Skill 模板目录。

    普通 Python 包、PyInstaller onefile 和测试覆盖都通过这个函数解析路径，
    避免业务代码直接依赖固定的 __file__ 相对路径。
    """
    override = os.environ.get("OPSCLI_BUILTIN_TEMPLATES_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "opscli" / "skills" / "templates"
        if bundled.exists():
            return bundled

    return Path(__file__).resolve().parent / "templates"


def load_release_manifest(templates_dir: Path | None = None) -> dict[str, Any]:
    """读取 Skill 发版清单。"""
    root = templates_dir or get_builtin_templates_dir()
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise SkillReleaseManifestError(f"未找到 Skill 发版清单: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkillReleaseManifestError(f"Skill 发版清单 JSON 无效: {manifest_path}") from exc
    if not isinstance(payload, dict):
        raise SkillReleaseManifestError("Skill 发版清单根节点必须是对象")
    if not isinstance(payload.get("skills"), dict):
        raise SkillReleaseManifestError("Skill 发版清单必须包含 skills 对象")
    return payload


def list_template_dirs(templates_dir: Path | None = None) -> list[Path]:
    """列出模板根目录下所有 Skill 目录。"""
    root = templates_dir or get_builtin_templates_dir()
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def current_profile(default: str = DEFAULT_PROFILE) -> str:
    """读取当前 Skill 构建 profile。"""
    return os.environ.get(PROFILE_ENV, "").strip() or default


def _profile_key(profile: str, artifact: str) -> str | None:
    if profile == "dev" or profile == "internal":
        return None
    keys = _PROFILE_KEYS.get(profile)
    if not keys:
        raise SkillReleaseManifestError(f"未知 Skill 构建 profile: {profile}")
    key = keys.get(artifact)
    if key is None:
        raise SkillReleaseManifestError(f"profile {profile!r} 不支持产物类型 {artifact!r}")
    return key


def skill_allowed(
    skill_name: str,
    *,
    profile: str,
    artifact: str,
    manifest: dict[str, Any] | None = None,
    templates_dir: Path | None = None,
) -> bool:
    """判断指定 Skill 是否允许进入目标 profile/artifact。"""
    if profile in {"dev", "internal"}:
        return True

    payload = manifest or load_release_manifest(templates_dir)
    key = _profile_key(profile, artifact)
    if key is None:
        return True

    defaults = payload.get("default", {})
    skills = payload.get("skills", {})
    row = skills.get(skill_name, {})
    if not isinstance(row, dict):
        row = {}
    return bool(row.get(key, defaults.get(key, False)))


def selected_skill_names(
    *,
    profile: str | None = None,
    artifact: str,
    templates_dir: Path | None = None,
) -> list[str]:
    """返回目标 profile/artifact 下应包含的 Skill 名称。"""
    root = templates_dir or get_builtin_templates_dir()
    resolved_profile = profile or current_profile()
    manifest = None if resolved_profile in {"dev", "internal"} else load_release_manifest(root)

    names: list[str] = []
    for skill_dir in list_template_dirs(root):
        if skill_allowed(
            skill_dir.name,
            profile=resolved_profile,
            artifact=artifact,
            manifest=manifest,
            templates_dir=root,
        ):
            names.append(skill_dir.name)
    return names


def prune_templates_dir(
    target_templates_dir: Path,
    *,
    profile: str | None = None,
    artifact: str,
    manifest_templates_dir: Path | None = None,
) -> list[str]:
    """删除目标模板目录中不允许进入当前产物的 Skill。

    返回被保留的 Skill 名称列表。
    """
    if not target_templates_dir.exists():
        return []
    _remove_packaging_junk(target_templates_dir)

    resolved_profile = profile or current_profile()
    if resolved_profile in {"dev", "internal"}:
        return [p.name for p in list_template_dirs(target_templates_dir)]

    allowed = set(
        selected_skill_names(
            profile=resolved_profile,
            artifact=artifact,
            templates_dir=manifest_templates_dir or get_builtin_templates_dir(),
        )
    )
    for child in target_templates_dir.iterdir():
        if child.is_dir() and child.name not in allowed:
            _remove_tree(child)
    return sorted(name for name in allowed if (target_templates_dir / name).exists())


def collect_skill_datas(
    *,
    profile: str | None = None,
    templates_dir: Path | None = None,
) -> list[tuple[str, str]]:
    """返回 PyInstaller datas 兼容的模板文件列表。

    每个元素为 (source_file, destination_dir)，destination_dir 保持
    opscli/skills/templates/<skill-name>/... 结构。
    """
    root = templates_dir or get_builtin_templates_dir()
    names = selected_skill_names(profile=profile or "binary-minimal", artifact="binary", templates_dir=root)
    datas: list[tuple[str, str]] = []
    for name in names:
        skill_dir = root / name
        for file_path in sorted(p for p in skill_dir.rglob("*") if _is_packable_file(p)):
            relative_parent = file_path.parent.relative_to(root)
            destination = PurePosixPath("opscli", "skills", "templates", *relative_parent.parts)
            datas.append((str(file_path), str(destination)))
    manifest_file = root / MANIFEST_FILENAME
    if manifest_file.exists():
        datas.append((str(manifest_file), "opscli/skills/templates"))
    return datas


def validate_release_manifest(templates_dir: Path | None = None) -> list[str]:
    """校验发版清单声明完整性，返回问题列表。"""
    root = templates_dir or get_builtin_templates_dir()
    payload = load_release_manifest(root)
    skills = payload["skills"]
    problems: list[str] = []

    actual_names = {p.name for p in list_template_dirs(root)}
    declared_names = set(skills)
    for missing in sorted(actual_names - declared_names):
        problems.append(f"模板目录未在 manifest 声明: {missing}")
    for stale in sorted(declared_names - actual_names):
        problems.append(f"manifest 声明了不存在的模板目录: {stale}")

    for name in sorted(actual_names & declared_names):
        row = skills.get(name)
        if not isinstance(row, dict):
            problems.append(f"{name}: manifest 条目必须是对象")
            continue
        if not str(row.get("reason", "")).strip():
            problems.append(f"{name}: reason 不能为空")
        if not str(row.get("tier", "")).strip():
            problems.append(f"{name}: tier 不能为空")

        skill_dir = root / name
        if any(bool(row.get(key, False)) for key in ("source", "wheel", "binary", "binary_full")):
            if not (skill_dir / "SKILL.md").exists():
                problems.append(f"{name}: 发版准入 Skill 必须包含 SKILL.md")
            if not (skill_dir / "data" / "VERSION.json").exists():
                problems.append(f"{name}: 发版准入 Skill 必须包含 data/VERSION.json")

    return problems


def _remove_tree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


def _is_packable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name == ".DS_Store" or path.suffix in {".pyc", ".pyo"}:
        return False
    return "__pycache__" not in path.parts


def _remove_packaging_junk(root: Path) -> None:
    for child in list(root.rglob("__pycache__")):
        if child.is_dir():
            _remove_tree(child)
    for child in list(root.rglob("*")):
        if child.is_file() and not _is_packable_file(child):
            child.unlink()
