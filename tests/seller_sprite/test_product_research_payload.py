"""选产品参数以本场景页面请求为基准，不继承其他选品场景的字段语义。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from opscli.seller_sprite.api.scenarios import get_scenario
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError
from opscli.seller_sprite.collection_storage_integration import build_seller_sprite_cache_identity
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.shared.collection_storage.result_cache import build_cache_key


@pytest.fixture
def page_request():
    # 来源：用户 2026-09-28 提供的 product-research POST 请求，仅保留业务请求体。
    path = Path(__file__).parents[1] / "fixtures/seller_sprite/product-research/page-request-20260928.json"
    return json.loads(path.read_text(encoding="utf-8"))


def build(params):
    return get_scenario("product-research").build_payload(
        params=params, site="US", period="30d", page_size=60,
    )


def test_product_research_preserves_page_request(page_request):
    payload = build(page_request)

    assert {key: payload.get(key) for key in page_request} == page_request


def test_product_research_keyword_alias_uses_page_field():
    payload = build({"keyword": "LOFT", "matchType": 0})

    assert payload["keywords"] == "LOFT"
    assert "keyword" not in payload
    assert payload["selectType"] == "2"
    assert "matchType" not in payload


def test_product_research_page_keyword_takes_precedence():
    payload = build({"keywords": "LOFT", "keyword": "bed"})

    assert payload["keywords"] == "LOFT"
    assert "keyword" not in payload


def test_product_research_page_sort_takes_precedence():
    payload = build({
        "order": {"field": "price", "desc": False},
        "orderField": "total_units", "orderDesc": True,
    })

    assert payload["order"] == {"field": "price", "desc": False}


@pytest.mark.parametrize("keywords", [["LOFT"], {"value": "LOFT"}, 123])
def test_product_research_rejects_non_page_keyword_type(keywords):
    with pytest.raises(SellerSpriteConfigError, match="keywords 必须为字符串"):
        build({"keywords": keywords})


def test_product_research_keeps_legacy_sort_aliases():
    assert build({"orderField": "price", "orderDesc": False})["order"] == {
        "field": "price", "desc": False,
    }


def test_product_research_does_not_mutate_caller_params(page_request):
    original = json.loads(json.dumps(page_request))
    build(page_request)
    assert page_request == original


@pytest.mark.parametrize(("legacy", "page_value"), [(0, "2"), (1, "3"), (2, "4")])
def test_product_research_legacy_match_mode_maps_to_page_radio(legacy, page_value):
    payload = build({"keywords": "loft bed", "matchType": legacy})
    assert payload["selectType"] == page_value
    assert "matchType" not in payload


@pytest.mark.parametrize("select_type", ["2", "3", "4"])
def test_product_research_page_match_mode_takes_precedence(select_type):
    assert build({"selectType": select_type, "matchType": 0})["selectType"] == select_type


@pytest.mark.parametrize(("params", "symbol_flag"), [
    ({}, False),
    ({"symbolFlag": True}, True),
    ({"symbolFlag": "false"}, False),
    ({"loadVariations": True}, False),
    ({"loadVariations": False}, True),
    ({"symbolFlag": False, "loadVariations": False}, False),
])
def test_product_research_variant_flag_uses_post_semantics(params, symbol_flag):
    payload = build(params)
    assert payload["symbolFlag"] is symbol_flag
    assert "loadVariations" not in payload
    query = parse_qs(urlparse(get_scenario("product-research").build_referer(payload)).query)
    assert query["symbolFlag"] == [str(not symbol_flag).lower()]
    assert query["filterSub"] == ["false"]
    assert query["order[desc]"] == ["true"]


@pytest.mark.parametrize("period", ["30d", "2026-08"])
def test_product_research_growth_comparison_is_independent_of_data_month(period):
    payload = get_scenario("product-research").build_payload(
        params={}, site="US", period=period, page_size=60,
    )
    assert payload["salesGrowthType"] == "30d"
    assert payload["monthName"] == (
        "bsr_sales_nearly" if period == "30d" else "bsr_sales_monthly_202608"
    )


def test_product_research_growth_sort_follows_page_comparison_selection():
    payload = build({"salesGrowthType": "yoy", "order": {"field": "total_units_growth", "desc": True}})
    assert payload["salesGrowthType"] == "yoy"
    assert payload["order"]["field"] == "total_units_growth_yoy"


@pytest.mark.parametrize(("video", "expected"), [(True, "Y"), (False, "N"), ("Y", "Y"), ("N", "N")])
def test_product_research_video_matches_page_post_and_url(video, expected):
    payload = build({"video": video})
    assert payload["video"] == expected
    query = parse_qs(urlparse(get_scenario("product-research").build_referer(payload)).query)
    assert query["video"] == [str(expected == "Y").lower()]


@pytest.mark.parametrize("params", [
    {"selectType": 1}, {"selectType": "all"}, {"matchType": 3},
    {"salesGrowthType": "90d"}, {"symbolFlag": "all"},
])
def test_product_research_rejects_unsupported_control_values(params):
    with pytest.raises(SellerSpriteConfigError):
        build(params)


@pytest.mark.parametrize("scenario", ["product-research", "keyword-miner"])
def test_only_product_research_stops_reusing_pre_fix_results(scenario):
    request = SellerSpriteScenarioRequest(
        scenario=scenario, site="US", period="30d", params={"keyword": "LOFT"}, export_format="json",
    )
    old_key = build_cache_key("seller_sprite", {
        "scenario": scenario, "site": "US", "period": "30d", "params": request.params,
        "page_size": 100, "export_format": "json", "mode": "browser-route", "page_prepare": None,
    })
    key, _ = build_seller_sprite_cache_identity(request, account_route=None, requested_account_key=None)
    assert (key != old_key) is (scenario == "product-research")


def test_product_research_browser_route_sends_page_post_body(monkeypatch, tmp_path, page_request):
    """检查真正传给 route.continue_ 的 JSON，避免仅在入参层断言自洽。"""
    from opscli.seller_sprite.accounts import SellerSpriteAccount
    from opscli.seller_sprite.browser_route import worker as worker_module
    from opscli.seller_sprite.config import SellerSpriteSettings

    calls = []
    endpoint = "/v3/api/product-research"
    payload = build(page_request)

    class RouteProbe:
        request = SimpleNamespace(
            url=f"https://www.sellersprite.com{endpoint}",
            headers={"content-type": "application/json"},
            post_data=json.dumps(page_request),
        )

        async def continue_(self, **kwargs):
            calls.append(kwargs)

    class PageProbe:
        async def route(self, pattern, handler):
            self.handler = handler

        async def unroute(self, pattern, handler):
            assert handler is self.handler

        def is_closed(self):
            return False

    page = PageProbe()

    async def trigger(*args, **kwargs):
        await page.handler(RouteProbe())
        return SimpleNamespace(status=200), "page_response"

    async def parse(*args, **kwargs):
        return {"code": "OK", "data": {"items": []}}

    monkeypatch.setattr(worker_module, "_trigger_request", trigger)
    monkeypatch.setattr(worker_module, "_parse_response", parse)
    worker = worker_module.SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=SellerSpriteAccount(name="test", username="test@example.com", password="test"),
    )
    request = worker_module.BrowserRouteRequest(
        scenario="product-research", method="POST", endpoint=endpoint, payload=payload,
        referer=get_scenario("product-research").build_referer(payload), account=worker.account,
        root_dir=tmp_path,
    )
    asyncio.run(worker._execute_route_fetch(
        page=page, method="POST", endpoint=endpoint, payload=payload,
        root_dir=tmp_path, section="main", request=request,
    ))
    assert len(calls) == 1
    assert calls[0]["url"] == f"https://www.sellersprite.com{endpoint}"
    assert json.loads(calls[0]["post_data"]) == {**page_request, "smallAndLight": "N"}
