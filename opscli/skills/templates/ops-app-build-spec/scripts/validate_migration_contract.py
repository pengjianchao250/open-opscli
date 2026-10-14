"""执行迁移项目的三项标准验证合同并固化可推送证据。"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.app.services.migration_contract import (
    inspect_migration_release_assets,
    migration_release_fingerprint,
)

OUTPUT_LIMIT = 4000


def validate_migration(
    project_root: str | Path,
    *,
    local_check: list[str],
    apphub_check: list[str],
    parity_check: list[str] | None = None,
    require_parity: bool = False,
    timeout: int = 180,
) -> dict[str, Any]:
    """执行轻量运行兼容检查和发布门禁，并写入验证清单。"""
    root = Path(project_root).expanduser().resolve()
    integrity = _inspect_migration_integrity(root)
    commands = _run_checks(
        root,
        local_check=local_check,
        apphub_check=apphub_check,
        parity_check=parity_check,
        require_parity=require_parity,
        timeout=timeout,
    )
    dual_runtime_ready = all(result["passed"] for result in commands.values())
    expected_app_id = integrity.get("app_id")
    release_assets = inspect_migration_release_assets(
        root,
        expected_app_id=expected_app_id if isinstance(expected_app_id, str) else None,
    )
    fingerprint = migration_release_fingerprint(root)
    contracts = {
        "migration_integrity": {
            "passed": integrity["passed"],
            "checks": integrity["checks"],
        },
        "dual_runtime": {
            "passed": dual_runtime_ready,
            "mode": "lightweight_runtime_compatibility",
            "checks": {
                "local_runtime": commands["local"]["passed"],
                "apphub_runtime": commands["apphub"]["passed"],
                "business_parity": commands["parity"]["passed"],
                "business_parity_required": require_parity,
                "business_parity_status": commands["parity"]["status"],
            },
        },
        "release_gate": {
            "passed": release_assets["ready"],
            "checks": release_assets,
        },
    }
    release_ready = all(contract["passed"] for contract in contracts.values())
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "migration_id": integrity.get("migration_id"),
        "contracts": contracts,
        "commands": commands,
        "release_fingerprint": fingerprint,
        "release_ready": release_ready,
    }
    manifest_path = _validation_manifest_path(root, integrity.get("migration_id"))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result["validation_manifest"] = str(manifest_path)
    return result


def _run_checks(
    root: Path,
    *,
    local_check: list[str],
    apphub_check: list[str],
    parity_check: list[str] | None,
    require_parity: bool,
    timeout: int,
) -> dict[str, dict[str, Any]]:
    """执行必要冒烟检查，并在同一次验证中复用完全相同的命令结果。"""
    checks = {
        "local": (local_check, True),
        "apphub": (apphub_check, True),
        "parity": (parity_check, require_parity),
    }
    cache: dict[tuple[str, ...], tuple[str, dict[str, Any]]] = {}
    results: dict[str, dict[str, Any]] = {}
    for name, (command, required) in checks.items():
        if command is None:
            results[name] = _skipped_command(required=required)
            continue
        cache_key = tuple(command)
        cached = cache.get(cache_key)
        if cached is not None:
            source_name, source_result = cached
            results[name] = {
                **source_result,
                "status": "reused",
                "reused_from": source_name,
            }
            continue
        result = _run_command(root, command, timeout)
        cache[cache_key] = (name, result)
        results[name] = result
    return results


def _inspect_migration_integrity(root: Path) -> dict[str, Any]:
    marker_path = root / ".opscli" / "project.json"
    marker = _read_json_object(marker_path)
    migration_id = marker.get("migration_id")
    migration_dir = root / ".opscli" / "migration" / str(migration_id or "")
    source_value = marker.get("source_root")
    source = (
        Path(source_value).expanduser().resolve()
        if isinstance(source_value, str) and source_value.strip()
        else None
    )
    target_independent = bool(
        source
        and source != root
        and source not in root.parents
        and root not in source.parents
    )
    state = _read_json_object(migration_dir / "migration.json")
    adaptation = _read_json_object(migration_dir / "adaptation-manifest.json")
    required_state = (
        "copy-manifest.json",
        "startup-manifest.json",
        "adaptation-manifest.json",
        "migration.json",
    )
    checks = {
        "migration_marker": marker.get("origin_type") == "migration_copy",
        "migration_id": isinstance(migration_id, str) and bool(migration_id.strip()),
        "source_exists": bool(source and source.is_dir()),
        "target_independent": target_independent,
        "state_complete": all((migration_dir / name).is_file() for name in required_state),
        "migration_verified": bool(state.get("delivery_ready")),
        "adaptation_ready": adaptation.get("status") == "ready",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "migration_id": migration_id,
        "app_id": state.get("app_id"),
    }


def _run_command(root: Path, command: list[str], timeout: int) -> dict[str, Any]:
    """以参数数组运行项目自有检查，禁止 shell 字符串插值。"""
    if not command or not all(isinstance(item, str) and item for item in command):
        return {
            "passed": False,
            "status": "invalid_command",
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": "检查命令必须是非空字符串数组。",
        }
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "passed": False,
            "status": "failed_to_run",
            "command": command,
            "exit_code": None,
            "stdout": _truncate(getattr(exc, "stdout", "") or ""),
            "stderr": _truncate(str(exc)),
        }
    return {
        "passed": completed.returncode == 0,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": command,
        "exit_code": completed.returncode,
        "stdout": _truncate(completed.stdout),
        "stderr": _truncate(completed.stderr),
    }


def _skipped_command(*, required: bool) -> dict[str, Any]:
    """返回条件检查未触发或缺少必需命令的标准结果。"""
    return {
        "passed": not required,
        "status": "missing_required_command" if required else "not_required",
        "command": None,
        "exit_code": None,
        "stdout": "",
        "stderr": "缺少风险触发后的业务一致性检查命令。" if required else "",
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _validation_manifest_path(root: Path, migration_id: Any) -> Path:
    key = str(migration_id).strip() if migration_id is not None else "unknown"
    return root / ".opscli" / "migration" / key / "validation-manifest.json"


def _truncate(value: str) -> str:
    return value if len(value) <= OUTPUT_LIMIT else value[:OUTPUT_LIMIT] + "\n...<truncated>"


def _json_command(value: str) -> list[str]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"命令不是有效 JSON：{exc}") from exc
    if not isinstance(payload, list) or not payload or not all(
        isinstance(item, str) and item for item in payload
    ):
        raise argparse.ArgumentTypeError("命令必须是非空 JSON 字符串数组。")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行 AppHub 迁移项目标准验证合同")
    parser.add_argument("project_root", type=Path, help="迁移目标项目根目录")
    parser.add_argument("--local-check-json", required=True, type=_json_command)
    parser.add_argument("--apphub-check-json", required=True, type=_json_command)
    parser.add_argument("--parity-check-json", type=_json_command)
    parser.add_argument(
        "--require-parity",
        action="store_true",
        help="迁移改动触发高风险条件时，强制要求业务一致性检查",
    )
    parser.add_argument("--timeout", type=int, default=180)
    return parser


def main() -> int:
    arguments = _build_parser().parse_args()
    result = validate_migration(
        arguments.project_root,
        local_check=arguments.local_check_json,
        apphub_check=arguments.apphub_check_json,
        parity_check=arguments.parity_check_json,
        require_parity=arguments.require_parity,
        timeout=arguments.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
