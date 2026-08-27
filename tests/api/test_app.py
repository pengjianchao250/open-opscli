"""产品化 HTTP API 的合同与 MCP 组合测试。"""

from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def test_query_flow_requires_authenticated_user(monkeypatch):
    """没有已验证用户时，场景 API 必须返回 401。"""
    from opscli.api import app as api_module

    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email",
        lambda: None,
    )
    app = api_module.create_api_app()

    response = TestClient(app).post(
        "/api/v1/query/flow",
        json={"request": "查询本月销售额"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "data": None,
        "error": {
            "code": "authentication_required",
            "message": "请先完成 opscli 账号授权",
        },
    }


def test_query_flow_returns_shared_service_result(monkeypatch):
    """API 应把请求转换为共享查询服务调用，而不是重新实现规划逻辑。"""
    from opscli.api import app as api_module

    captured = {}

    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email",
        lambda: "user@example.com",
    )

    def fake_run(payload, *, user_email):
        captured["payload"] = payload
        captured["user_email"] = user_email
        return {"status": "planned", "result": {"rows": 1}}

    monkeypatch.setattr(api_module, "_run_query_flow", fake_run)
    app = api_module.create_api_app()

    response = TestClient(app).post(
        "/api/v1/query/flow",
        json={
            "request": "查询本月销售额",
            "requested_fields": ["sales"],
            "limit": 50,
            "order_by": [{"field": "sales", "desc": True}],
            "offset": 10,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"status": "planned", "result": {"rows": 1}},
        "error": None,
    }
    assert captured["user_email"] == "user@example.com"
    assert captured["payload"].request == "查询本月销售额"
    assert captured["payload"].order_by[0].desc is True


def test_query_flow_rejects_unknown_fields():
    """REST 合同必须拒绝 MCP/内部参数混入，避免接口随 Tool 演化漂移。"""
    from opscli.api import create_api_app

    response = TestClient(create_api_app()).post(
        "/api/v1/query/flow",
        json={"request": "查询本月销售额", "session_id": "should-not-be-accepted"},
    )

    assert response.status_code == 422


def test_keepa_run_requires_authenticated_user(monkeypatch):
    """Keepa REST 场景必须沿用已验证用户身份。"""
    from opscli.api import create_api_app

    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email",
        lambda: None,
    )
    response = TestClient(create_api_app()).post(
        "/api/v1/keepa/run",
        json={"scenario": "product-search", "params": {"keyword": "flashlight"}},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_keepa_scenarios_returns_public_definitions(monkeypatch):
    """网站可先读取 Keepa 场景注册表，避免硬编码场景参数。"""
    from opscli.api import create_api_app

    class DummyManager:
        def scenarios(self):
            return [{"scenario_id": "product-search", "required_params": ["term"]}]

    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)
    response = TestClient(create_api_app()).get("/api/v1/keepa/scenarios")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": [{"scenario_id": "product-search", "required_params": ["term"]}],
        "error": None,
    }


def test_keepa_run_reuses_governed_mcp_contract(monkeypatch):
    """Keepa REST 请求只做合同转换，执行结果沿用 MCP 的统一响应。"""
    from opscli.api import app as api_module

    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email",
        lambda: "user@example.com",
    )
    captured = {}

    async def fake_run(payload):
        captured["payload"] = payload
        return {
            "success": True,
            "data": {"job_id": "job-1", "scenario": payload.scenario},
            "error": None,
            "quota": {"remaining": 4},
        }

    monkeypatch.setattr(api_module, "_run_keepa_scenario", fake_run)
    response = TestClient(api_module.create_api_app()).post(
        "/api/v1/keepa/run",
        json={
            "scenario": "product-search",
            "site": "US",
            "params": {"keyword": "flashlight"},
            "export_format": "json",
            "wait": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["job_id"] == "job-1"
    assert response.json()["quota"]["remaining"] == 4
    assert captured["payload"].params == {"keyword": "flashlight"}
    assert captured["payload"].export_format == "json"
    assert captured["payload"].wait is True


def test_keepa_run_rejects_path_traversal_job_id():
    """Keepa 自定义 job_id 不能改变服务端导出目录。"""
    from opscli.api import create_api_app

    response = TestClient(create_api_app()).post(
        "/api/v1/keepa/run",
        json={
            "scenario": "product-search",
            "params": {"keyword": "flashlight"},
            "job_id": "../outside",
        },
    )

    assert response.status_code == 422


def test_wrap_mcp_app_keeps_mcp_routes_and_lifespan():
    """组合 FastAPI 外壳不能丢失 MCP 子应用路由或生命周期。"""
    from opscli.api import wrap_mcp_app

    state = {"started": False, "stopped": False}

    async def mcp_endpoint(_request):
        return JSONResponse({"mcp": True})

    @asynccontextmanager
    async def lifespan(_app):
        state["started"] = True
        yield
        state["stopped"] = True

    mcp_app = Starlette(
        routes=[Route("/mcp", mcp_endpoint, methods=["GET"])],
        lifespan=lifespan,
    )
    app = wrap_mcp_app(mcp_app)

    with TestClient(app) as client:
        response = client.get("/mcp")
        assert response.status_code == 200
        assert response.json() == {"mcp": True}
        assert state["started"] is True

    assert state["stopped"] is True


def test_mcp_server_exposes_api_route_behind_api_key():
    """真实 MCP 入口应同时提供 API，并沿用现有 API Key 鉴权。"""
    from opscli.mcp.server import _build_dual_endpoint_app

    app = _build_dual_endpoint_app(api_key="test-api-key")
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 401
        response = client.get(
            "/health/live",
            headers={"Authorization": "Bearer test-api-key"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_mcp_server_keeps_streamable_http_route_behind_api_key():
    """REST 外壳不能遮蔽真实 MCP Streamable HTTP 端点。"""
    from opscli.mcp.server import _build_dual_endpoint_app

    app = _build_dual_endpoint_app(api_key="test-api-key")
    with TestClient(app) as client:
        unauthorized = client.get("/mcp")
        authorized = client.get(
            "/mcp",
            headers={"Authorization": "Bearer test-api-key"},
        )

    assert unauthorized.status_code == 401
    # MCP 端点已被命中；GET 的协议错误说明路由和 FastMCP 生命周期均在工作。
    assert authorized.status_code == 406
    assert authorized.json()["error"]["code"] == -32600
