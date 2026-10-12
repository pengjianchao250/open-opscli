"""根据迁移启动证据应用可审计、可重复执行的运行时适配策略。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable


# Vinext 构建后归一化脚本使用固定文件名，便于幂等识别和迁移清单追踪。
_VINEXT_NORMALIZER = Path("scripts") / "normalize_apphub_public_paths.mjs"
# 构建脚本追加固定命令，不覆盖项目已有 postbuild 生命周期。
_VINEXT_BUILD_SUFFIX = "node scripts/normalize_apphub_public_paths.mjs"
# Vite 支持的项目级配置文件名，按常见优先级查找且不猜测多配置项目。
_VITE_CONFIG_NAMES = (
    "vite.config.ts",
    "vite.config.mts",
    "vite.config.js",
    "vite.config.mjs",
    "vite.config.cts",
    "vite.config.cjs",
)


def apply_migration_runtime_adaptations(
    root: Path,
    startup: dict[str, Any],
) -> dict[str, Any]:
    """按启动清单选择适配策略，并返回统一的适配结果。"""
    results: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    for runtime in _runtime_candidates(startup):
        evidence = runtime.get("evidence")
        if not isinstance(evidence, str) or evidence in seen_evidence:
            continue
        seen_evidence.add(evidence)
        for strategy in _RUNTIME_ADAPTATION_STRATEGIES:
            result = strategy(root, runtime)
            if result is not None:
                results.append(result)
                break

    managed_files = sorted(
        {
            relative
            for result in results
            for relative in result.get("managed_files", [])
            if isinstance(relative, str) and relative
        }
    )
    if any(result.get("status") == "adaptation_manual_required" for result in results):
        status = "adaptation_manual_required"
    elif results:
        status = "ready"
    else:
        status = "not_applicable"
    return {
        "status": status,
        "strategies": results,
        "managed_files": managed_files,
    }


def _runtime_candidates(startup: dict[str, Any]) -> list[dict[str, Any]]:
    """返回包含真实包清单证据的 Node 运行时，避免依赖固定目录名。"""
    candidates: list[dict[str, Any]] = []
    for key in ("frontend", "runtime", "backend", "docker"):
        runtime = startup.get(key)
        if not isinstance(runtime, dict) or runtime.get("kind") != "node_web":
            continue
        evidence = runtime.get("evidence")
        if isinstance(evidence, str) and Path(evidence).name == "package.json":
            candidates.append(runtime)
    return candidates


def _adapt_vinext_node_web(
    root: Path,
    runtime: dict[str, Any],
) -> dict[str, Any] | None:
    """为 Vinext 项目补齐动态前缀安全的构建链路。"""
    package_path = _safe_project_file(root, runtime.get("evidence"))
    if package_path is None or package_path.name != "package.json":
        return None
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(package, dict) or not _is_vinext_package(package):
        return None

    package_root = package_path.parent
    scripts = package.get("scripts")
    build_command = scripts.get("build") if isinstance(scripts, dict) else None
    if not isinstance(build_command, str) or not build_command.strip():
        return _manual_vinext_result(root, package_path, "build_script_missing")

    vite_plan = _plan_vite_base(package_root)
    if vite_plan["status"] != "ready":
        return _manual_vinext_result(
            root,
            package_path,
            str(vite_plan["reason"]),
            detail=vite_plan.get("detail"),
        )

    normalizer_path = package_root / _VINEXT_NORMALIZER
    normalizer_content = _vinext_normalizer_source()
    if normalizer_path.is_file():
        try:
            existing_normalizer = normalizer_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return _manual_vinext_result(root, package_path, "normalizer_unreadable")
        if existing_normalizer != normalizer_content:
            return _manual_vinext_result(root, package_path, "normalizer_path_conflict")

    changed_files: list[str] = []
    vite_path = Path(str(vite_plan["path"]))
    vite_content = str(vite_plan["content"])
    if not vite_path.is_file() or vite_path.read_text(encoding="utf-8") != vite_content:
        _write_text(vite_path, vite_content)
        changed_files.append(vite_path.relative_to(root).as_posix())

    if not normalizer_path.is_file():
        _write_text(normalizer_path, normalizer_content)
        changed_files.append(normalizer_path.relative_to(root).as_posix())

    if _VINEXT_BUILD_SUFFIX not in build_command:
        scripts["build"] = f"{build_command.rstrip()} && {_VINEXT_BUILD_SUFFIX}"
        _write_text(package_path, json.dumps(package, ensure_ascii=False, indent=2) + "\n")
        changed_files.append(package_path.relative_to(root).as_posix())

    managed_files = sorted(
        {
            package_path.relative_to(root).as_posix(),
            vite_path.relative_to(root).as_posix(),
            normalizer_path.relative_to(root).as_posix(),
        }
    )
    return {
        "name": "vinext_node_web",
        "status": "ready",
        "runtime_cwd": runtime.get("cwd"),
        "evidence": package_path.relative_to(root).as_posix(),
        "managed_files": managed_files,
        "changed_files": sorted(changed_files),
        "detail": {
            "vite_config": vite_path.relative_to(root).as_posix(),
            "normalizer": normalizer_path.relative_to(root).as_posix(),
            "existing_postbuild_preserved": isinstance(scripts.get("postbuild"), str),
        },
    }


def _is_vinext_package(package: dict[str, Any]) -> bool:
    """同时使用依赖和脚本证据识别 Vinext，兼容依赖放在不同区块。"""
    dependency_names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        dependencies = package.get(key)
        if isinstance(dependencies, dict):
            dependency_names.update(str(name) for name in dependencies)
    scripts = package.get("scripts")
    script_values = scripts.values() if isinstance(scripts, dict) else []
    return "vinext" in dependency_names or any(
        isinstance(value, str) and re.search(r"(?:^|\s)vinext(?:\s|$)", value)
        for value in script_values
    )


def _plan_vite_base(package_root: Path) -> dict[str, Any]:
    """生成 Vite 相对 base 的确定性写入计划，不直接修改文件。"""
    configs = [
        package_root / name
        for name in _VITE_CONFIG_NAMES
        if (package_root / name).is_file()
    ]
    if len(configs) > 1:
        return {
            "status": "adaptation_manual_required",
            "reason": "multiple_vite_configs",
            "detail": {"files": [path.name for path in configs]},
        }
    if not configs:
        path = package_root / "vite.config.mjs"
        content = (
            "import { defineConfig } from 'vite';\n"
            "import vinext from 'vinext';\n\n"
            "export default defineConfig({\n"
            "  base: './',\n"
            "  plugins: [vinext()],\n"
            "});\n"
        )
        return {"status": "ready", "reason": "config_created", "path": path, "content": content}

    path = configs[0]
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {"status": "adaptation_manual_required", "reason": "vite_config_unreadable"}

    literal_base = re.compile(
        r"(?m)^(?P<indent>\s*)base\s*:\s*(?P<quote>['\"])(?P<value>[^'\"]*)(?P=quote)"
    )
    matches = list(literal_base.finditer(content))
    if len(matches) > 1:
        return {"status": "adaptation_manual_required", "reason": "multiple_vite_base_values"}
    if matches:
        match = matches[0]
        if match.group("value") == "./":
            return {"status": "ready", "reason": "base_present", "path": path, "content": content}
        updated = content[: match.start("value")] + "./" + content[match.end("value") :]
        return {"status": "ready", "reason": "base_replaced", "path": path, "content": updated}
    if re.search(r"(?m)^\s*base\s*:", content):
        return {"status": "adaptation_manual_required", "reason": "dynamic_vite_base"}

    insertion = _vite_base_insertion(content)
    if insertion is None:
        return {"status": "adaptation_manual_required", "reason": "vite_config_shape_unsupported"}
    offset, indent = insertion
    updated = content[:offset] + f"\n{indent}base: './'," + content[offset:]
    return {"status": "ready", "reason": "base_inserted", "path": path, "content": updated}


def _vite_base_insertion(content: str) -> tuple[int, str] | None:
    """只适配可唯一识别的顶层配置对象，复杂配置交给人工处理。"""
    return_matches = list(re.finditer(r"(?m)^(?P<indent>\s*)return\s*\{", content))
    if len(return_matches) == 1:
        match = return_matches[0]
        return match.end(), match.group("indent") + "  "

    patterns = (
        re.compile(r"defineConfig\s*\(\s*\{"),
        re.compile(r"defineConfig\s*\(\s*(?:async\s*)?\([^)]*\)\s*=>\s*\(\s*\{"),
        re.compile(r"(?m)^(?P<indent>\s*)export\s+default\s*\{"),
    )
    for pattern in patterns:
        matches = list(pattern.finditer(content))
        if len(matches) != 1:
            continue
        match = matches[0]
        indent = match.groupdict().get("indent") or _line_indent(content, match.start())
        return match.end(), indent + "  "
    return None


def _line_indent(content: str, offset: int) -> str:
    """返回指定位置所在行的缩进。"""
    line_start = content.rfind("\n", 0, offset) + 1
    prefix = content[line_start:offset]
    return prefix[: len(prefix) - len(prefix.lstrip())]


def _safe_project_file(root: Path, value: Any) -> Path | None:
    """把清单相对路径限制在迁移目标内，拒绝绝对路径和目录穿越。"""
    if not isinstance(value, str) or not value:
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _manual_vinext_result(
    root: Path,
    package_path: Path,
    reason: str,
    *,
    detail: Any = None,
) -> dict[str, Any]:
    """生成统一的 Vinext 人工适配结果。"""
    return {
        "name": "vinext_node_web",
        "status": "adaptation_manual_required",
        "evidence": package_path.relative_to(root).as_posix(),
        "reason": reason,
        "managed_files": [],
        "detail": detail or {},
    }


def _write_text(path: Path, content: str) -> None:
    """以临时文件替换方式写入适配文件，避免中断后留下半文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _vinext_normalizer_source() -> str:
    """返回 Vinext 生产清单归一化脚本源码。"""
    return r'''import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const serverRoot = path.resolve('dist/server');
const targetNames = new Set(['__vite_rsc_assets_manifest.js', 'vinext-client-assets.js']);
const unsafePattern = /(["'`])\/(?:\.\/)?_next\//g;

async function collect(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await collect(target)));
    else if (entry.isFile() && targetNames.has(entry.name)) files.push(target);
  }
  return files;
}

const files = await collect(serverRoot);
if (files.length === 0) {
  throw new Error(`Vinext asset manifests were not found under ${serverRoot}`);
}

let replacements = 0;
for (const file of files) {
  const original = await readFile(file, 'utf8');
  const normalized = original.replace(unsafePattern, (_match, quote) => {
    replacements += 1;
    return `${quote}./_next/`;
  });
  unsafePattern.lastIndex = 0;
  if (unsafePattern.test(normalized)) {
    throw new Error(`Unsafe Vinext asset path remains in ${file}`);
  }
  unsafePattern.lastIndex = 0;
  if (normalized !== original) await writeFile(file, normalized, 'utf8');
}

console.log(`[opscli] normalized ${replacements} Vinext asset paths in ${files.length} manifests`);
'''


# 策略注册表按顺序匹配，后续运行时只需新增独立策略而不改迁移主流程。
_RUNTIME_ADAPTATION_STRATEGIES: tuple[
    Callable[[Path, dict[str, Any]], dict[str, Any] | None], ...
] = (_adapt_vinext_node_web,)
