"""用官方请求样本验证目录合同与实际 Provider 参数透传。"""

import asyncio
import json

import pytest
from jsonschema import Draft202012Validator

from opscli.xiyou.providers.xydc_audit import XydcAuditLogger
from opscli.xiyou.providers.xydc_openapi import XydcOpenApiError, XydcOpenApiProvider, list_operations
from tests.xiyou.test_xydc_openapi_provider import FakePool, _lease


# 来源：331502595e0、331594504e0、333379279e0、451262166e0、451506681e0。
LIST_REQUESTS = [
    ("asin_research_period", {"asin": "B09XS7JWHH", "country": "US", "page": 1,
                              "pageSize": 20, "period": "last7days"}),
    ("asin_research_monthly", {"asin": "B09XS7JWHH", "country": "US", "page": 1,
                               "pageSize": 20, "startMonth": "2025-06", "endMonth": "2025-06"}),
    ("search_terms_info", {"country": "US", "searchTerms": ["usb c cable"],
                           "sort": {"field": "weeklySearchVolume", "order": "desc"}}),
    ("search_terms_analysis_period", {"searchTerm": "usb c cable", "country": "US", "page": 1,
                                      "pageSize": 20, "period": "last7days",
                                      "sort": {"field": "trafficRatio", "order": "desc"}}),
    ("search_terms_analysis_monthly", {"searchTerm": "usb c cable", "country": "US", "page": 1,
                                       "pageSize": 20, "startMonth": "2025-06", "endMonth": "2025-06",
                                       "sort": {"field": "traffic", "order": "desc"}}),
]


@pytest.mark.parametrize("operation,payload", LIST_REQUESTS)
def test_official_list_payload_reaches_supplier_unchanged(tmp_path, respx_mock, operation, payload):
    """合法最近周期不再被错误要求日期；显式分页和排序不被本地改写。"""
    catalog = {item["operation"]: item for item in list_operations()}
    route = respx_mock.post("https://openapi.xydc.com" + catalog[operation]["endpoint"]).respond(200, json={"list": []})
    pool = FakePool(_lease(1, "test-secret"))
    provider = XydcOpenApiProvider(pool, audit_logger=XydcAuditLogger(tmp_path / "audit.jsonl"))
    result = asyncio.run(provider.call(operation, payload))
    assert result["success"] is True
    assert json.loads(route.calls.last.request.content) == payload
    assert route.call_count == 1


@pytest.mark.parametrize("operation,payload", LIST_REQUESTS)
def test_required_list_fields_are_checked_before_credentials(tmp_path, operation, payload):
    """分别去掉官方必填字段，保证在领取凭据前失败，不调用付费接口。"""
    class Pool(FakePool):
        def acquire(self, *args, **kwargs):
            pytest.fail("缺少必填字段不应领取凭据或发送网络请求")

    pool = Pool()
    provider = XydcOpenApiProvider(pool, audit_logger=XydcAuditLogger(tmp_path / "unused.jsonl"))
    for field in payload:
        incomplete = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(XydcOpenApiError, match=field) as caught:
            asyncio.run(provider.call(operation, incomplete))
        assert caught.value.code == "XYDC_OPENAPI_INVALID_PARAMS"
    assert pool.acquire_calls == []


def test_catalog_exposes_complete_examples_and_endpoint_specific_constraints():
    """每个公共接口可据目录构造请求，不同站点和排序枚举不混用。"""
    catalog = {item["operation"]: item for item in list_operations()}
    for spec in catalog.values():
        assert spec["documentation_url"].startswith("https://openapi-doc.xiyouzhaoci.com/")
        schema = spec["payload_schema"]
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(spec["example_payload"])
        assert schema["required"] == spec["required_fields"]
    assert "startDate" not in catalog["asin_research_period"]["payload_schema"]["properties"]
    assert catalog["asin_research_period"]["payload_schema"]["properties"]["period"]["enum"] == ["last7days"]
    assert catalog["asin_info"]["payload_schema"]["properties"]["entities"]["maxItems"] == 100
    assert catalog["asin_search_terms_rank_hourly"]["payload_schema"]["properties"]["country"]["enum"] == ["US", "UK", "DE"]
    assert "AU" not in catalog["asin_bsr_daily"]["payload_schema"]["properties"]["country"]["enum"]
    research_sort = catalog["asin_research_period"]["payload_schema"]["properties"]["sort"]["properties"]["field"]["enum"]
    analysis_sort = catalog["search_terms_analysis_period"]["payload_schema"]["properties"]["sort"]["properties"]["field"]["enum"]
    assert "trafficRatio" not in research_sort
    assert "trafficRatio" in analysis_sort
    assert "52" in " ".join(catalog["search_terms_aba_weekly"]["constraints"])
