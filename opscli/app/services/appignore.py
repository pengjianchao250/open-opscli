"""构建 AppHub 本地规范扫描文件集。"""

from __future__ import annotations

import fnmatch
from pathlib import Path


DEFAULT_EXCLUDES = (
    ".git/**",
    ".venv/**",
    "venv/**",
    "__pycache__/**",
    "*.pyc",
    ".env",
)


def load_patterns(root: Path) -> tuple[str, ...]:
    """读取 .appignore；空行与注释不参与匹配。"""
    path = root / ".appignore"
    patterns = list(DEFAULT_EXCLUDES)
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            value = raw.strip().replace("\\", "/")
            if value and not value.startswith("#"):
                patterns.append(value.rstrip("/"))
    return tuple(patterns)


def build_file_set(project_dir: str | Path) -> list[Path]:
    """返回 .appignore 过滤后的普通文件。"""
    root = Path(project_dir).expanduser().resolve()
    patterns = load_patterns(root)
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if any(_matches(relative, pattern) for pattern in patterns):
            continue
        files.append(path)
    return sorted(files)


def _matches(relative: str, pattern: str) -> bool:
    normalized = pattern.lstrip("/")
    return (
        fnmatch.fnmatch(relative, normalized)
        or fnmatch.fnmatch(relative, f"{normalized}/**")
        or (normalized.endswith("/**") and relative.startswith(normalized[:-3].rstrip("/") + "/"))
    )
