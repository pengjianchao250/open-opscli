"""执行归因请求头回归：三个可选参数必须以 Header 形式到达服务端，不污染 payload。"""
import json

import httpx
import respx

from opscli.query.services.manager import QueryManager

_QUERY_URL = "https://ops.api.xenkee.com/api/v1/data-metrics/cli-query"


@respx.mock
def test_run_sends_attribution_headers(tmp_path, monkeypatch):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps({"tableId": 1, "query": {"from": {"alias": "ds_x"}}}), encoding="utf-8")

    route = respx.post(_QUERY_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"result": {"success": True}}, "msg": "ok"})
    )
    manager = QueryManager()
    monkeypatch.setattr(manager.client, "_get_auth", lambda system: ({}, {}))

    manager.run(
        payload_path=str(payload_file),
        intent_code="ads_overall",
        selection_source="intent_route",
        match_record_id=77,
    )

    request = route.calls.last.request
    assert request.headers["X-Intent-Code"] == "ads_overall"
    assert request.headers["X-Selection-Source"] == "intent_route"
    assert request.headers["X-Match-Record-Id"] == "77"
    assert b"intent" not in request.content.lower()   # payload 不被污染


@respx.mock
def test_run_without_attribution_sends_no_headers(tmp_path, monkeypatch):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps({"tableId": 1, "query": {"from": {"alias": "ds_x"}}}), encoding="utf-8")

    route = respx.post(_QUERY_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"result": {"success": True}}, "msg": "ok"})
    )
    manager = QueryManager()
    monkeypatch.setattr(manager.client, "_get_auth", lambda system: ({}, {}))
    manager.run(payload_path=str(payload_file))

    request = route.calls.last.request
    assert "X-Intent-Code" not in request.headers
    assert "X-Match-Record-Id" not in request.headers
