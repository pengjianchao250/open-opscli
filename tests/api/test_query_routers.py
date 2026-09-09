"""query 全量 REST 端点的合同与路由测试。

覆盖三类断言：
1. 鉴权边界：所有 query 端点在无已验证账号时返回统一 401 信封
2. 合同转换：REST 请求 → QueryManager/规划器调用参数的映射（含 CLI 概念剔除）
3. 错误映射：domain 异常 → 语义化 HTTP 状态码 + 统一错误信封
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from opscli.api import create_api_app
from opscli.query.domain.exceptions import DatasetNotFoundError, InvalidPayloadError


@pytest.fixture()
def client(monkeypatch):
    """已认证账号下的 API 测试客户端（业务内核按测试需要打桩）。"""
    monkeypatch.setenv("LOCAL_AUTH_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OPSCLI_LOCAL_AUTH_EMAIL", "user@example.com")
    return TestClient(create_api_app())


# 全部 query 端点：method, path, 最小合法请求体（GET 为 None）
ALL_QUERY_ENDPOINTS = [
    ("POST", "/api/v1/query/plan", {"request": "本月销售额"}),
    ("POST", "/api/v1/query/flow", {"request": "本月销售额"}),
    ("GET", "/api/v1/query/preferences", None),
    ("GET", "/api/v1/query/metadata", None),
    ("GET", "/api/v1/query/catalog", None),
    ("POST", "/api/v1/query/intents/match", {"query": "销售额"}),
    ("POST", "/api/v1/query/run", {"payload": {"tableId": 1, "query": {}}}),
    ("POST", "/api/v1/query/build", {"dimensions": ["ds_x.dept_name"]}),
    ("POST", "/api/v1/query/simple", {"table_id": 1, "payload": {"dimensions": []}}),
    ("GET", "/api/v1/charts/uuid-1", None),
    ("POST", "/api/v1/charts/uuid-1/run", {"dry_run": False}),
    ("GET", "/api/v1/charts/uuid-1/doc", None),
]


@pytest.mark.parametrize(
    "method,path,body",
    ALL_QUERY_ENDPOINTS,
    ids=[item[1] for item in ALL_QUERY_ENDPOINTS],
)
def test_all_query_endpoints_require_authenticated_user(monkeypatch, method, path, body):
    """无已验证账号时，任何 query 端点都必须以统一 401 信封拒绝。"""
    unauthenticated = TestClient(create_api_app())

    response = unauthenticated.request(method, path, json=body)

    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "data": None,
        "error": {
            "code": "authentication_required",
            "message": "请先完成 AppHub 账号授权",
        },
    }


def test_query_plan_converts_contract_to_planner_call(client, monkeypatch):
    """plan 端点把 REST 合同转换为规划器调用。"""
    from opscli.api.routers import query as query_router

    captured = {}

    def fake_plan(payload, *, user_email):
        captured.update(payload.model_dump(), user_email=user_email)
        return {"status": "planned"}

    monkeypatch.setattr(query_router, "_query_plan", fake_plan)

    response = client.post(
        "/api/v1/query/plan",
        json={"request": "本月销售额", "requested_fields": ["sales"], "top_n": 3},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"status": "planned"},
        "error": None,
    }
    assert captured["user_email"] == "user@example.com"
    assert captured["requested_fields"] == ["sales"]
    assert captured["top_n"] == 3


def test_query_preferences_returns_manager_result(client, monkeypatch):
    """preferences 端点透传 QueryManager 结果。"""
    from opscli.api.routers import query as query_router

    monkeypatch.setattr(query_router, "_query_preferences", lambda: [{"table_id": 15}])

    response = client.get("/api/v1/query/preferences")

    assert response.status_code == 200
    assert response.json()["data"] == [{"table_id": 15}]


def test_query_metadata_without_all_fields_uses_dataset_lookup(client, monkeypatch):
    """metadata 默认走指定数据集查询，不触发全量元数据。"""
    from opscli.api.routers import query as query_router

    captured = {}

    def fake_metadata(**kwargs):
        captured.update(kwargs)
        return {"dataset": {"alias": "ds_x"}, "fields": []}

    monkeypatch.setattr(query_router, "_query_metadata", fake_metadata)

    response = client.get(
        "/api/v1/query/metadata",
        params={"dataset": "ds_x", "table_id": 15},
    )

    assert response.status_code == 200
    assert response.json()["data"]["dataset"]["alias"] == "ds_x"
    assert captured["dataset"] == "ds_x"
    assert captured["table_id"] == 15
    assert captured["all_fields"] is False
    assert captured["user_email"] == "user@example.com"


def test_query_run_rejects_unknown_fields(client):
    """REST 合同必须拒绝 MCP/内部参数混入，避免接口随 Tool 演化漂移。"""
    response = client.post(
        "/api/v1/query/run",
        json={"payload": {"tableId": 1, "query": {}}, "session_id": "no"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_query_chart_run_passes_dry_run(client, monkeypatch):
    """chart run 端点透传 dry_run 并返回合并结果。"""
    from opscli.api.routers import query as query_router

    captured = {}

    def fake_chart_run(chart_uuid, payload):
        captured["uuid"] = chart_uuid
        captured["dry_run"] = payload.dry_run
        return {"chart_uuid": chart_uuid, "merged": {"rows": []}}

    monkeypatch.setattr(query_router, "_chart_run", fake_chart_run)

    response = client.post("/api/v1/charts/uuid-9/run", json={"dry_run": True})

    assert response.status_code == 200
    assert response.json()["data"]["chart_uuid"] == "uuid-9"
    assert captured == {"uuid": "uuid-9", "dry_run": True}


def test_query_simple_inner_failure_keeps_cli_semantics(client, monkeypatch):
    """simple 执行遇内层失败时：外层 200 + success=false + error，与 CLI 输出语义一致。"""
    from opscli.api.routers import query as query_router

    inner_error = {"code": "VALIDATION_ERROR", "message": "limit 超上限", "details": None}

    def fake_simple(_payload):
        return {"payload": {"tableId": 1}}, inner_error

    monkeypatch.setattr(query_router, "_query_simple", fake_simple)

    response = client.post(
        "/api/v1/query/simple",
        json={"table_id": 1, "payload": {"dimensions": [{"field": "ds_x.dept_name"}]}, "run": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "data": {"payload": {"tableId": 1}},
        "error": inner_error,
    }


@pytest.mark.parametrize(
    "exc,status,code",
    [
        (InvalidPayloadError("payload 缺少 tableId"), 400, "INVALID_PAYLOAD"),
        (DatasetNotFoundError("数据集不存在"), 404, "DATASET_NOT_FOUND"),
        (RuntimeError("boom"), 502, "RuntimeError"),
    ],
    ids=["invalid-payload-400", "dataset-not-found-404", "unexpected-502"],
)
def test_query_endpoints_map_domain_exceptions(
    client, monkeypatch, exc, status, code
):
    """domain 异常映射为语义化状态码；未知异常不泄漏内部信息。"""
    from opscli.api.routers import query as query_router

    def raise_exc():
        raise exc

    monkeypatch.setattr(query_router, "_query_preferences", raise_exc)

    response = client.get("/api/v1/query/preferences")

    assert response.status_code == status
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == code


def test_unexpected_exception_hides_internal_details(client, monkeypatch):
    """非业务异常的 message 必须收敛为通用文案，避免泄漏内部细节。"""
    from opscli.api.routers import query as query_router

    def raise_exc():
        raise RuntimeError("/Users/secret/path/token.txt 泄漏")

    monkeypatch.setattr(query_router, "_query_preferences", raise_exc)

    response = client.get("/api/v1/query/preferences")

    assert response.status_code == 502
    assert "secret" not in response.text


# ── 合同转换：REST 请求 → QueryManager 调用参数 ────────────────────────


class FakeManager:
    """记录调用参数的 QueryManager 替身。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, {"args": args, "kwargs": kwargs}))
        return {"payload": {"tableId": 1}, "result": {"rows": [], "meta": {"rowCount": 0}}}

    def run_payload(self, payload, **kwargs):
        return self._record("run_payload", payload, **kwargs)

    def build(self, **kwargs):
        return self._record("build", **kwargs)

    def build_and_run(self, **kwargs):
        return self._record("build_and_run", **kwargs)

    def build_simple(self, **kwargs):
        return self._record("build_simple", **kwargs)

    def build_simple_and_run(self, **kwargs):
        return self._record("build_simple_and_run", **kwargs)


@pytest.fixture()
def fake_manager(monkeypatch):
    """把路由层的 QueryManager 构造替换为记录型替身。"""
    from opscli.api.routers import query as query_router

    manager = FakeManager()
    monkeypatch.setattr(query_router, "build_query_manager", lambda timeout=None: manager)
    return manager


def test_run_helper_forwards_payload_and_attribution(fake_manager):
    """run 合同：完整 payload 原样透传，归因三元组以独立参数传递。"""
    from opscli.api.routers import query as query_router
    from opscli.api.schemas.query import QueryRunRequest

    payload = QueryRunRequest(
        payload={"tableId": 15, "query": {"select": []}},
        intent_code="intent_x",
        selection_source="intent_route",
        match_record_id=7,
        timeout=60,
    )
    result = query_router._query_run(payload)

    name, call = fake_manager.calls[0]
    assert name == "run_payload"
    assert call["args"][0] == {"tableId": 15, "query": {"select": []}}
    assert call["kwargs"] == {
        "intent_code": "intent_x",
        "selection_source": "intent_route",
        "match_record_id": 7,
    }
    assert result == {"payload": {"tableId": 1}, "result": {"rows": [], "meta": {"rowCount": 0}}}


def test_build_helper_converts_structured_where_to_json(fake_manager):
    """build 合同：结构化 where 序列化为构造层 where_json 字符串。"""
    from opscli.api.routers import query as query_router
    from opscli.api.schemas.query import QueryBuildRequest

    request = QueryBuildRequest(
        dataset="ds_x",
        dimensions=["ds_x.dept_name"],
        metrics=["ds_x.price:SUM"],
        where=[{"field": "ds_x.platform_name", "operator": "in", "value": ["Amazon"]}],
        limit=100,
    )
    query_router._query_build(request)

    name, call = fake_manager.calls[0]
    assert name == "build"
    kwargs = call["kwargs"]
    assert json.loads(kwargs["where_json"]) == [
        {"field": "ds_x.platform_name", "operator": "in", "value": ["Amazon"]}
    ]
    assert kwargs["dataset_alias"] == "ds_x"
    assert kwargs["limit"] == 100
    # CLI 的 where_conditions 简写不进 REST 合同，构造层只收 where_json
    assert "where_conditions" not in kwargs


def test_build_helper_routes_run_flag_to_build_and_run(fake_manager):
    """run=true 走 build_and_run，run=false 只构造不执行。"""
    from opscli.api.routers import query as query_router
    from opscli.api.schemas.query import QueryBuildRequest

    base = {"dimensions": ["ds_x.dept_name"]}

    query_router._query_build(QueryBuildRequest(**base))
    assert fake_manager.calls[0][0] == "build"

    query_router._query_build(QueryBuildRequest(run=True, **base))
    assert fake_manager.calls[1][0] == "build_and_run"


def test_simple_helper_applies_currency_priority_and_validation(fake_manager):
    """simple 合同：显式 global_currency 优先于 payload 内币种，且默认开启字段校验。"""
    from opscli.api.routers import query as query_router
    from opscli.api.schemas.query import QuerySimpleRequest, SimpleQuerySpec

    request = QuerySimpleRequest(
        table_id=15,
        dataset="ds_x",
        payload=SimpleQuerySpec(
            dimensions=[{"field": "ds_x.dept_name"}],
            metrics=[{"field": "ds_x.price", "aggregation": "SUM"}],
            global_currency="CNY",
        ),
        global_currency="USD",
    )
    result, inner_error = query_router._query_simple(request)

    name, call = fake_manager.calls[0]
    assert name == "build_simple"
    kwargs = call["kwargs"]
    assert kwargs["global_currency"] == "USD"
    assert kwargs["validate_fields"] is True
    assert kwargs["table_id"] == 15
    assert inner_error is None
    assert result is not None


def test_simple_helper_run_mode_extracts_inner_error(fake_manager):
    """simple run=true 走 build_simple_and_run 并提取内层失败。"""
    from opscli.api.routers import query as query_router
    from opscli.api.schemas.query import QuerySimpleRequest, SimpleQuerySpec

    def failing_run(**kwargs):
        return {
            "payload": {"tableId": 1},
            "result": {
                "success": False,
                "data": [],
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求参数验证失败",
                    "details": {"errors": [{"field": "limit", "message": "超上限"}]},
                },
            },
        }

    fake_manager.build_simple_and_run = failing_run

    request = QuerySimpleRequest(
        table_id=1,
        payload=SimpleQuerySpec(dimensions=[{"field": "ds_x.dept_name"}]),
        run=True,
    )
    _result, inner_error = query_router._query_simple(request)

    assert inner_error is not None
    assert inner_error["code"] == "VALIDATION_ERROR"
    assert "limit" in inner_error["message"]
