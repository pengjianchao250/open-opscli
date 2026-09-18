"""AppHub 看板迁移任务的状态、审计、门禁和文档生成服务。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.app.domain.exceptions import AppError, AppProjectError
from opscli.app.services.data_contracts import validate_document
from opscli.app.services.gitops import GitRunner

# 新任务使用 Schema v2；读取时继续兼容现有 Schema v1 状态。
MIGRATION_SCHEMA_VERSION = 2
SUPPORTED_MIGRATION_SCHEMA_VERSIONS = {1, MIGRATION_SCHEMA_VERSION}
MIGRATION_STATUSES = {"待实施", "部分完成", "已完成", "blocked", "deferred_attachment"}
DATA_CONTRACT_STATUSES = {
    "candidate",
    "verified",
    "degraded",
    "blocked",
    "deferred_attachment",
}
UI_ITEM_KINDS = {"navigation", "page", "module", "page_state"}
GATE_NAMES = {"inventory", "ui", "data", "release"}
PHASES = (
    "audit",
    "ui_blueprint",
    "ui_skeleton",
    "data_integration",
    "behavior_verification",
    "release_verification",
    "complete",
)
TARGET_REQUIRED_PATHS = (
    ".git",
    ".opscli/app.json",
    "README.md",
    "app.yaml",
    "frontend",
    "backend/app.py",
    "backend/CLAUDE.md",
    "docs/apphub-contract.md",
)
AUDIT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".scss",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {
    ".data",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "output",
}
MIGRATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
DATA_SPEC_START = "<!-- opscli:migration-data:start -->"
DATA_SPEC_END = "<!-- opscli:migration-data:end -->"
# 覆盖矩阵 Schema v2 统一使用复数列表字段，避免剩余问题在导出时丢失。
MATRIX_LIST_FIELDS = ("remaining_issues", "unblock_conditions")


class MigrationService:
    """维护目标项目中的迁移状态，并执行只读审计和阶段门禁。"""

    def __init__(self, *, git_runner: GitRunner | None = None) -> None:
        self.git_runner = git_runner or GitRunner(timeout=15.0)

    def initialize(
        self,
        source: str | Path,
        target: str | Path,
        *,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        """创建迁移任务，并生成首份审计、状态和人类可读文档。"""
        source_root, target_root = self._validate_roots(source, target)
        migration_key = self._migration_id(migration_id)
        migration_root = self._migration_root(target_root, migration_key)
        if migration_root.exists():
            raise AppProjectError(
                "APP-MIGRATION-EXISTS",
                f"迁移任务已存在：{migration_key}",
                fix_hint="使用现有 migration_id，或指定新的 --migration-id。",
            )

        now = _utc_now()
        migration_root.mkdir(parents=True, exist_ok=False)
        migration = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_key,
            "source_root": str(source_root),
            "target_root": str(target_root),
            "phase": "audit",
            "created_at": now,
            "updated_at": now,
        }
        matrix = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_key,
            "statuses": sorted(MIGRATION_STATUSES),
            "items": [],
        }
        blueprint = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_key,
            "shell": {},
            "navigation": [],
            "pages": [],
        }
        self._write_json(migration_root / "migration.json", migration)
        self._write_json(migration_root / "coverage-matrix.json", matrix)
        self._write_json(migration_root / "ui-blueprint.json", blueprint)
        self._write_json(
            target_root / ".opscli" / "migration" / "current.json",
            {"schema_version": MIGRATION_SCHEMA_VERSION, "migration_id": migration_key},
        )

        audit_result = self.audit(target_root, migration_id=migration_key)
        export_result = self.export(target_root, migration_id=migration_key)
        return {
            **self.status(target_root, migration_id=migration_key),
            "audit": audit_result["audit"],
            "documents": export_result["documents"],
            "message": "迁移任务已初始化；请先把审计候选证据整理为逐页逐模块覆盖矩阵。",
        }

    def audit(self, target: str | Path, *, migration_id: str | None = None) -> dict[str, Any]:
        """只读扫描旧项目，并更新候选证据、Git 信息和文件指纹。"""
        context = self._load_context(target, migration_id)
        source_root = Path(context["migration"]["source_root"])
        files = self._scan_source(source_root)
        audit = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": context["migration_id"],
            "scanned_at": _utc_now(),
            "source_root": str(source_root),
            "source_git": self._git_info(source_root),
            "file_fingerprint": self._fingerprint(files),
            "file_count": len(files),
            "candidates": self._candidate_groups(files),
            "files": files,
            "notice": "自动审计只生成候选证据，必须人工或由 Agent 转换为覆盖矩阵。",
        }
        self._write_json(context["root"] / "audit-snapshot.json", audit)
        self._touch_migration(context)
        return {
            "migration_id": context["migration_id"],
            "phase": context["migration"]["phase"],
            "audit": {
                "file_count": audit["file_count"],
                "file_fingerprint": audit["file_fingerprint"],
                "candidate_counts": {
                    key: len(value) for key, value in audit["candidates"].items()
                },
            },
            "message": "旧项目只读审计已更新。",
        }

    def plan(self, target: str | Path, *, migration_id: str | None = None) -> dict[str, Any]:
        """生成迁移计划文档，并把初始阶段推进到 UI 蓝图阶段。"""
        context = self._load_context(target, migration_id)
        if context["migration"]["phase"] == "audit":
            self._set_phase(context, "ui_blueprint")
        result = self.export(target, migration_id=context["migration_id"])
        result["message"] = "迁移计划和规格文档已生成。"
        return result

    def status(self, target: str | Path, *, migration_id: str | None = None) -> dict[str, Any]:
        """汇总当前迁移阶段、覆盖状态、动态模块和阻塞项。"""
        context = self._load_context(target, migration_id)
        items = context["matrix"]["items"]
        counts = Counter(item.get("status", "未知") for item in items)
        dynamic_items = [item for item in items if item.get("dynamic") is True]
        incomplete_items = [
            item.get("id") or "<missing-id>" for item in items if item.get("status") != "已完成"
        ]
        pending_dynamic_items = [
            item.get("id") or "<missing-id>"
            for item in dynamic_items
            if item.get("status") != "已完成"
            or (item.get("data_contract") or {}).get("status") != "verified"
            or (item.get("data_contract") or {}).get("implementation_status") != "verified"
        ]
        blocked_items = [
            item.get("id")
            for item in items
            if item.get("status") in {"blocked", "deferred_attachment"}
        ]
        inventory_problems = self._inventory_problems(context)
        ui_problems = self._ui_problems(context)
        data_problems = self._data_problems(context)
        release_problems = self._release_problems(context)
        data_ready = not data_problems
        release_ready = not release_problems
        delivery_ready = context["migration"]["phase"] == "complete" and release_ready
        return {
            "migration_id": context["migration_id"],
            "schema_version": context["matrix"]["schema_version"],
            "schema_upgrade_required": context["matrix"]["schema_version"] < MIGRATION_SCHEMA_VERSION,
            "phase": context["migration"]["phase"],
            "source_root": context["migration"]["source_root"],
            "target_root": context["migration"]["target_root"],
            "total_items": len(items),
            "status_counts": dict(sorted(counts.items())),
            "dynamic_items": len(dynamic_items),
            "incomplete_items": incomplete_items,
            "pending_dynamic_items": pending_dynamic_items,
            "blocked_items": blocked_items,
            "data_ready": data_ready,
            "release_ready": release_ready,
            "delivery_ready": delivery_ready,
            "next_required_gate": self._next_required_gate(
                inventory_problems,
                ui_problems,
                data_problems,
                release_problems,
            ),
            "gate_problems": {
                "inventory": inventory_problems,
                "ui": ui_problems,
                "data": data_problems,
                "release": release_problems,
            },
            "state_path": str(context["root"]),
            "message": (
                "迁移已完成，可进入交付。"
                if delivery_ready
                else "迁移尚未完成，当前不可交付。"
            ),
        }

    def check(
        self,
        target: str | Path,
        *,
        gate: str,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        """只读执行指定迁移门禁，失败时返回稳定错误码和问题清单。"""
        normalized_gate = gate.strip().lower()
        if normalized_gate not in GATE_NAMES:
            raise AppProjectError(
                "APP-MIGRATION-STATE",
                f"不支持的迁移门禁：{gate}",
                fix_hint=f"gate 必须为：{', '.join(sorted(GATE_NAMES))}。",
            )
        context = self._load_context(target, migration_id)
        problems = self._gate_problems(context, normalized_gate)
        if problems:
            raise AppProjectError(
                "APP-MIGRATION-GATE",
                f"迁移门禁未通过：{normalized_gate}",
                fix_hint="按 detail.problems 修正覆盖矩阵、UI 蓝图或验收证据后重试。",
                detail={"gate": normalized_gate, "problems": problems},
            )
        return {
            "migration_id": context["migration_id"],
            "phase": context["migration"]["phase"],
            "gate": normalized_gate,
            "passed": True,
            "problems": [],
            "message": f"迁移门禁已通过：{normalized_gate}",
        }

    def verify(
        self,
        target: str | Path,
        *,
        gate: str,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        """验证阶段门禁，并在成功后推进迁移阶段。"""
        context = self._load_context(target, migration_id)
        normalized_gate = gate.strip().lower()
        prerequisite_gates = {
            "ui": ("inventory", "ui"),
            "data": ("inventory", "ui", "data"),
            "release": ("inventory", "ui", "data"),
        }
        if normalized_gate not in prerequisite_gates:
            raise AppProjectError(
                "APP-MIGRATION-STATE",
                f"verify 不支持门禁：{gate}",
                fix_hint="使用 ui、data 或 release。",
            )
        for required_gate in prerequisite_gates[normalized_gate]:
            problems = self._gate_problems(context, required_gate)
            if problems:
                raise AppProjectError(
                    "APP-MIGRATION-GATE",
                    f"迁移门禁未通过：{required_gate}",
                    fix_hint="按 detail.problems 修正后重试。",
                    detail={"gate": required_gate, "problems": problems},
                )

        if normalized_gate == "release":
            release_problems = self._gate_problems(context, "release")
            if release_problems:
                raise AppProjectError(
                    "APP-MIGRATION-GATE",
                    "迁移门禁未通过：release",
                    fix_hint="按 detail.problems 修正后重试。",
                    detail={"gate": "release", "problems": release_problems},
                )

        next_phase = {
            "ui": "data_integration",
            "data": "behavior_verification",
            "release": "complete",
        }[normalized_gate]
        self._set_phase(context, next_phase)
        self.export(target, migration_id=context["migration_id"])
        return {
            "migration_id": context["migration_id"],
            "phase": next_phase,
            "gate": normalized_gate,
            "passed": True,
            "problems": [],
            "message": f"迁移门禁已通过，阶段已推进到 {next_phase}。",
        }

    def export(self, target: str | Path, *, migration_id: str | None = None) -> dict[str, Any]:
        """从机器可读状态重新生成迁移计划、UI、数据和验收文档。"""
        context = self._load_context(target, migration_id)
        docs_root = context["target"] / "docs" / "ops-app"
        docs_root.mkdir(parents=True, exist_ok=True)
        documents = {
            "migration_plan": docs_root / "migration-plan.md",
            "ui_spec": docs_root / "ui-spec.md",
            "data_spec": docs_root / "data-spec.md",
            "acceptance": docs_root / "migration-acceptance.md",
        }
        self._write_text(documents["migration_plan"], self._migration_plan(context))
        self._write_text(documents["ui_spec"], self._ui_spec(context))
        self._write_managed_text(
            documents["data_spec"],
            self._data_spec(context),
            start_marker=DATA_SPEC_START,
            end_marker=DATA_SPEC_END,
        )
        self._write_text(documents["acceptance"], self._acceptance(context))
        return {
            "migration_id": context["migration_id"],
            "phase": context["migration"]["phase"],
            "documents": {key: str(path) for key, path in documents.items()},
            "message": "迁移文档已从当前状态重新生成。",
        }

    def _validate_roots(self, source: str | Path, target: str | Path) -> tuple[Path, Path]:
        source_root = Path(source).expanduser().resolve()
        target_root = Path(target).expanduser().resolve()
        if not source_root.is_dir() or not target_root.is_dir():
            raise AppProjectError(
                "APP-MIGRATION-PATH",
                "旧项目和目标项目都必须是已存在的目录。",
                detail={"source": str(source_root), "target": str(target_root)},
            )
        if (
            source_root == target_root
            or source_root in target_root.parents
            or target_root in source_root.parents
        ):
            raise AppProjectError(
                "APP-MIGRATION-PATH",
                "旧项目和目标项目不能相同，也不能互相包含。",
                detail={"source": str(source_root), "target": str(target_root)},
            )
        missing = [item for item in TARGET_REQUIRED_PATHS if not (target_root / item).exists()]
        if missing:
            raise AppProjectError(
                "APP-MIGRATION-TARGET",
                "目标目录不能证明满足当前 AppHub 模板合同。",
                fix_hint="先完成模板克隆、应用绑定和初始化，再执行迁移初始化。",
                detail={"missing": missing, "target": str(target_root)},
            )
        return source_root, target_root

    def _migration_id(self, value: str | None) -> str:
        migration_id = value or datetime.now().strftime("migration-%Y%m%d-%H%M%S")
        if not MIGRATION_ID_RE.fullmatch(migration_id):
            raise AppProjectError(
                "APP-MIGRATION-STATE",
                "migration_id 格式错误。",
                fix_hint="使用 3-64 位字母、数字、点、下划线或连字符。",
            )
        return migration_id

    def _load_context(self, target: str | Path, migration_id: str | None) -> dict[str, Any]:
        target_root = Path(target).expanduser().resolve()
        if not target_root.is_dir():
            raise AppProjectError("APP-MIGRATION-PATH", "目标项目目录不存在。")
        migration_key = self._resolve_migration_id(target_root, migration_id)
        migration_root = self._migration_root(target_root, migration_key)
        migration = self._read_json(migration_root / "migration.json")
        matrix = self._read_json(migration_root / "coverage-matrix.json")
        blueprint = self._read_json(migration_root / "ui-blueprint.json")
        audit_path = migration_root / "audit-snapshot.json"
        audit = self._read_json(audit_path) if audit_path.exists() else None
        self._validate_state(migration_key, migration, matrix, blueprint)
        return {
            "migration_id": migration_key,
            "target": target_root,
            "root": migration_root,
            "migration": migration,
            "matrix": matrix,
            "blueprint": blueprint,
            "audit": audit,
        }

    def _resolve_migration_id(self, target: Path, migration_id: str | None) -> str:
        if migration_id:
            return self._migration_id(migration_id)
        current_path = target / ".opscli" / "migration" / "current.json"
        if not current_path.exists():
            raise AppProjectError(
                "APP-MIGRATION-NOT-FOUND",
                "目标项目没有当前迁移任务。",
                fix_hint="先执行 opscli app migrate init。",
            )
        current = self._read_json(current_path)
        return self._migration_id(str(current.get("migration_id") or ""))

    def _validate_state(
        self,
        migration_id: str,
        migration: dict[str, Any],
        matrix: dict[str, Any],
        blueprint: dict[str, Any],
    ) -> None:
        documents = (migration, matrix, blueprint)
        schema_versions = {doc.get("schema_version") for doc in documents}
        if len(schema_versions) != 1 or not schema_versions.issubset(
            SUPPORTED_MIGRATION_SCHEMA_VERSIONS
        ):
            raise AppProjectError("APP-MIGRATION-STATE", "迁移状态 schema_version 不受支持。")
        if any(doc.get("migration_id") != migration_id for doc in documents):
            raise AppProjectError("APP-MIGRATION-STATE", "迁移状态文件的 migration_id 不一致。")
        if migration.get("phase") not in PHASES:
            raise AppProjectError("APP-MIGRATION-STATE", "迁移阶段值无效。")
        if not isinstance(matrix.get("items"), list) or not isinstance(blueprint.get("pages"), list):
            raise AppProjectError("APP-MIGRATION-STATE", "迁移矩阵或 UI 蓝图格式错误。")
        if matrix.get("schema_version") == MIGRATION_SCHEMA_VERSION:
            problems = self._matrix_schema_problems(matrix["items"])
            if problems:
                raise AppProjectError(
                    "APP-MIGRATION-STATE",
                    "迁移覆盖矩阵不符合 Schema v2。",
                    fix_hint="按 detail.problems 修正字段名、类型和动态数据合同。",
                    detail={"problems": problems},
                )

    def _matrix_schema_problems(self, items: list[Any]) -> list[str]:
        """校验 Schema v2 覆盖项的稳定字段和类型。"""
        problems: list[str] = []
        for index, item in enumerate(items):
            location = f"items[{index}]"
            if not isinstance(item, dict):
                problems.append(f"{location} 必须是对象。")
                continue
            if not isinstance(item.get("id"), str) or not item["id"].strip():
                problems.append(f"{location}.id 必须是非空字符串。")
            if not isinstance(item.get("kind"), str) or not item["kind"].strip():
                problems.append(f"{location}.kind 必须是非空字符串。")
            if item.get("status") not in MIGRATION_STATUSES:
                problems.append(f"{location}.status 使用了无效迁移状态。")
            if not isinstance(item.get("dynamic"), bool):
                problems.append(f"{location}.dynamic 必须是布尔值。")
            if not isinstance(item.get("target"), dict):
                problems.append(f"{location}.target 必须是对象。")
            if not isinstance(item.get("acceptance"), dict):
                problems.append(f"{location}.acceptance 必须是对象。")
            for field in MATRIX_LIST_FIELDS:
                if not isinstance(item.get(field), list):
                    problems.append(f"{location}.{field} 必须是数组。")
            if item.get("dynamic") is True and not isinstance(item.get("data_contract"), dict):
                problems.append(f"{location}.data_contract 必须是对象。")
        return problems

    def _scan_source(self, source: Path) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for path in source.rglob("*"):
            relative = path.relative_to(source)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            if not path.is_file() or path.suffix.lower() not in AUDIT_SUFFIXES:
                continue
            stat = path.stat()
            files.append(
                {
                    "path": relative.as_posix(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "category": self._classify(relative),
                }
            )
        return sorted(files, key=lambda item: item["path"])

    def _classify(self, relative: Path) -> str:
        text = relative.as_posix().lower()
        if any(token in text for token in ("router", "routes", "/route")):
            return "route"
        if any(token in text for token in ("navigation", "navbar", "sidebar", "/menu")):
            return "navigation"
        if any(token in text for token in ("/views/", "/pages/", "page.")):
            return "page"
        if any(token in text for token in ("/api/", "/clients/", "/services/")):
            return "api"
        if any(token in text for token in ("test", "spec")):
            return "test"
        if relative.suffix.lower() in {".yaml", ".yml", ".json"}:
            return "config"
        return "source"

    def _candidate_groups(self, files: list[dict[str, Any]]) -> dict[str, list[str]]:
        groups = {key: [] for key in ("navigation", "route", "page", "api", "test", "config")}
        for item in files:
            category = item["category"]
            if category in groups:
                groups[category].append(item["path"])
        return groups

    def _fingerprint(self, files: list[dict[str, Any]]) -> str:
        payload = "\n".join(
            f"{item['path']}|{item['size']}|{item['mtime_ns']}" for item in files
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _git_info(self, source: Path) -> dict[str, Any]:
        if not (source / ".git").exists():
            return {"detected": False, "branch": None, "commit": None, "status": []}
        try:
            root = self.git_runner.run(source, ["rev-parse", "--show-toplevel"], check=False)
            if root.returncode != 0:
                return {"detected": False, "branch": None, "commit": None, "status": []}
            branch = self.git_runner.run(source, ["rev-parse", "--abbrev-ref", "HEAD"], check=False)
            commit = self.git_runner.run(source, ["rev-parse", "HEAD"], check=False)
            status = self.git_runner.run(source, ["status", "--short"], check=False)
            return {
                "detected": True,
                "root": root.stdout,
                "branch": branch.stdout or None,
                "commit": commit.stdout or None,
                "status": status.stdout.splitlines() if status.stdout else [],
            }
        except AppError as exc:
            return {
                "detected": False,
                "branch": None,
                "commit": None,
                "status": [],
                "error": exc.code,
            }

    def _gate_problems(self, context: dict[str, Any], gate: str) -> list[str]:
        if gate == "inventory":
            return self._inventory_problems(context)
        if gate == "ui":
            return self._ui_problems(context)
        if gate == "data":
            return self._data_problems(context)
        return self._release_problems(context)

    def _inventory_problems(self, context: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        audit = context.get("audit")
        if not audit or not audit.get("file_count"):
            problems.append("旧项目审计快照为空，请重新执行 migrate audit。")
        if not context["matrix"]["items"]:
            problems.append("覆盖矩阵为空，请把审计候选证据整理为导航、页面、模块和状态项。")
        item_ids = [item.get("id") for item in context["matrix"]["items"]]
        if any(not item_id for item_id in item_ids):
            problems.append("覆盖矩阵存在缺少稳定 ID 的项目。")
        duplicate_ids = sorted(
            item_id for item_id, count in Counter(item_ids).items() if item_id and count > 1
        )
        if duplicate_ids:
            problems.append(f"覆盖矩阵存在重复 ID：{', '.join(duplicate_ids)}。")
        return problems

    def _ui_problems(self, context: dict[str, Any]) -> list[str]:
        items = [item for item in context["matrix"]["items"] if item.get("kind") in UI_ITEM_KINDS]
        problems: list[str] = []
        if not items:
            problems.append("覆盖矩阵中没有 UI 项。")
        if not context["blueprint"].get("pages"):
            problems.append("UI 蓝图中没有页面。")
        for item in items:
            item_id = item.get("id") or "<missing-id>"
            if item.get("status") not in MIGRATION_STATUSES:
                problems.append(f"{item_id} 使用了无效迁移状态。")
            elif item.get("status") != "已完成":
                problems.append(f"{item_id} 尚未完成 UI 结构还原。")
            target = item.get("target") or {}
            if not target.get("route") and not target.get("files"):
                problems.append(f"{item_id} 缺少目标路由或目标文件。")
            acceptance = item.get("acceptance") or {}
            if not acceptance.get("evidence"):
                problems.append(f"{item_id} 缺少布局验收证据。")
        return problems

    def _data_problems(self, context: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        dynamic_items = [item for item in context["matrix"]["items"] if item.get("dynamic") is True]
        for item in dynamic_items:
            item_id = item.get("id") or "<missing-id>"
            contract = item.get("data_contract") or {}
            contract_status = contract.get("status")
            if contract_status not in DATA_CONTRACT_STATUSES:
                problems.append(f"{item_id} 缺少有效的数据合同状态。")
                continue
            if contract_status == "candidate":
                problems.append(f"{item_id} 仍是 candidate，尚未完成真实数据合同验证。")
            if contract_status == "verified" and not contract.get("evidence"):
                problems.append(f"{item_id} 的 verified 数据合同缺少验证证据。")
            if contract_status in {"degraded", "blocked", "deferred_attachment"}:
                if not contract.get("evidence"):
                    problems.append(f"{item_id} 的 {contract_status} 状态缺少证据。")
                if not self._item_list(item, "unblock_conditions", "unblock_condition"):
                    problems.append(f"{item_id} 的 {contract_status} 状态缺少解除条件。")
            if item.get("status") == "已完成" and contract_status != "verified":
                problems.append(f"{item_id} 已标记完成，但真实数据合同不是 verified。")
            implementation_status = contract.get("implementation_status")
            if contract_status == "verified" and implementation_status != "verified":
                problems.append(
                    f"{item_id} 的合同已验证，但数据层实现状态不是 verified。"
                )
        problems.extend(self._data_contract_document_problems(context, dynamic_items))
        return list(dict.fromkeys(problems))

    def _data_contract_document_problems(
        self,
        context: dict[str, Any],
        dynamic_items: list[dict[str, Any]],
    ) -> list[str]:
        """校验项目数据合同文件，并核对其与覆盖矩阵的一致性。"""
        if not dynamic_items:
            return []
        contract_path = context["target"] / "docs" / "ops-app" / "data-contracts.json"
        if not contract_path.is_file():
            return ["项目缺少 docs/ops-app/data-contracts.json。"]
        try:
            document = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"data-contracts.json 无法读取：{exc}。"]

        problems = [
            f"data-contracts.json {problem}"
            for problem in validate_document(
                document,
                mode="delivery",
                project_root=context["target"],
            )
        ]
        products = document.get("products") if isinstance(document, dict) else None
        product_map = {
            product.get("product_key"): product
            for product in products or []
            if isinstance(product, dict) and product.get("product_key")
        }
        for item in dynamic_items:
            item_id = item.get("id") or "<missing-id>"
            matrix_contract = item.get("data_contract") or {}
            product_key = matrix_contract.get("product_key")
            if not product_key:
                problems.append(f"{item_id} 缺少 data_contract.product_key。")
                continue
            product = product_map.get(product_key)
            if product is None:
                problems.append(
                    f"{item_id} 的数据产品 {product_key} 未登记在 data-contracts.json。"
                )
                continue
            if matrix_contract.get("status") != product.get("contract_status"):
                problems.append(f"{item_id} 的合同状态与 data-contracts.json 不一致。")
            if matrix_contract.get("implementation_status") != product.get(
                "implementation_status"
            ):
                problems.append(f"{item_id} 的实现状态与 data-contracts.json 不一致。")
        return problems

    def _release_problems(self, context: dict[str, Any]) -> list[str]:
        problems = [*self._ui_problems(context), *self._data_problems(context)]
        for item in context["matrix"]["items"]:
            item_id = item.get("id") or "<missing-id>"
            if item.get("status") != "已完成":
                problems.append(f"{item_id} 尚未达到发布完成状态。")
            acceptance = item.get("acceptance") or {}
            if not acceptance.get("checks"):
                problems.append(f"{item_id} 缺少验收检查。")
            if not acceptance.get("evidence"):
                problems.append(f"{item_id} 缺少验收证据。")
        return list(dict.fromkeys(problems))

    def _item_list(self, item: dict[str, Any], plural: str, singular: str) -> list[str]:
        """兼容读取 Schema v2 列表字段和 Schema v1 单数字段。"""
        value = item.get(plural)
        if isinstance(value, list):
            return [str(entry) for entry in value if str(entry).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        legacy = item.get(singular)
        if isinstance(legacy, list):
            return [str(entry) for entry in legacy if str(entry).strip()]
        if isinstance(legacy, str) and legacy.strip():
            return [legacy.strip()]
        return []

    def _next_required_gate(
        self,
        inventory_problems: list[str],
        ui_problems: list[str],
        data_problems: list[str],
        release_problems: list[str],
    ) -> str | None:
        """按门禁顺序返回下一项必须完成的检查。"""
        if inventory_problems:
            return "inventory"
        if ui_problems:
            return "ui"
        if data_problems:
            return "data"
        if release_problems:
            return "release"
        return None

    def _migration_plan(self, context: dict[str, Any]) -> str:
        audit = context.get("audit") or {}
        candidate_counts = {
            key: len(value) for key, value in (audit.get("candidates") or {}).items()
        }
        return (
            "# 迁移重构计划\n\n"
            f"- 迁移 ID：`{context['migration_id']}`\n"
            f"- 当前阶段：`{context['migration']['phase']}`\n"
            f"- 旧项目：`{context['migration']['source_root']}`\n"
            f"- 目标项目：`{context['migration']['target_root']}`\n"
            f"- 审计文件数：`{audit.get('file_count', 0)}`\n"
            f"- 候选分类：`{json.dumps(candidate_counts, ensure_ascii=False)}`\n\n"
            "## 实施顺序\n\n"
            "1. 把审计候选证据整理为逐页逐模块覆盖矩阵。\n"
            "2. 完成导航、路由、页面区域、模块顺序和父子层级的 UI 蓝图。\n"
            "3. 在目标模板内完成 UI 骨架并通过 `verify-ui`。\n"
            "4. 使用 `ops-app-data-builder` 逐模块验证真实数据合同并通过 `verify-data`。\n"
            "5. 补齐业务交互、页面状态、测试和证据，通过 `verify-release`。\n\n"
            "## 覆盖矩阵\n\n"
            f"{self._matrix_table(context['matrix']['items'])}\n"
        )

    def _ui_spec(self, context: dict[str, Any]) -> str:
        blueprint = context["blueprint"]
        return (
            "# UI 结构规格\n\n"
            f"- 迁移 ID：`{context['migration_id']}`\n"
            f"- 页面数量：`{len(blueprint.get('pages', []))}`\n\n"
            "UI 验收优先检查导航、路由、模块层级、顺序、栅格和页面状态；字体与颜色细节后置。\n\n"
            "## 应用壳层\n\n"
            f"```json\n{json.dumps(blueprint.get('shell', {}), ensure_ascii=False, indent=2)}\n```\n\n"
            "## 导航\n\n"
            f"```json\n{json.dumps(blueprint.get('navigation', []), ensure_ascii=False, indent=2)}\n```\n\n"
            "## 页面\n\n"
            f"```json\n{json.dumps(blueprint.get('pages', []), ensure_ascii=False, indent=2)}\n```\n"
        )

    def _data_spec(self, context: dict[str, Any]) -> str:
        dynamic_items = [item for item in context["matrix"]["items"] if item.get("dynamic") is True]
        rows = [
            "| 模块 | 迁移状态 | 数据产品 | 合同状态 | 实现状态 | 证据 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in dynamic_items:
            contract = item.get("data_contract") or {}
            rows.append(
                "| {id} | {status} | {product} | {contract_status} | {implementation_status} | {evidence} |".format(
                    id=item.get("id", ""),
                    status=item.get("status", ""),
                    product=contract.get("product_key", ""),
                    contract_status=contract.get("status", ""),
                    implementation_status=contract.get("implementation_status", ""),
                    evidence="<br>".join(contract.get("evidence") or []),
                )
            )
        if not dynamic_items:
            rows.append("| - | - | - | - | - | 尚未登记动态数据模块 |")
        return (
            "## 迁移覆盖矩阵数据状态\n\n"
            f"- 迁移 ID：`{context['migration_id']}`\n"
            "- 合同 `verified` 只代表上游合同已确认；数据层实现也必须为 `verified` 才能通过数据门禁。\n\n"
            + "\n".join(rows)
            + "\n"
        )

    def _acceptance(self, context: dict[str, Any]) -> str:
        data_problems = self._data_problems(context)
        release_problems = self._release_problems(context)
        release_ready = not release_problems
        delivery_ready = context["migration"]["phase"] == "complete" and release_ready
        problem_rows = release_problems or ["无"]
        return (
            "# 迁移验收报告\n\n"
            f"- 迁移 ID：`{context['migration_id']}`\n"
            f"- 当前阶段：`{context['migration']['phase']}`\n"
            f"- 数据门禁就绪：`{str(not data_problems).lower()}`\n"
            f"- 发布门禁就绪：`{str(release_ready).lower()}`\n"
            f"- 可交付：`{str(delivery_ready).lower()}`\n"
            f"- 生成时间：`{_utc_now()}`\n\n"
            "## 逐项状态\n\n"
            f"{self._matrix_table(context['matrix']['items'])}\n\n"
            "## 未完成问题\n\n"
            + "\n".join(f"- {problem}" for problem in problem_rows)
            + "\n\n"
            "未实际执行的测试、浏览器验收、真实数据联调或线上验证不得填写为通过。\n"
        )

    def _matrix_table(self, items: list[dict[str, Any]]) -> str:
        rows = [
            "| ID | 类型 | 状态 | 动态数据 | 目标路由 | 剩余问题 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in items:
            target = item.get("target") or {}
            rows.append(
                "| {id} | {kind} | {status} | {dynamic} | {route} | {issue} |".format(
                    id=item.get("id", ""),
                    kind=item.get("kind", ""),
                    status=item.get("status", ""),
                    dynamic="是" if item.get("dynamic") is True else "否",
                    route=target.get("route", ""),
                    issue="<br>".join(
                        self._item_list(item, "remaining_issues", "remaining_issue")
                    ),
                )
            )
        if not items:
            rows.append("| - | - | - | - | - | 覆盖矩阵尚未建立 |")
        return "\n".join(rows)

    def _set_phase(self, context: dict[str, Any], phase: str) -> None:
        context["migration"]["phase"] = phase
        context["migration"]["updated_at"] = _utc_now()
        self._write_json(context["root"] / "migration.json", context["migration"])

    def _touch_migration(self, context: dict[str, Any]) -> None:
        context["migration"]["updated_at"] = _utc_now()
        self._write_json(context["root"] / "migration.json", context["migration"])

    def _migration_root(self, target: Path, migration_id: str) -> Path:
        return target / ".opscli" / "migration" / migration_id

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AppProjectError(
                "APP-MIGRATION-NOT-FOUND",
                f"迁移状态文件不存在：{path.name}",
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise AppProjectError(
                "APP-MIGRATION-STATE",
                f"迁移状态文件无法读取：{path}",
            ) from exc
        if not isinstance(payload, dict):
            raise AppProjectError("APP-MIGRATION-STATE", f"迁移状态文件必须是 JSON 对象：{path}")
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._write_text(path, content)

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 同目录临时文件配合 replace，避免中断时留下半份迁移状态。
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        os.replace(temp_path, path)

    def _write_managed_text(
        self,
        path: Path,
        content: str,
        *,
        start_marker: str,
        end_marker: str,
    ) -> None:
        """只替换 Markdown 的受管区块，保留业务人员维护的其他内容。"""
        managed_block = f"{start_marker}\n{content.rstrip()}\n{end_marker}\n"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        start = existing.find(start_marker)
        end = existing.find(end_marker)
        if start >= 0 and end >= start:
            end += len(end_marker)
            merged = existing[:start].rstrip() + "\n\n" + managed_block + existing[end:].lstrip("\r\n")
        elif existing.strip():
            merged = existing.rstrip() + "\n\n" + managed_block
        else:
            merged = "# 真实数据规格\n\n" + managed_block
        self._write_text(path, merged)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
