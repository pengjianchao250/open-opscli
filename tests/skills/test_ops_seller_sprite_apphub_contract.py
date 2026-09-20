"""SellerSprite AppHub 机器合同与旧运行时隔离测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "opscli" / "app" / "services" / "data_contracts.py"
CONTRACT = (
    ROOT
    / "opscli"
    / "skills"
    / "templates"
    / "ops-seller-sprite"
    / "APPHUB_SCENARIO_CONTRACTS.json"
)


def _load_service():
    spec = importlib.util.spec_from_file_location("data_contracts_apphub_test", SERVICE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(**overrides):
    request = {
        "scope": "apphub",
        "contract_schema_version": "1.0",
        "scenario": "keyword-miner",
        "tool": "seller_sprite_run",
        "endpoint_family": "ordinary_jobs",
        "site": "US",
        "period": "30d",
        "page_size": 100,
        "params": {"keyword": "wireless charger"},
        "export_format": "json",
    }
    request.update(overrides)
    return request


def _seller_sprite_product_with_request(request: dict) -> dict:
    return {
        "product_key": "seller_sprite_keyword_miner",
        "source": "seller_sprite",
        "contract_status": "verified",
        "requires_real_data": True,
        "verification": {
            "attempted": True,
            "attempted_at": "2026-09-18T10:00:00+08:00",
            "method": "ops-seller-sprite",
            "outcome": "success",
            "row_count": 1,
            "shape_evidence": {
                "records_path": "$.data.result.rows[*]",
                "record_type": "array",
                "observed_fields": ["关键词", "月搜索量"],
            },
        },
        "technical_contract": {
            "scenario": "keyword-miner",
            "site": "US",
            "result_format": "json",
            "response_shape": {
                "records_path": "$.data.result.rows[*]",
                "columns_path": "$.data.result.columns",
                "record_type": "array",
            },
            "required_business_roles": ["keyword", "monthly_searches"],
            "fields": {
                "keyword": {
                    "source_field": "关键词",
                    "source_path": "$.data.result.rows[*][0]",
                    "result_field": "keyword",
                    "data_type": "string",
                },
                "monthly_searches": {
                    "source_field": "月搜索量",
                    "source_path": "$.data.result.rows[*][1]",
                    "result_field": "monthly_searches",
                    "data_type": "number",
                },
            },
            "projection_policy": {
                "validate_before_snapshot": True,
                "on_schema_mismatch": "degraded_preserve_snapshot",
            },
            "apphub_request": request,
        },
        "implementation_status": "not_started",
    }


def test_apphub_seller_sprite_catalog_is_valid():
    validator = _load_service()
    catalog = validator.load_apphub_seller_sprite_contracts(CONTRACT)

    assert validator.validate_apphub_seller_sprite_catalog(catalog) == []
    assert len(catalog["scenarios"]) == 16


def test_apphub_seller_sprite_request_requires_json_for_page_data():
    validator = _load_service()

    errors = validator.validate_apphub_seller_sprite_request(
        _request(export_format="xls"),
        require_json=True,
    )

    assert any("export_format=json" in error for error in errors)


def test_apphub_seller_sprite_rejects_asin_asins_and_endpoint_family_mixing():
    validator = _load_service()

    errors = validator.validate_apphub_seller_sprite_request(
        _request(
            scenario="association-traffic",
            endpoint_family="ordinary_jobs",
            params={"asin": "B000123456"},
        )
    )

    assert any("endpoint family" in error for error in errors)
    assert any("参数未在场景合同中登记" in error for error in errors)
    assert any("缺少必填参数" in error for error in errors)

    errors = validator.validate_apphub_seller_sprite_request(
        _request(
            scenario="competitor-lookup",
            params={"asins": "B000123456"},
        )
    )
    assert any("必须是字符串数组" in error for error in errors)


def test_apphub_seller_sprite_rejects_unknown_scenario_without_guessing():
    validator = _load_service()

    errors = validator.validate_apphub_seller_sprite_request(
        _request(scenario="unknown-scene")
    )

    assert any("场景未登记" in error for error in errors)


def test_apphub_seller_sprite_requires_online_scenario_discovery():
    validator = _load_service()

    errors = validator.validate_apphub_seller_sprite_request(
        _request(),
        available_scenarios={"product-research"},
    )

    assert any("线上 seller_sprite_scenarios 未暴露" in error for error in errors)


def test_apphub_seller_sprite_export_only_scene_cannot_be_page_json():
    validator = _load_service()

    errors = validator.validate_apphub_seller_sprite_request(
        _request(
            scenario="branddb",
            endpoint_family="browser_route_export",
            params={"text": "Acme"},
            export_format="json",
        ),
        require_json=True,
    )

    assert any("导出格式不在场景合同允许范围内" in error for error in errors)


def test_apphub_request_contract_is_opt_in_and_old_seller_sprite_contract_still_passes():
    validator = _load_service()
    product = _seller_sprite_product_with_request(_request())
    assert validator.validate_document(
        {"schema_version": "1.1", "products": [product]},
        mode="contract",
    ) == []

    product["technical_contract"].pop("apphub_request")
    assert validator.validate_document(
        {"schema_version": "1.1", "products": [product]},
        mode="contract",
    ) == []
