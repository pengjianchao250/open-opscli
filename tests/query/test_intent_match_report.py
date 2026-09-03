"""意图匹配上报回归：命中与未命中都上报，上报失败绝不影响匹配结果返回。"""
import httpx
import respx

from opscli.query.services.manager import QueryManager

_REPORT_URL = "https://ops.api.xenkee.com/api/v1/data-metrics/datasets/skill/intent-match-report"
_CATALOG = {
    "version": "v1.0.0", "intent_count": 1,
    "intents": [{
        "intent_code": "ads_overall", "intent_name": "广告总览",
        "table_id": 15, "dataset_alias": "ds_ads", "dataset_name": "广告费数据集",
        "keywords": ["广告费"], "priority": 100,
    }],
}


def _manager(monkeypatch) -> QueryManager:
    manager = QueryManager()
    monkeypatch.setattr(manager.client, "fetch_dataset_catalog", lambda: _CATALOG)
    monkeypatch.setattr(manager.client, "_get_auth", lambda system: ({}, {}))
    return manager


@respx.mock
def test_intent_match_reports_and_returns_record_id(monkeypatch):
    route = respx.post(_REPORT_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"match_record_id": 77}, "msg": "ok"})
    )
    result = _manager(monkeypatch).intent_match(query="看下广告费")
    assert result["match_record_id"] == 77
    body = route.calls.last.request.content
    assert b'"matched": true' in body or b'"matched":true' in body
    assert b"ads_overall" in body


@respx.mock
def test_unmatched_query_still_reports(monkeypatch):
    route = respx.post(_REPORT_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"match_record_id": 78}, "msg": "ok"})
    )
    result = _manager(monkeypatch).intent_match(query="毫无关联的天气话题")
    assert result["fallback_required"] is True
    assert result["match_record_id"] == 78
    assert b"no_intent_match" in route.calls.last.request.content


@respx.mock
def test_report_failure_is_silent(monkeypatch):
    respx.post(_REPORT_URL).mock(side_effect=httpx.ConnectError("down"))
    result = _manager(monkeypatch).intent_match(query="看下广告费")
    assert result["matched"] is True           # 匹配结果不受上报失败影响
    assert result["match_record_id"] is None
