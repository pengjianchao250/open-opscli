"""AppHub 看板迁移状态、审计和门禁测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.migration import MigrationService


def _target_project(root: Path) -> Path:
    target = root / "target"
    for relative in (
        ".git/HEAD",
        ".opscli/app.json",
        "README.md",
        "app.yaml",
        "backend/app.py",
        "backend/CLAUDE.md",
        "docs/apphub-contract.md",
        "frontend/package.json",
    ):
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    return target


def _source_project(root: Path) -> Path:
    source = root / "legacy"
    (source / "frontend/src/views").mkdir(parents=True)
    (source / "frontend/src/router").mkdir(parents=True)
    (source / "frontend/src/views/Sales.vue").write_text("<template />\n", encoding="utf-8")
    (source / "frontend/src/router/index.ts").write_text("export default []\n", encoding="utf-8")
    return source


def _state_path(target: Path, name: str) -> Path:
    return target / ".opscli" / "migration" / "migration-demo" / name


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _implementation_artifacts(target: Path, *, placeholder: bool = False) -> dict[str, list[str]]:
    """创建数据门禁需要的最小项目工件。"""
    artifacts = {
        "backend_api": ["backend/api/v1/sales.py"],
        "backend_service": ["backend/services/sales_service.py"],
        "backend_schema": ["backend/schemas/sales.py"],
        "frontend_consumer": ["frontend/src/views/SalesView.vue"],
        "tests": ["tests/api/test_sales.py"],
        "openapi": ["docs/openapi.json"],
    }
    for group, paths in artifacts.items():
        for relative in paths:
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            content = "仅用于布局验证\n" if placeholder and group == "frontend_consumer" else "ok\n"
            path.write_text(content, encoding="utf-8")
    return artifacts


def _write_verified_contract(
    target: Path,
    artifacts: dict[str, list[str]],
    *,
    implementation_status: str = "verified",
) -> None:
    """写入与迁移矩阵一致的 OPS 数据合同凭证。"""
    contract_path = target / "docs/ops-app/data-contracts.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    _write(
        contract_path,
        {
            "schema_version": "1.0",
            "products": [
                {
                    "product_key": "sales",
                    "source": "ops",
                    "contract_status": "verified",
                    "requires_real_data": True,
                    "verification": {
                        "attempted": True,
                        "attempted_at": "2026-09-17T10:00:00+08:00",
                        "method": "opscli query flow",
                        "outcome": "success",
                    },
                    "technical_contract": {
                        "dataset_alias": "sales_dataset",
                        "table_id": "table-sales",
                        "required_business_roles": ["orders"],
                        "fields": {
                            "orders": {
                                "field_name": "orders",
                                "role": "metric",
                                "aggregation": "sum",
                                "result_alias": "orders",
                            }
                        },
                    },
                    "implementation_status": implementation_status,
                    "implementation_artifacts": artifacts,
                }
            ],
        },
    )


def _completed_page_item() -> dict:
    """构造已经通过 UI 结构验收的页面覆盖项。"""
    return {
        "id": "PAGE-001",
        "kind": "page",
        "status": "已完成",
        "dynamic": False,
        "target": {"route": "/sales", "files": ["frontend/src/views/SalesView.vue"]},
        "acceptance": {"checks": ["layout"], "evidence": ["evidence/ui/PAGE-001.png"]},
        "remaining_issues": [],
        "unblock_conditions": [],
    }


def test_initialize_creates_state_and_never_writes_source(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    data_spec = target / "docs/ops-app/data-spec.md"
    data_spec.parent.mkdir(parents=True, exist_ok=True)
    data_spec.write_text("# 真实数据规格\n\n业务口径必须保留。\n", encoding="utf-8")
    before = sorted(path.relative_to(source).as_posix() for path in source.rglob("*"))

    result = MigrationService().initialize(source, target, migration_id="migration-demo")

    after = sorted(path.relative_to(source).as_posix() for path in source.rglob("*"))
    assert before == after
    assert result["migration_id"] == "migration-demo"
    assert result["audit"]["file_count"] == 2
    assert _state_path(target, "migration.json").exists()
    assert _state_path(target, "audit-snapshot.json").exists()
    assert _state_path(target, "coverage-matrix.json").exists()
    assert _state_path(target, "ui-blueprint.json").exists()
    assert (target / "docs/ops-app/migration-plan.md").exists()
    exported_data_spec = data_spec.read_text(encoding="utf-8")
    assert "业务口径必须保留。" in exported_data_spec
    assert "<!-- opscli:migration-data:start -->" in exported_data_spec


@pytest.mark.parametrize("relation", ["same", "source-parent", "target-parent"])
def test_initialize_rejects_same_or_nested_paths(tmp_path: Path, relation: str) -> None:
    target = _target_project(tmp_path)
    source = _source_project(tmp_path)
    if relation == "same":
        source = target
    elif relation == "source-parent":
        source = tmp_path
    else:
        nested = source / "target"
        nested.mkdir()
        target = nested

    with pytest.raises(AppProjectError) as exc_info:
        MigrationService().initialize(source, target, migration_id="migration-demo")

    assert exc_info.value.code == "APP-MIGRATION-PATH"


def test_initialize_rejects_non_template_target(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    target = tmp_path / "target"
    target.mkdir()

    with pytest.raises(AppProjectError) as exc_info:
        MigrationService().initialize(source, target, migration_id="migration-demo")

    assert exc_info.value.code == "APP-MIGRATION-TARGET"
    assert "backend/app.py" in exc_info.value.detail["missing"]


def test_inventory_gate_rejects_duplicate_ids(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    service = MigrationService()
    service.initialize(source, target, migration_id="migration-demo")
    matrix_path = _state_path(target, "coverage-matrix.json")
    matrix = _load(matrix_path)
    matrix["items"] = [
        {
            "id": "PAGE-001",
            "kind": "page",
            "status": "待实施",
            "dynamic": False,
            "target": {},
            "acceptance": {},
            "remaining_issues": [],
            "unblock_conditions": [],
        },
        {
            "id": "PAGE-001",
            "kind": "page",
            "status": "待实施",
            "dynamic": False,
            "target": {},
            "acceptance": {},
            "remaining_issues": [],
            "unblock_conditions": [],
        },
    ]
    _write(matrix_path, matrix)

    with pytest.raises(AppProjectError) as exc_info:
        service.check(target, gate="inventory")

    assert "重复 ID" in "\n".join(exc_info.value.detail["problems"])


def test_ui_gate_requires_matrix_blueprint_and_evidence(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    service = MigrationService()
    service.initialize(source, target, migration_id="migration-demo")

    with pytest.raises(AppProjectError) as exc_info:
        service.check(target, gate="ui")

    assert exc_info.value.code == "APP-MIGRATION-GATE"
    assert "覆盖矩阵中没有 UI 项。" in exc_info.value.detail["problems"]

    matrix_path = _state_path(target, "coverage-matrix.json")
    matrix = _load(matrix_path)
    matrix["items"] = [
        {
            "id": "PAGE-001",
            "kind": "page",
            "status": "已完成",
            "dynamic": False,
            "target": {"route": "/sales", "files": ["frontend/src/views/SalesView.vue"]},
            "acceptance": {"checks": ["layout"], "evidence": ["evidence/ui/PAGE-001.png"]},
            "remaining_issues": [],
            "unblock_conditions": [],
        }
    ]
    _write(matrix_path, matrix)
    blueprint_path = _state_path(target, "ui-blueprint.json")
    blueprint = _load(blueprint_path)
    blueprint["pages"] = [{"id": "PAGE-001", "route": "/sales", "modules": []}]
    _write(blueprint_path, blueprint)

    assert service.check(target, gate="ui")["passed"] is True


def test_data_and_release_gates_require_verified_contract_and_acceptance(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    service = MigrationService()
    service.initialize(source, target, migration_id="migration-demo")
    matrix_path = _state_path(target, "coverage-matrix.json")
    matrix = _load(matrix_path)
    matrix["items"] = [
        {
            "id": "MODULE-001",
            "kind": "module",
            "status": "已完成",
            "dynamic": True,
            "target": {"route": "/sales", "files": ["frontend/src/views/SalesView.vue"]},
            "acceptance": {"checks": ["layout", "data"], "evidence": ["tests/api/test_sales.py"]},
            "data_contract": {
                "product_key": "sales",
                "status": "candidate",
                "evidence": [],
                "implementation_status": "not_started",
            },
            "remaining_issues": ["真实数据层尚未实现"],
            "unblock_conditions": [],
        }
    ]
    _write(matrix_path, matrix)
    blueprint_path = _state_path(target, "ui-blueprint.json")
    blueprint = _load(blueprint_path)
    blueprint["pages"] = [{"id": "PAGE-001", "route": "/sales", "modules": ["MODULE-001"]}]
    _write(blueprint_path, blueprint)

    with pytest.raises(AppProjectError) as exc_info:
        service.verify(target, gate="data")
    assert "candidate" in " ".join(exc_info.value.detail["problems"])

    matrix["items"][0]["data_contract"] = {
        "product_key": "sales",
        "status": "verified",
        "evidence": ["docs/ops-app/data-contracts.json#sales"],
        "implementation_status": "verified",
    }
    _write(matrix_path, matrix)
    artifacts = _implementation_artifacts(target)
    _write_verified_contract(target, artifacts)

    assert service.verify(target, gate="data")["phase"] == "behavior_verification"
    assert service.verify(target, gate="release")["phase"] == "complete"


def test_blocked_dynamic_contract_requires_evidence_and_unblock_condition(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    service = MigrationService()
    service.initialize(source, target, migration_id="migration-demo")
    matrix_path = _state_path(target, "coverage-matrix.json")
    matrix = _load(matrix_path)
    matrix["items"] = [
        {
            "id": "MODULE-002",
            "kind": "module",
            "status": "blocked",
            "dynamic": True,
            "target": {"route": "/inventory", "files": []},
            "acceptance": {"checks": [], "evidence": []},
            "data_contract": {"product_key": "inventory", "status": "blocked", "evidence": []},
            "remaining_issues": ["正式能力暂不可用"],
            "unblock_conditions": [],
        }
    ]
    _write(matrix_path, matrix)

    with pytest.raises(AppProjectError) as exc_info:
        service.check(target, gate="data")

    problems = "\n".join(exc_info.value.detail["problems"])
    assert "缺少证据" in problems
    assert "缺少解除条件" in problems


def test_verified_contract_without_implementation_fails_data_gate(tmp_path: Path) -> None:
    """合同已验证但业务数据层未实现时不得通过数据门禁。"""
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    service = MigrationService()
    service.initialize(source, target, migration_id="migration-demo")
    matrix_path = _state_path(target, "coverage-matrix.json")
    matrix = _load(matrix_path)
    matrix["items"] = [
        _completed_page_item(),
        {
            "id": "DATA-001",
            "kind": "data",
            "status": "部分完成",
            "dynamic": True,
            "target": {"route": "/sales", "files": ["frontend/src/views/SalesView.vue"]},
            "acceptance": {"checks": ["data"], "evidence": ["contract-evidence"]},
            "data_contract": {
                "product_key": "sales",
                "status": "verified",
                "evidence": ["docs/ops-app/data-contracts.json#sales"],
                "implementation_status": "contract_verified_only",
            },
            "remaining_issues": ["业务 API 和前端消费尚未实现"],
            "unblock_conditions": ["完成数据层实现"],
        }
    ]
    _write(matrix_path, matrix)
    blueprint_path = _state_path(target, "ui-blueprint.json")
    blueprint = _load(blueprint_path)
    blueprint["pages"] = [{"id": "PAGE-001", "route": "/sales", "modules": ["MODULE-001"]}]
    _write(blueprint_path, blueprint)
    _write_verified_contract(
        target,
        _implementation_artifacts(target),
        implementation_status="contract_verified_only",
    )

    with pytest.raises(AppProjectError) as exc_info:
        service.verify(target, gate="data")

    assert "实现状态不是 verified" in "\n".join(exc_info.value.detail["problems"])
    status = service.status(target)
    assert status["delivery_ready"] is False
    assert status["next_required_gate"] == "data"


def test_frontend_placeholder_fails_delivery_validation(tmp_path: Path) -> None:
    """前端仍保留布局占位文字时不得通过数据门禁。"""
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    service = MigrationService()
    service.initialize(source, target, migration_id="migration-demo")
    matrix_path = _state_path(target, "coverage-matrix.json")
    matrix = _load(matrix_path)
    matrix["items"] = [
        _completed_page_item(),
        {
            "id": "DATA-001",
            "kind": "data",
            "status": "已完成",
            "dynamic": True,
            "target": {"route": "/sales", "files": ["frontend/src/views/SalesView.vue"]},
            "acceptance": {"checks": ["layout", "data"], "evidence": ["tests/api/test_sales.py"]},
            "data_contract": {
                "product_key": "sales",
                "status": "verified",
                "evidence": ["docs/ops-app/data-contracts.json#sales"],
                "implementation_status": "verified",
            },
            "remaining_issues": [],
            "unblock_conditions": [],
        }
    ]
    _write(matrix_path, matrix)
    blueprint_path = _state_path(target, "ui-blueprint.json")
    blueprint = _load(blueprint_path)
    blueprint["pages"] = [{"id": "PAGE-001", "route": "/sales", "modules": ["MODULE-001"]}]
    _write(blueprint_path, blueprint)
    artifacts = _implementation_artifacts(target, placeholder=True)
    _write_verified_contract(target, artifacts)

    with pytest.raises(AppProjectError) as exc_info:
        service.verify(target, gate="data")

    assert "前端仍包含未交付占位文本" in "\n".join(exc_info.value.detail["problems"])


def test_failed_verify_does_not_advance_phase(tmp_path: Path) -> None:
    """门禁失败时迁移阶段必须保持不变。"""
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    service = MigrationService()
    service.initialize(source, target, migration_id="migration-demo")

    with pytest.raises(AppProjectError):
        service.verify(target, gate="ui")

    assert service.status(target)["phase"] == "audit"


def test_schema_v1_migration_state_remains_readable(tmp_path: Path) -> None:
    """现有 Schema v1 状态应继续可读，并明确提示需要升级。"""
    source = _source_project(tmp_path)
    target = _target_project(tmp_path)
    service = MigrationService()
    service.initialize(source, target, migration_id="migration-demo")
    migration_root = target / ".opscli/migration/migration-demo"
    for name in ("migration.json", "coverage-matrix.json", "ui-blueprint.json"):
        path = migration_root / name
        payload = _load(path)
        payload["schema_version"] = 1
        _write(path, payload)

    status = service.status(target)

    assert status["schema_version"] == 1
    assert status["schema_upgrade_required"] is True
    assert status["delivery_ready"] is False
