"""检查 Skill 发版清单与发布产物内容。

示例：
    python scripts/check_skill_release_manifest.py --profile python-release --artifact wheel
    python scripts/check_skill_release_manifest.py --profile python-release --artifact wheel --dist dist/*.whl
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tarfile
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_MODULE = REPO_ROOT / "opscli" / "skills" / "packaging.py"
TEMPLATES_DIR = REPO_ROOT / "opscli" / "skills" / "templates"


def load_packaging_module():
    spec = importlib.util.spec_from_file_location("_opscli_skill_packaging", PACKAGING_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Skill 发版准入模块: {PACKAGING_MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact_members(path: Path) -> list[str]:
    if path.suffix == ".whl" or path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    if path.name.endswith(".tar.gz") or path.name.endswith(".tgz"):
        with tarfile.open(path, "r:gz") as tf:
            return tf.getnames()
    raise ValueError(f"不支持的产物格式: {path}")


def skill_names_in_members(members: list[str]) -> set[str]:
    names: set[str] = set()
    for member in members:
        normalized = member.replace("\\", "/")
        marker = "opscli/skills/templates/"
        if marker not in normalized:
            continue
        tail = normalized.split(marker, 1)[1]
        if not tail or tail == "manifest.json":
            continue
        skill_name = tail.split("/", 1)[0]
        if skill_name:
            names.add(skill_name)
    return names


def expand_dist_patterns(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = sorted(REPO_ROOT.glob(pattern)) if any(ch in pattern for ch in "*?[") else [Path(pattern)]
        for match in matches:
            path = match if match.is_absolute() else REPO_ROOT / match
            if path.exists():
                paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Skill 发版清单与构建产物")
    parser.add_argument("--profile", default="python-release", help="构建 profile")
    parser.add_argument("--artifact", choices=["sdist", "wheel", "binary"], default="wheel", help="产物类型")
    parser.add_argument("--dist", nargs="*", default=[], help="可选，待检查的 dist 产物路径或 glob")
    args = parser.parse_args()

    packaging = load_packaging_module()
    problems = packaging.validate_release_manifest(TEMPLATES_DIR)
    expected = set(
        packaging.selected_skill_names(
            profile=args.profile,
            artifact=args.artifact,
            templates_dir=TEMPLATES_DIR,
        )
    )

    if args.dist:
        for dist_path in expand_dist_patterns(args.dist):
            actual = skill_names_in_members(artifact_members(dist_path))
            unexpected = sorted(actual - expected)
            missing = sorted(expected - actual)
            if unexpected:
                problems.append(f"{dist_path.name}: 包含未准入 Skill: {', '.join(unexpected)}")
            if missing:
                problems.append(f"{dist_path.name}: 缺少准入 Skill: {', '.join(missing)}")

    if problems:
        print("Skill 发版检查失败：", file=sys.stderr)
        for item in problems:
            print(f"- {item}", file=sys.stderr)
        return 1

    print(
        f"Skill 发版检查通过 profile={args.profile} artifact={args.artifact} "
        f"skills={','.join(sorted(expected))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
