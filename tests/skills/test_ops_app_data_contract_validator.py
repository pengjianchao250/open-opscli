"""AppHub 数据合同交付校验器测试。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "opscli"
    / "skills"
    / "templates"
    / "ops-app-data-builder"
    / "scripts"
    / "validate_data_contracts.py"
)


def _load_validator():
    """从 Skill 模板加载独立校验器模块。"""
    spec = importlib.util.spec_from_file_location(
        "apphub_data_contract_validator",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verified_ops_product(
    *,
    outcome: str = "success",
    implementation_status: str = "not_started",
    artifacts: dict[str, list[str]] | None = None,
) -> dict:
    """构造通过校验的 OPS 数据产品。"""
    product = {
        "product_key": "monthly_sales_trend",
        "source": "ops",
        "contract_status": "verified",
        "requires_real_data": True,
        "verification": {
            "attempted": True,
            "attempted_at": "2026-09-17T10:00:00+08:00",
            "method": "opscli query flow",
            "outcome": outcome,
            "row_count": 0 if outcome == "zero_rows" else 3,
        },
        "technical_contract": {
            "dataset_alias": "sales_dataset",
            "table_id": "table-sales",
            "required_business_roles": ["month", "orders"],
            "fields": {
                "month": {
                    "field_name": "month",
                    "role": "dimension",
                    "result_alias": "month",
                },
                "orders": {
                    "field_name": "orders",
                    "role": "metric",
                    "aggregation": "sum",
                    "result_alias": "orders",
                },
            },
        },
        "implementation_status": implementation_status,
    }
    if artifacts is not None:
        product["implementation_artifacts"] = artifacts
    return product


def _implementation_artifacts(project_root: Path, *, placeholder: bool = False) -> dict[str, list[str]]:
    """创建交付校验需要的项目实现工件。"""
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
            path = project_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            content = "等待真实数据合同\n" if placeholder and group == "frontend_consumer" else "ok\n"
            path.write_text(content, encoding="utf-8")
    return artifacts


def _document(product: dict, *, schema_version: str = "1.0") -> dict:
    """构造单产品数据合同文档。"""
    return {"schema_version": schema_version, "products": [product]}


def _verified_third_party_product(source: str) -> dict:
    """构造通过 1.1 校验的第三方数据产品。"""
    if source == "keepa":
        records_path = "$.data.data[*]"
        record_type = "object"
        observed_fields = ["title", "currentAmazonPrice", "currentSalesRank"]
        fields = {
            "title": {
                "source_field": "title",
                "source_path": "$.data.data[*].title",
                "result_field": "title",
                "data_type": "string",
            },
            "price": {
                "source_field": "currentAmazonPrice",
                "source_path": "$.data.data[*].currentAmazonPrice",
                "result_field": "price",
                "data_type": "number",
            },
            "bsr": {
                "source_field": "currentSalesRank",
                "source_path": "$.data.data[*].currentSalesRank",
                "result_field": "bsr",
                "data_type": "integer",
            },
        }
        response_shape = {
            "records_path": records_path,
            "record_type": record_type,
        }
        required_business_roles = ["title", "price", "bsr"]
    else:
        records_path = "$.data.result.rows[*]"
        record_type = "array"
        observed_fields = ["商品标题", "价格", "月销量"]
        fields = {
            "title": {
                "source_field": "商品标题",
                "source_path": "$.data.result.rows[*][0]",
                "result_field": "title",
                "data_type": "string",
            },
            "price": {
                "source_field": "价格",
                "source_path": "$.data.result.rows[*][1]",
                "result_field": "price",
                "data_type": "number",
            },
            "estimated_sales_30d": {
                "source_field": "月销量",
                "source_path": "$.data.result.rows[*][2]",
                "result_field": "estimated_sales_30d",
                "data_type": "integer",
            },
        }
        response_shape = {
            "records_path": records_path,
            "record_type": record_type,
            "columns_path": "$.data.result.columns",
        }
        required_business_roles = ["title", "price", "estimated_sales_30d"]

    return {
        "product_key": f"{source}_product",
        "source": source,
        "contract_status": "verified",
        "requires_real_data": True,
        "verification": {
            "attempted": True,
            "attempted_at": "2026-09-17T10:00:00+08:00",
            "method": f"ops-{source}",
            "outcome": "success",
            "row_count": 1,
            "shape_evidence": {
                "records_path": records_path,
                "record_type": record_type,
                "observed_fields": observed_fields,
            },
        },
        "technical_contract": {
            "scenario": "product",
            "site": "US",
            "result_format": "json",
            "response_shape": response_shape,
            "required_business_roles": required_business_roles,
            "fields": fields,
            "projection_policy": {
                "validate_before_snapshot": True,
                "on_schema_mismatch": "degraded_preserve_snapshot",
            },
        },
        "implementation_status": "not_started",
    }


def test_verified_ops_contract_passes_contract_validation() -> None:
    """完整 OPS 合同应通过合同门禁。"""
    validator = _load_validator()

    assert validator.validate_document(
        _document(_verified_ops_product()),
        mode="contract",
    ) == []


def test_zero_rows_is_still_a_verified_contract() -> None:
    """零行结果只影响业务数据，不否定技术合同。"""
    validator = _load_validator()

    assert validator.validate_document(
        _document(_verified_ops_product(outcome="zero_rows")),
        mode="contract",
    ) == []


def test_candidate_is_allowed_in_draft_but_rejected_for_delivery() -> None:
    """未验证状态只能存在于开发中间态。"""
    validator = _load_validator()
    product = {
        "product_key": "monthly_sales_trend",
        "source": "ops",
        "contract_status": "candidate",
        "verification": {"attempted": False, "outcome": "not_started"},
    }

    assert validator.validate_document(_document(product), mode="draft") == []
    errors = validator.validate_document(_document(product), mode="delivery")
    assert any("交付时真实数据合同必须为 verified" in error for error in errors)


def test_degraded_requires_real_failure_evidence() -> None:
    """临时降级必须证明已实际调用并记录失败。"""
    validator = _load_validator()
    product = {
        "product_key": "monthly_sales_trend",
        "source": "ops",
        "contract_status": "degraded",
        "verification": {
            "attempted": True,
            "attempted_at": "2026-09-17T10:00:00+08:00",
            "method": "opscli query flow",
            "outcome": "failed",
            "failure": {
                "code": "UPSTREAM_UNAVAILABLE",
                "retryable": True,
                "feedback_required": True,
                "feedback_uuid": "feedback-123",
            },
        },
    }

    assert validator.validate_document(_document(product), mode="contract") == []


def test_blocked_rejects_not_validated_and_service_error_reasons() -> None:
    """未尝试和临时服务错误不能伪装成结构性阻塞。"""
    validator = _load_validator()
    for code in ("not_validated", "service_error", "timeout"):
        product = {
            "product_key": "monthly_sales_trend",
            "source": "ops",
            "contract_status": "blocked",
            "verification": {"attempted": False, "outcome": "not_started"},
            "blockers": [
                {
                    "code": code,
                    "category": "runtime_prerequisite",
                    "message": "尚未完成在线验证",
                }
            ],
        }

        errors = validator.validate_document(_document(product), mode="contract")
        assert any("不能作为 blocked" in error for error in errors)


def test_structural_unsupported_blocker_passes_contract_validation() -> None:
    """正式能力确实不支持时允许保存结构性阻塞合同。"""
    validator = _load_validator()
    product = {
        "product_key": "unsupported_source",
        "source": "third_party",
        "contract_status": "blocked",
        "verification": {
            "attempted": False,
            "outcome": "unsupported_by_contract",
        },
        "blockers": [
            {
                "code": "SCENARIO_UNSUPPORTED",
                "category": "unsupported",
                "message": "正式场景合同不支持该业务能力",
            }
        ],
    }

    assert validator.validate_document(_document(product), mode="contract") == []
    delivery_errors = validator.validate_document(_document(product), mode="delivery")
    assert any("交付时真实数据合同必须为 verified" in error for error in delivery_errors)


def test_verified_ops_contract_requires_exact_field_mapping() -> None:
    """已验证 OPS 合同缺少字段映射时必须失败。"""
    validator = _load_validator()
    product = _verified_ops_product()
    product["technical_contract"].pop("fields")

    errors = validator.validate_document(_document(product), mode="contract")
    assert any("必须提供字段映射" in error for error in errors)


def test_verified_ops_contract_requires_every_business_role() -> None:
    """用户点名的业务角色缺少任一字段映射时必须失败。"""
    validator = _load_validator()
    product = _verified_ops_product()
    product["technical_contract"]["required_business_roles"].append("sales")

    errors = validator.validate_document(_document(product), mode="contract")
    assert any("缺少用户要求的业务角色字段映射" in error for error in errors)


def test_verified_keepa_contract_requires_schema_1_1() -> None:
    """已验证 Keepa 合同不能继续使用 1.0。"""
    validator = _load_validator()

    errors = validator.validate_document(
        _document(_verified_third_party_product("keepa")),
        mode="contract",
    )

    assert any("已验证第三方数据合同必须升级为 1.1" in error for error in errors)


def test_verified_keepa_contract_passes_schema_1_1() -> None:
    """Keepa 真实 data.data 对象结构与精确字段映射应通过。"""
    validator = _load_validator()

    assert validator.validate_document(
        _document(_verified_third_party_product("keepa"), schema_version="1.1"),
        mode="contract",
    ) == []


def test_verified_seller_sprite_columns_rows_contract_passes_schema_1_1() -> None:
    """SellerSprite columns + rows 数组结构与正式列名映射应通过。"""
    validator = _load_validator()

    assert validator.validate_document(
        _document(
            _verified_third_party_product("seller_sprite"),
            schema_version="1.1",
        ),
        mode="contract",
    ) == []


def test_third_party_field_must_exist_in_shape_evidence() -> None:
    """正式投影字段必须出现在脱敏结构证据中。"""
    validator = _load_validator()
    product = _verified_third_party_product("keepa")
    product["verification"]["shape_evidence"]["observed_fields"].remove("title")

    errors = validator.validate_document(
        _document(product, schema_version="1.1"),
        mode="contract",
    )

    assert any("字段未出现在 shape_evidence.observed_fields" in error for error in errors)


def test_third_party_contract_requires_projection_policy() -> None:
    """第三方数据保存快照前必须声明投影校验与漂移策略。"""
    validator = _load_validator()
    product = _verified_third_party_product("keepa")
    product["technical_contract"].pop("projection_policy")

    errors = validator.validate_document(
        _document(product, schema_version="1.1"),
        mode="contract",
    )

    assert any("第三方合同必须声明投影校验策略" in error for error in errors)


def test_seller_sprite_contract_requires_columns_path() -> None:
    """SellerSprite 数组记录必须声明 columns 路径。"""
    validator = _load_validator()
    product = _verified_third_party_product("seller_sprite")
    product["technical_contract"]["response_shape"].pop("columns_path")

    errors = validator.validate_document(
        _document(product, schema_version="1.1"),
        mode="contract",
    )

    assert any("必须提供 columns_path" in error for error in errors)


def test_third_party_contract_requires_records_path_and_business_roles() -> None:
    """第三方合同缺少记录路径或用户业务角色时必须失败。"""
    validator = _load_validator()
    product = _verified_third_party_product("keepa")
    product["technical_contract"]["response_shape"].pop("records_path")
    product["technical_contract"]["required_business_roles"].append("rating")

    errors = validator.validate_document(
        _document(product, schema_version="1.1"),
        mode="contract",
    )

    assert any("必须提供精确记录路径" in error for error in errors)
    assert any("缺少用户要求的业务角色字段映射" in error for error in errors)


def test_contract_rejects_credentials_and_result_rows() -> None:
    """验证凭证不得携带身份凭证或真实结果数据。"""
    validator = _load_validator()
    product = _verified_ops_product()
    product["verification"]["session_id"] = "sensitive-session"
    product["sample_rows"] = [{"orders": 10}]

    errors = validator.validate_document(_document(product), mode="contract")
    assert any("敏感身份字段" in error for error in errors)
    assert any("真实结果载荷" in error for error in errors)


def test_contract_verified_only_is_rejected_for_delivery(tmp_path: Path) -> None:
    """只完成上游合同验证不能通过最终交付门禁。"""
    validator = _load_validator()
    artifacts = _implementation_artifacts(tmp_path)
    product = _verified_ops_product(
        implementation_status="contract_verified_only",
        artifacts=artifacts,
    )

    errors = validator.validate_document(
        _document(product),
        mode="delivery",
        project_root=tmp_path,
    )

    assert any("数据层实现状态必须为 verified" in error for error in errors)


def test_complete_implementation_passes_delivery_validation(tmp_path: Path) -> None:
    """合同和项目工件全部完成时应通过最终交付门禁。"""
    validator = _load_validator()
    artifacts = _implementation_artifacts(tmp_path)
    product = _verified_ops_product(
        implementation_status="verified",
        artifacts=artifacts,
    )

    assert validator.validate_document(
        _document(product),
        mode="delivery",
        project_root=tmp_path,
    ) == []


def test_missing_implementation_artifact_fails_delivery(tmp_path: Path) -> None:
    """声明但不存在的实现工件必须阻止最终交付。"""
    validator = _load_validator()
    artifacts = _implementation_artifacts(tmp_path)
    (tmp_path / artifacts["backend_api"][0]).unlink()
    product = _verified_ops_product(
        implementation_status="verified",
        artifacts=artifacts,
    )

    errors = validator.validate_document(
        _document(product),
        mode="delivery",
        project_root=tmp_path,
    )

    assert any("项目工件不存在" in error for error in errors)


def test_frontend_placeholder_fails_delivery(tmp_path: Path) -> None:
    """前端仍显示待接入占位文字时必须阻止最终交付。"""
    validator = _load_validator()
    artifacts = _implementation_artifacts(tmp_path, placeholder=True)
    product = _verified_ops_product(
        implementation_status="verified",
        artifacts=artifacts,
    )

    errors = validator.validate_document(
        _document(product),
        mode="delivery",
        project_root=tmp_path,
    )

    assert any("前端仍包含未交付占位文本" in error for error in errors)


def test_validator_script_runs_directly_from_arbitrary_directory(tmp_path: Path) -> None:
    """Skill 校验脚本从项目外目录直接执行时也应加载校验内核。"""
    artifacts = _implementation_artifacts(tmp_path)
    product = _verified_ops_product(
        implementation_status="verified",
        artifacts=artifacts,
    )
    contract_file = tmp_path / "docs/ops-app/data-contracts.json"
    contract_file.parent.mkdir(parents=True, exist_ok=True)
    contract_file.write_text(
        json.dumps(_document(product), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(contract_file),
            "--mode",
            "delivery",
            "--project-root",
            str(tmp_path),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["delivery_ready"] is True
