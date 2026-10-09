"""源码复制迁移项目的生产构建合同检查。"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

_PNPM_DECLARATION_RE = re.compile(r"^pnpm@(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$")
_COREPACK_ENABLE_RE = re.compile(r"\bcorepack\s+enable\b")
_PNPM_FRONTEND_DIR_RE = re.compile(r"\bpnpm\s+(?:--dir(?:=|\s+)|-C\s+)frontend\b")
_NESTED_FRONTEND_MANIFEST_RE = re.compile(
    r"\bCOPY\s+frontend/package\.json(?:\s+frontend/pnpm-lock\.yaml)?\s+\./frontend/?\b"
)
_PUBLIC_PATH_SUFFIXES = {".css", ".html", ".js", ".jsx", ".svelte", ".ts", ".tsx", ".vue"}
_PUBLIC_PATH_EXCLUDED_PARTS = {
    ".git",
    ".next",
    ".nuxt",
    ".opscli",
    ".venv",
    ".vinext",
    "coverage",
    "dist",
    "node_modules",
    "tests",
}
_HTML_ROOT_PATH_RE = re.compile(
    r"\b(?P<attribute>href|src|action|poster)\s*=\s*(?P<quote>['\"])/(?!/)(?P<path>[^'\"]*)",
    re.IGNORECASE,
)
_CSS_ROOT_PATH_RE = re.compile(
    r"\burl\(\s*(?P<quote>['\"]?)/(?!/)(?P<path>[^)'\"]*)",
    re.IGNORECASE,
)
_SCRIPT_ROOT_PATH_RE = re.compile(
    r"(?P<quote>['\"`])/(?!/)(?P<path>(?:api|assets|dashboard|static|_next)(?:/|(?=['\"`])))",
)
_RUNTIME_REFERENCE_SUFFIXES = {".cjs", ".js", ".mjs", ".py", ".ts"}
_RUNTIME_REFERENCE_EXCLUDED_PARTS = {
    ".git",
    ".opscli",
    ".venv",
    "dist",
    "node_modules",
    "public",
    "tests",
}


def inspect_migration_frontend_build(root: str | Path) -> dict[str, Any]:
    """识别 Corepack 无法看到前端 packageManager 的确定性失败配置。"""
    project_root = Path(root).expanduser().resolve()
    package_path = project_root / "frontend" / "package.json"
    dockerfile_path = project_root / "Dockerfile"
    if not package_path.is_file():
        return _result(True, "not_applicable")
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _result(True, "not_applicable")
    if not isinstance(package, dict):
        return _result(True, "not_applicable")

    declaration = package.get("packageManager")
    if not isinstance(declaration, str) or not declaration.startswith("pnpm@"):
        return _result(True, "not_applicable", package_manager=declaration)
    match = _PNPM_DECLARATION_RE.fullmatch(declaration)
    if match is None:
        return _result(False, "pnpm_declaration_invalid", package_manager=declaration)
    if not dockerfile_path.is_file():
        return _result(True, "not_applicable", package_manager=declaration)
    try:
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return _result(True, "not_applicable", package_manager=declaration)

    normalized = re.sub(r"\\\r?\n", " ", dockerfile)
    explicit_pin = re.search(
        rf"\bcorepack\s+(?:prepare|use)\s+{re.escape(declaration)}(?:\s|$)",
        normalized,
    )
    context_mismatch = (
        _COREPACK_ENABLE_RE.search(normalized) is not None
        and _PNPM_FRONTEND_DIR_RE.search(normalized) is not None
        and _NESTED_FRONTEND_MANIFEST_RE.search(normalized) is not None
        and explicit_pin is None
    )
    if context_mismatch:
        return _result(
            False,
            "corepack_context_mismatch",
            package_manager=declaration,
            detail={
                "dockerfile": "Dockerfile",
                "frontend_manifest": "frontend/package.json",
            },
        )
    return _result(True, "ready", package_manager=declaration)


def inspect_migration_public_paths(root: str | Path) -> dict[str, Any]:
    """检查迁移前端是否使用无法适配 AppHub 动态前缀的根绝对 URL。"""
    project_root = Path(root).expanduser().resolve()
    source_roots = _public_path_source_roots(project_root)
    violations: list[dict[str, Any]] = []
    for source_root in source_roots:
        for path in sorted(source_root.rglob("*")):
            if (
                not path.is_file()
                or path.suffix.lower() not in _PUBLIC_PATH_SUFFIXES
                or any(part in _PUBLIC_PATH_EXCLUDED_PARTS for part in path.relative_to(project_root).parts)
            ):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            relative = path.relative_to(project_root).as_posix()
            patterns = []
            if path.suffix.lower() == ".html":
                patterns.append(("html_attribute", _HTML_ROOT_PATH_RE))
            if path.suffix.lower() == ".css":
                patterns.append(("css_url", _CSS_ROOT_PATH_RE))
            if path.suffix.lower() in {".js", ".jsx", ".svelte", ".ts", ".tsx", ".vue"}:
                patterns.append(("script_url", _SCRIPT_ROOT_PATH_RE))
            for kind, pattern in patterns:
                for match in pattern.finditer(content):
                    violations.append(
                        {
                            "file": relative,
                            "line": content.count("\n", 0, match.start()) + 1,
                            "kind": kind,
                            "value": f"/{match.group('path')}",
                        }
                    )
                    if len(violations) >= 100:
                        break
                if len(violations) >= 100:
                    break
            if len(violations) >= 100:
                break
        if len(violations) >= 100:
            break
    if violations:
        return _result(
            False,
            "root_relative_public_url",
            detail={
                "violations": violations,
                "scanned_roots": [
                    path.relative_to(project_root).as_posix() or "." for path in source_roots
                ],
            },
        )
    return _result(
        True,
        "ready" if source_roots else "not_applicable",
        detail={
            "violations": [],
            "scanned_roots": [
                path.relative_to(project_root).as_posix() or "." for path in source_roots
            ],
        },
    )


def inspect_migration_runtime_assets(root: str | Path) -> dict[str, Any]:
    """检查代码引用的公开数据快照是否会进入最终运行镜像。"""
    project_root = Path(root).expanduser().resolve()
    snapshot_roots = _referenced_public_data_roots(project_root)
    if not snapshot_roots:
        return _result(
            True,
            "not_applicable",
            detail={"snapshot_roots": [], "references": [], "violations": []},
        )

    dockerfile_path = project_root / "Dockerfile"
    if not dockerfile_path.is_file():
        return _result(
            True,
            "not_applicable",
            detail={
                "snapshot_roots": [item["root"] for item in snapshot_roots],
                "references": [reference for item in snapshot_roots for reference in item["references"]],
                "violations": [],
            },
        )
    try:
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return _result(True, "not_applicable")

    violations: list[dict[str, Any]] = []
    final_stage = _final_docker_stage(dockerfile)
    if not _docker_stage_copies_public(final_stage):
        violations.append(
            {
                "file": "Dockerfile",
                "kind": "runtime_public_not_copied",
                "value": "public",
            }
        )
    for ignore_name in (".gitignore", ".dockerignore"):
        ignore_path = project_root / ignore_name
        for item in snapshot_roots:
            if _ignore_file_excludes(ignore_path, item["root"]):
                violations.append(
                    {
                        "file": ignore_name,
                        "kind": "runtime_snapshot_ignored",
                        "value": item["root"],
                    }
                )

    detail = {
        "snapshot_roots": [item["root"] for item in snapshot_roots],
        "references": [reference for item in snapshot_roots for reference in item["references"]],
        "violations": violations,
    }
    if violations:
        return _result(False, "runtime_snapshot_not_packaged", detail=detail)
    return _result(True, "ready", detail=detail)


def _public_path_source_roots(project_root: Path) -> list[Path]:
    """返回需要按浏览器运行时合同扫描的源码根目录。"""
    roots: list[Path] = []
    for relative in ("frontend/src", "web", "src"):
        candidate = project_root / relative
        if candidate.is_dir():
            roots.append(candidate)
    if (project_root / "index.html").is_file():
        roots.append(project_root)
    return roots


def _referenced_public_data_roots(project_root: Path) -> list[dict[str, Any]]:
    public_root = project_root / "public"
    if not public_root.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for candidate in sorted(public_root.rglob("data")):
        if not candidate.is_dir() or not any(path.is_file() for path in candidate.rglob("*")):
            continue
        relative = candidate.relative_to(project_root).as_posix()
        references = _runtime_asset_references(project_root, relative)
        if references:
            results.append({"root": relative, "references": references})
    return results


def _runtime_asset_references(project_root: Path, relative: str) -> list[dict[str, Any]]:
    parts = relative.split("/")
    references: list[dict[str, Any]] = []
    for path in _runtime_reference_paths(project_root):
        if (
            not path.is_file()
            or path.suffix.lower() not in _RUNTIME_REFERENCE_SUFFIXES
            or any(
                part in _RUNTIME_REFERENCE_EXCLUDED_PARTS
                for part in path.relative_to(project_root).parts
            )
        ):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            normalized = line.replace("\\", "/")
            cursor = 0
            for part in parts:
                cursor = normalized.find(part, cursor)
                if cursor < 0:
                    break
                cursor += len(part)
            else:
                references.append(
                    {
                        "file": path.relative_to(project_root).as_posix(),
                        "line": line_number,
                        "value": relative,
                    }
                )
                break
    return references


def _runtime_reference_paths(project_root: Path) -> list[Path]:
    paths = [
        path
        for path in project_root.iterdir()
        if path.is_file() and path.suffix.lower() in _RUNTIME_REFERENCE_SUFFIXES
    ]
    for relative in ("app", "backend", "scripts", "server", "src", "worker"):
        source_root = project_root / relative
        if not source_root.is_dir():
            continue
        paths.extend(
            path
            for path in source_root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in _RUNTIME_REFERENCE_SUFFIXES
            and not any(
                part in _RUNTIME_REFERENCE_EXCLUDED_PARTS
                for part in path.relative_to(project_root).parts
            )
        )
    return sorted(set(paths))


def _final_docker_stage(dockerfile: str) -> str:
    starts = [match.start() for match in re.finditer(r"(?im)^\s*FROM\b", dockerfile)]
    return dockerfile[starts[-1] :] if starts else dockerfile


def _docker_stage_copies_public(stage: str) -> bool:
    normalized = re.sub(r"\\\r?\n", " ", stage)
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("COPY "):
            continue
        arguments = stripped[5:].strip()
        while arguments.startswith("--"):
            _, _, arguments = arguments.partition(" ")
            arguments = arguments.lstrip()
        try:
            values = json.loads(arguments) if arguments.startswith("[") else shlex.split(arguments)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(values, list) or len(values) < 2:
            continue
        for source in values[:-1]:
            normalized_source = str(source).replace("\\", "/").rstrip("/")
            if normalized_source in {".", "./", "public", "./public"}:
                return True
            if normalized_source.startswith(("public/", "./public/")):
                return True
            if normalized_source.endswith("/public"):
                return True
    return False


def _ignore_file_excludes(path: Path, relative: str) -> bool:
    if not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    ignored = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:] if negated else line
        if _ignore_pattern_matches(pattern, relative):
            ignored = not negated
    return ignored


def _ignore_pattern_matches(pattern: str, relative: str) -> bool:
    normalized = pattern.replace("\\", "/").rstrip("/")
    if not normalized:
        return False
    relative_parts = relative.split("/")
    if normalized.startswith("/"):
        rooted = normalized.lstrip("/")
        return relative == rooted or relative.startswith(f"{rooted}/")
    if "/" not in normalized:
        return normalized in relative_parts
    return relative == normalized or relative.startswith(f"{normalized}/")


def _result(
    ready: bool,
    reason: str,
    *,
    package_manager: Any = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ready": ready,
        "reason": reason,
        "package_manager": package_manager,
        "detail": detail or {},
    }
