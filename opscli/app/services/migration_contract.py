"""源码复制迁移项目的生产构建合同检查。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import yaml

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
    ".sites-checkout",
    ".sites-runtime",
    ".venv",
    ".vinext",
    ".wrangler",
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
    r"(?P<quote>['\"`])/(?P<dot>\./)?(?P<path>(?:api|assets|dashboard|static|_next)(?:/|(?=['\"`])))",
)
_PUBLIC_PATH_GENERATED_PATTERNS = (
    "dist/server/**/__vite_rsc_assets_manifest.js",
    "dist/server/**/vinext-client-assets.js",
)
_RUNTIME_REFERENCE_SUFFIXES = {".cjs", ".js", ".mjs", ".py", ".ts"}
_RUNTIME_REFERENCE_EXCLUDED_PARTS = {
    ".git",
    ".opscli",
    ".sites-checkout",
    ".sites-runtime",
    ".venv",
    ".vinext",
    ".wrangler",
    "dist",
    "node_modules",
    "public",
    "tests",
}
_REQUIRED_RELEASE_FILES = ("app.yaml", "Dockerfile", ".dockerignore", ".gitignore")
_BUILD_CONFIG_SUFFIXES = {".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
_BUILD_CONFIG_EXCLUDED_PARTS = _RUNTIME_REFERENCE_EXCLUDED_PARTS | {
    ".next",
    ".nuxt",
    "build",
    "coverage",
    "out",
}
_BUILD_CONFIG_NAME_RE = re.compile(r"(?:^|\.)(?:config)\.(?:cjs|js|jsx|mjs|ts|tsx)$")
_STATIC_RELATIVE_IMPORT_RE = re.compile(
    r"""
    (?:
        \b(?:import|export)\s+(?:[^;\n]*?\s+from\s+)?
        |
        \brequire\s*\(\s*
    )
    (?P<quote>['"])
    (?P<path>\.{1,2}/[^'"]+)
    (?P=quote)
    """,
    re.VERBOSE,
)
_RELATIVE_IMPORT_SUFFIXES = (".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".json")
_APP_YAML_FIELDS = {
    "apiVersion",
    "app_id",
    "title",
    "description",
    "contact",
    "resources",
    "database",
    "opscli",
    "llm",
    "access",
}
_APP_YAML_BLOCK_FIELDS = {
    "resources": {"cpu", "memory"},
    "database": {"kind", "path"},
    "opscli": {"auth_mode", "datasets"},
    "llm": {"enabled"},
    "access": {"visibility"},
}
_DOCKER_START_RE = re.compile(r"(?im)^\s*(?:CMD|ENTRYPOINT)\b")
_PORT_REFERENCE_RE = re.compile(
    r"(?<![0-9A-Za-z_])(?:8000|\$PORT|\$\{PORT(?:[:?+\-][^}]*)?\}|process\.env\.PORT|os\.environ(?:\.get)?\([^\n]*['\"]PORT['\"])",
)
_HEALTH_PATH = "/__apphub_healthz"
_RUNTIME_CONTRACT_SUFFIXES = {
    ".cjs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".ts",
    ".tsx",
}
_RUNTIME_CONTRACT_EXCLUDED_PARTS = {
    ".git",
    ".opscli",
    ".sites-checkout",
    ".sites-runtime",
    ".venv",
    ".vinext",
    ".wrangler",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "tests",
}
_FINGERPRINT_EXCLUDED_PARTS = {
    ".git",
    ".opscli",
    ".sites-checkout",
    ".sites-runtime",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vinext",
    ".wrangler",
    ".coverage",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "out",
}
_FINGERPRINT_EXCLUDED_SUFFIXES = {".db", ".log", ".sqlite", ".sqlite3"}


def inspect_migration_release_assets(
    root: str | Path,
    *,
    expected_app_id: str | None = None,
) -> dict[str, Any]:
    """检查迁移副本是否具备 AppHub 线上构建所需的最小发布资产。"""
    project_root = Path(root).expanduser().resolve()
    missing = [
        relative
        for relative in _REQUIRED_RELEASE_FILES
        if not (project_root / relative).is_file()
    ]
    violations: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    manifest_path = project_root / "app.yaml"
    if manifest_path.is_file():
        try:
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            violations.append(
                {"file": "app.yaml", "kind": "invalid_yaml", "value": str(exc)}
            )
        else:
            if not isinstance(loaded, dict):
                violations.append({"file": "app.yaml", "kind": "invalid_document"})
            else:
                manifest = loaded
                unknown_fields = sorted(set(loaded) - _APP_YAML_FIELDS)
                for field in unknown_fields:
                    violations.append(
                        {
                            "file": "app.yaml",
                            "kind": "unknown_app_yaml_field",
                            "value": field,
                        }
                    )
                if loaded.get("apiVersion") != "apps.aukeys/v1":
                    violations.append(
                        {
                            "file": "app.yaml",
                            "kind": "api_version_mismatch",
                            "value": loaded.get("apiVersion"),
                        }
                    )
                if "name" in loaded:
                    violations.append({"file": "app.yaml", "kind": "legacy_name_field"})
                app_id = loaded.get("app_id")
                if not isinstance(app_id, str) or re.fullmatch(
                    r"[0-9A-Za-z]{5}", app_id
                ) is None:
                    violations.append(
                        {"file": "app.yaml", "kind": "invalid_app_id", "value": app_id}
                    )
                elif expected_app_id and app_id != expected_app_id:
                    violations.append(
                        {
                            "file": "app.yaml",
                            "kind": "app_id_mismatch",
                            "value": app_id,
                            "expected": expected_app_id,
                        }
                    )
                _inspect_app_yaml_blocks(loaded, violations)
                database = loaded.get("database")
                if isinstance(database, dict) and not (
                    project_root / "compose.apphub.yaml"
                ).is_file():
                    missing.append("compose.apphub.yaml")

    dockerfile = ""
    dockerfile_path = project_root / "Dockerfile"
    if dockerfile_path.is_file():
        try:
            dockerfile = dockerfile_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            violations.append(
                {"file": "Dockerfile", "kind": "unreadable", "value": str(exc)}
            )
    runtime_contract = _inspect_runtime_contract(project_root, dockerfile)
    if dockerfile and _DOCKER_START_RE.search(dockerfile) is None:
        violations.append(
            {"file": "Dockerfile", "kind": "docker_start_command_missing"}
        )
    if dockerfile and not runtime_contract["port_evidence"]:
        violations.append({"file": "Dockerfile", "kind": "port_contract_missing"})
    if dockerfile and not runtime_contract["health_evidence"]:
        violations.append(
            {"file": "Dockerfile", "kind": "health_route_missing"}
        )

    for ignore_name in (".gitignore", ".dockerignore"):
        ignore_path = project_root / ignore_name
        for relative in _REQUIRED_RELEASE_FILES:
            if relative == ignore_name:
                continue
            if _ignore_file_excludes(ignore_path, relative):
                violations.append(
                    {
                        "file": ignore_name,
                        "kind": "release_asset_ignored",
                        "value": relative,
                    }
                )

    violations.extend(_inspect_build_input_releasability(project_root))
    frontend_build = inspect_migration_frontend_build(project_root)
    public_paths = inspect_migration_public_paths(project_root)
    runtime_assets = inspect_migration_runtime_assets(project_root)
    detail = {
        "missing": missing,
        "violations": violations,
        "app_id": manifest.get("app_id"),
        "frontend_build": frontend_build,
        "public_paths": public_paths,
        "runtime_assets": runtime_assets,
        "runtime_contract": runtime_contract,
    }
    ready = (
        not missing
        and not violations
        and frontend_build["ready"]
        and public_paths["ready"]
        and runtime_assets["ready"]
    )
    return _result(
        ready,
        "ready" if ready else "release_gate_failed",
        detail=detail,
    )


def _inspect_app_yaml_blocks(
    manifest: dict[str, Any],
    violations: list[dict[str, Any]],
) -> None:
    """按 AppHub 当前严格字段集合检查迁移发布清单。"""
    for block_name, allowed_fields in _APP_YAML_BLOCK_FIELDS.items():
        block = manifest.get(block_name)
        if block is None:
            continue
        if not isinstance(block, dict):
            violations.append(
                {
                    "file": "app.yaml",
                    "kind": "invalid_app_yaml_block",
                    "value": block_name,
                }
            )
            continue
        for field in sorted(set(block) - allowed_fields):
            violations.append(
                {
                    "file": "app.yaml",
                    "kind": "unknown_app_yaml_field",
                    "value": f"{block_name}.{field}",
                }
            )

    database = manifest.get("database")
    if not isinstance(database, dict):
        return
    if database.get("kind") != "sqlite":
        violations.append(
            {
                "file": "app.yaml",
                "kind": "invalid_database_kind",
                "value": database.get("kind"),
            }
        )
    database_path = database.get("path")
    if not isinstance(database_path, str) or not _valid_database_path(database_path):
        violations.append(
            {
                "file": "app.yaml",
                "kind": "invalid_database_path",
                "value": database_path,
            }
        )


def _valid_database_path(value: str) -> bool:
    """复现 AppHub 对 SQLite 容器内文件路径的关键约束。"""
    if "\x00" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not (
        not path.is_absolute()
        or value == "/"
        or value.startswith("//")
        or value.endswith("/")
        or ".." in path.parts
        or str(path) != value
        or path.parent == PurePosixPath("/")
    )


def _inspect_runtime_contract(project_root: Path, dockerfile: str) -> dict[str, Any]:
    """收集生产端口和 AppHub 健康路径的静态证据。"""
    port_evidence: list[str] = []
    health_evidence: list[str] = []
    if dockerfile and _PORT_REFERENCE_RE.search(dockerfile):
        port_evidence.append("Dockerfile")
    for path in _iter_project_files(project_root, _RUNTIME_CONTRACT_EXCLUDED_PARTS):
        if (
            path.suffix.lower() not in _RUNTIME_CONTRACT_SUFFIXES
        ):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(project_root).as_posix()
        if _PORT_REFERENCE_RE.search(content):
            port_evidence.append(relative)
        if _HEALTH_PATH in content:
            health_evidence.append(relative)
    return {
        "port": 8000,
        "health_path": _HEALTH_PATH,
        "port_evidence": sorted(set(port_evidence)),
        "health_evidence": sorted(set(health_evidence)),
    }


def migration_release_fingerprint(root: str | Path) -> dict[str, Any]:
    """计算迁移验证后可交付源码的稳定指纹，排除本地状态与运行数据。"""
    project_root = Path(root).expanduser().resolve()
    digest = hashlib.sha256()
    included: list[str] = []
    for path in _iter_project_files(project_root, _FINGERPRINT_EXCLUDED_PARTS):
        relative = path.relative_to(project_root)
        if _exclude_from_release_fingerprint(relative):
            continue
        normalized = relative.as_posix()
        digest.update(normalized.encode("utf-8"))
        digest.update(b"\0")
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        except OSError:
            continue
        digest.update(b"\0")
        included.append(normalized)
    return {"sha256": digest.hexdigest(), "file_count": len(included)}


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
    generated_files = _public_path_generated_files(project_root)
    violations: list[dict[str, Any]] = []
    for source_root in source_roots:
        for path in _iter_project_files(source_root, _PUBLIC_PATH_EXCLUDED_PARTS):
            if (
                path.suffix.lower() not in _PUBLIC_PATH_SUFFIXES
            ):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            relative = path.relative_to(project_root).as_posix()
            violations.extend(_public_path_violations(relative, path, content))
            if len(violations) >= 100:
                violations = violations[:100]
                break
            if len(violations) >= 100:
                break
        if len(violations) >= 100:
            break
    if len(violations) < 100:
        for path in generated_files:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            relative = path.relative_to(project_root).as_posix()
            for violation in _public_path_violations(relative, path, content):
                violation["kind"] = f"generated_{violation['kind']}"
                violations.append(violation)
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
                "generated_files": [
                    path.relative_to(project_root).as_posix() for path in generated_files
                ],
            },
        )
    return _result(
        True,
        "ready" if source_roots or generated_files else "not_applicable",
        detail={
            "violations": [],
            "scanned_roots": [
                path.relative_to(project_root).as_posix() or "." for path in source_roots
            ],
            "generated_files": [
                path.relative_to(project_root).as_posix() for path in generated_files
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
    for relative in ("app", "frontend/src", "pages", "public", "web", "src"):
        candidate = project_root / relative
        if candidate.is_dir():
            roots.append(candidate)
    if (project_root / "index.html").is_file():
        roots.append(project_root)
    return roots


def _public_path_generated_files(project_root: Path) -> list[Path]:
    """返回能证明生产 HTML 资源路径的少量确定性构建清单。"""
    paths: set[Path] = set()
    for pattern in _PUBLIC_PATH_GENERATED_PATTERNS:
        paths.update(path for path in project_root.glob(pattern) if path.is_file())
    return sorted(paths)


def _public_path_violations(relative: str, path: Path, content: str) -> list[dict[str, Any]]:
    """提取单个源码或构建清单中的根绝对浏览器 URL。"""
    patterns = []
    if path.suffix.lower() == ".html":
        patterns.append(("html_attribute", _HTML_ROOT_PATH_RE))
    if path.suffix.lower() == ".css":
        patterns.append(("css_url", _CSS_ROOT_PATH_RE))
    if path.suffix.lower() in {".js", ".jsx", ".svelte", ".ts", ".tsx", ".vue"}:
        patterns.append(("script_url", _SCRIPT_ROOT_PATH_RE))
    violations: list[dict[str, Any]] = []
    for kind, pattern in patterns:
        for match in pattern.finditer(content):
            dot = match.groupdict().get("dot") or ""
            violations.append(
                {
                    "file": relative,
                    "line": content.count("\n", 0, match.start()) + 1,
                    "kind": kind,
                    "value": f"/{dot}{match.group('path')}",
                }
            )
    return violations


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
            for path in _iter_project_files(source_root, _RUNTIME_REFERENCE_EXCLUDED_PARTS)
            if path.suffix.lower() in _RUNTIME_REFERENCE_SUFFIXES
        )
    return sorted(set(paths))


def _inspect_build_input_releasability(project_root: Path) -> list[dict[str, Any]]:
    """确保构建配置静态引用的本地文件会进入远端 Docker 构建上下文。"""
    violations: list[dict[str, Any]] = []
    tracked_files = _git_tracked_files(project_root)
    for config_path in _build_config_paths(project_root):
        try:
            content = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for match in _STATIC_RELATIVE_IMPORT_RE.finditer(content):
            reference = match.group("path").split("?", 1)[0].split("#", 1)[0]
            target = _resolve_relative_import(config_path.parent, reference)
            line_number = content.count("\n", 0, match.start()) + 1
            config_relative = config_path.relative_to(project_root).as_posix()
            if target is None:
                violations.append(
                    {
                        "file": config_relative,
                        "line": line_number,
                        "kind": "build_input_not_releasable",
                        "value": reference,
                        "reason": "referenced file does not exist",
                    }
                )
                continue
            try:
                relative = target.relative_to(project_root).as_posix()
            except ValueError:
                violations.append(
                    {
                        "file": config_relative,
                        "line": line_number,
                        "kind": "build_input_not_releasable",
                        "value": reference,
                        "reason": "referenced file is outside the project build context",
                    }
                )
                continue

            ignored_by_docker = _ignore_file_excludes(
                project_root / ".dockerignore", relative
            )
            ignored_by_git = _ignore_file_excludes(project_root / ".gitignore", relative)
            untracked = tracked_files is not None and relative not in tracked_files
            reason = None
            if ignored_by_docker:
                reason = (
                    "file is ignored by .dockerignore and will be absent from "
                    "the Docker build context"
                )
            elif ignored_by_git and (tracked_files is None or untracked):
                reason = (
                    "file is ignored by .gitignore and is not tracked; it will be absent "
                    "from remote source"
                )
            elif untracked:
                reason = "file is not tracked by Git and will be absent from remote source"
            if reason:
                violations.append(
                    {
                        "file": config_relative,
                        "line": line_number,
                        "kind": "build_input_not_releasable",
                        "value": relative,
                        "reason": reason,
                    }
                )
    return violations


def _build_config_paths(project_root: Path) -> list[Path]:
    return [
        path
        for path in _iter_project_files(project_root, _BUILD_CONFIG_EXCLUDED_PARTS)
        if path.suffix.lower() in _BUILD_CONFIG_SUFFIXES
        and _BUILD_CONFIG_NAME_RE.search(path.name)
    ]


def _resolve_relative_import(parent: Path, reference: str) -> Path | None:
    candidate = (parent / reference).resolve()
    candidates = [candidate]
    if not candidate.suffix:
        candidates.extend(Path(f"{candidate}{suffix}") for suffix in _RELATIVE_IMPORT_SUFFIXES)
        candidates.extend(candidate / f"index{suffix}" for suffix in _RELATIVE_IMPORT_SUFFIXES)
    return next((path for path in candidates if path.is_file()), None)


def _git_tracked_files(project_root: Path) -> set[str] | None:
    if not (project_root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "ls-files", "--cached"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return {line.replace("\\", "/") for line in result.stdout.splitlines() if line}


def _iter_project_files(root: Path, excluded_parts: set[str]) -> list[Path]:
    """在进入依赖和缓存目录前剪枝，避免大型项目合同扫描失控。"""
    files: list[Path] = []
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        directory_names[:] = sorted(
            name for name in directory_names if name not in excluded_parts
        )
        current_path = Path(current)
        for name in sorted(file_names):
            path = current_path / name
            if path.is_file() and not path.is_symlink():
                files.append(path)
    return files


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
        return fnmatchcase(relative, rooted) or fnmatchcase(relative, f"{rooted}/**")
    if "/" not in normalized:
        return any(fnmatchcase(part, normalized) for part in relative_parts)
    return fnmatchcase(relative, normalized) or fnmatchcase(relative, f"{normalized}/**")


def _exclude_from_release_fingerprint(relative: Path) -> bool:
    """判断文件是否仅属于本地状态、依赖、构建产物或运行数据。"""
    parts = relative.parts
    if any(part in _FINGERPRINT_EXCLUDED_PARTS for part in parts):
        return True
    if parts and parts[0] == "data":
        return True
    name = relative.name
    if name.startswith(".env") and name != ".env.example":
        return True
    return relative.suffix.lower() in _FINGERPRINT_EXCLUDED_SUFFIXES


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
