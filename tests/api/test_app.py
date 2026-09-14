"""产品化 HTTP API 的合同与 MCP 组合测试。"""

import asyncio
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
            "message": "请先完成 AppHub 账号授权",
        },
    }


def test_query_flow_returns_shared_service_result(monkeypatch):
    """API 应把请求转换为共享查询服务调用，而不是重新实现规划逻辑。"""
    from opscli.api import app as api_module
    from opscli.api.routers import query as query_router

    captured = {}

    monkeypatch.setenv("LOCAL_AUTH_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OPSCLI_LOCAL_AUTH_EMAIL", "user@example.com")

    def fake_flow(payload, *, user_email):
        captured["payload"] = payload
        captured["user_email"] = user_email
        return {"status": "planned", "result": {"rows": 1}}

    monkeypatch.setattr(query_router, "_query_flow", fake_flow)
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


def test_query_flow_accepts_apphub_viewer_headers(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api.routers import query as query_router

    captured = {}

    def fake_flow(payload, *, user_email):
        captured["user_email"] = user_email
        return {"status": "planned"}

    monkeypatch.setattr(query_router, "_query_flow", fake_flow)
    response = TestClient(create_api_app()).post(
        "/api/v1/query/flow",
        headers={
            "X-Ops-Token": "viewer-jwt",
            "X-User-Email": "Viewer@Example.com",
            "X-User-Id": "u-1",
        },
        json={"request": "本月销售额"},
    )

    assert response.status_code == 200
    assert captured["user_email"] == "viewer@example.com"


def test_query_flow_validates_apphub_session_cookie(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api.routers import query as query_router
    from opscli.auth import AuthClient

    captured = {}

    def fake_get_me(self, session_id=None, jwt=None):
        captured["session_id"] = session_id
        captured["jwt"] = jwt
        return {
            "data": {
                "username": "session@example.com",
                "inherit_email": "other@example.com",
                "id": 42,
            }
        }

    monkeypatch.setattr(AuthClient, "get_me", fake_get_me)
    monkeypatch.setattr(
        query_router,
        "_query_flow",
        lambda payload, *, user_email: {"user_email": user_email},
    )
    response = TestClient(create_api_app()).post(
        "/api/v1/query/flow",
        headers={"Authorization": "Bearer session-jwt"},
        cookies={"polarisUserToken": "session-cookie"},
        json={"request": "本月销售额"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["user_email"] == "session@example.com"
    assert captured == {"session_id": "session-cookie", "jwt": "session-jwt"}


def test_query_flow_rejects_unknown_fields(monkeypatch):
    """REST 合同必须拒绝 MCP/内部参数混入，避免接口随 Tool 演化漂移。"""
    from opscli.api import create_api_app

    monkeypatch.setenv("LOCAL_AUTH_FALLBACK_ENABLED", "true")
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


def test_auth_ensure_requires_authenticated_user(monkeypatch):
    """凭据预热接口必须建立在已验证 API Key 身份之上。"""
    from opscli.api import create_api_app

    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email",
        lambda: None,
    )

    response = TestClient(create_api_app()).post("/api/v1/auth/ensure")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_auth_ensure_returns_status_without_credentials(monkeypatch):
    """凭据预热接口只返回状态，不得暴露 Session 或 JWT。"""
    from opscli.api import app as api_module
    from opscli.mcp.ops_credentials import OpsCredentialBinding

    monkeypatch.setenv("LOCAL_AUTH_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OPSCLI_LOCAL_AUTH_EMAIL", "user@example.com")

    async def fake_ensure(*, provided_session, provided_jwt, require_jwt):
        assert provided_session is None
        assert provided_jwt is None
        assert require_jwt is True
        return OpsCredentialBinding(
            credential_scope="isolated-scope",
            user_email="user@example.com",
            session_id="secret-session",
            jwt="secret-jwt",
            refreshed=True,
        )

    monkeypatch.setattr(
        "opscli.mcp.ops_credentials.ensure_ops_credentials",
        fake_ensure,
    )

    response = TestClient(api_module.create_api_app()).post("/api/v1/auth/ensure")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"authenticated": True, "refreshed": True},
        "error": None,
    }
    assert "secret-session" not in response.text
    assert "secret-jwt" not in response.text


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
    from opscli.api.routers import keepa as keepa_router

    monkeypatch.setenv("LOCAL_AUTH_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OPSCLI_LOCAL_AUTH_EMAIL", "user@example.com")
    captured = {}

    async def fake_run(payload):
        captured["payload"] = payload
        return {
            "success": True,
            "data": {"job_id": "job-1", "scenario": payload.scenario},
            "error": None,
            "quota": {"remaining": 4},
        }

    monkeypatch.setattr(keepa_router, "_run_keepa_scenario", fake_run)
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


def test_keepa_run_returns_retryable_status_for_quota_error(monkeypatch):
    """Keepa 额度不足返回 429，并保留 Retry-After。"""
    from opscli.api import app as api_module
    from opscli.api.routers import keepa as keepa_router

    monkeypatch.setenv("LOCAL_AUTH_FALLBACK_ENABLED", "true")

    async def fake_run(_payload):
        return {
            "success": False,
            "data": None,
            "error": {
                "code": "KEEPA_QUOTA_INSUFFICIENT",
                "message": "Keepa 当前可用额度不足",
                "retry_after_seconds": 301,
            },
        }

    monkeypatch.setattr(keepa_router, "_run_keepa_scenario", fake_run)
    response = TestClient(api_module.create_api_app()).post(
        "/api/v1/keepa/run",
        json={"scenario": "product", "site": "US", "params": {"asin": "B0088PUEPK"}},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "301"
    assert response.json()["error"]["code"] == "KEEPA_QUOTA_INSUFFICIENT"


def test_keepa_api_mode_is_scoped_to_shared_tool_call(monkeypatch):
    """API mode must be visible only during the delegated Keepa tool call."""
    from opscli.api.routers import keepa as keepa_router
    from opscli.api.schemas.keepa import KeepaRunRequest
    from opscli.mcp.tools import keepa as keepa_module

    observed = {}

    async def fake_keepa_run(**kwargs):
        observed["during"] = keepa_module._KEEPA_API_MODE.get()
        observed["kwargs"] = kwargs
        return {"success": True, "data": {"request_source": "api"}, "error": None}

    monkeypatch.setattr(keepa_module, "keepa_run", fake_keepa_run)
    monkeypatch.setattr(keepa_router, "_trace_keepa_api", lambda message: None)
    monkeypatch.setattr(
        "opscli.mcp.instrumentation.quota_wrap",
        lambda fn, **kwargs: fn,
    )
    monkeypatch.setattr(
        "opscli.mcp.instrumentation.telemetry_wrap",
        lambda fn, **kwargs: fn,
    )

    payload = KeepaRunRequest(
        scenario="product-search",
        site="US",
        params={"keyword": "flashlight"},
    )
    result = asyncio.run(keepa_router._run_keepa_scenario(payload))

    assert result["data"]["request_source"] == "api"
    assert observed["during"] is True
    assert observed["kwargs"]["scenario"] == "product-search"
    assert keepa_module._KEEPA_API_MODE.get() is False


def test_keepa_run_rejects_path_traversal_job_id(monkeypatch):
    """Keepa 自定义 job_id 不能改变服务端导出目录。"""
    from opscli.api import create_api_app

    monkeypatch.setenv("LOCAL_AUTH_FALLBACK_ENABLED", "true")
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


def test_mcp_server_allows_local_prototype_cors_preflight():
    """本地 HTML 原型的跨端口 API 预检请求不应被 API Key 鉴权拦截。"""
    from opscli.mcp.server import _build_dual_endpoint_app

    app = _build_dual_endpoint_app(api_key="test-api-key")
    response = TestClient(app).options(
        "/api/v1/keepa/run",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_mcp_server_allows_seller_sprite_prototype_cors_preflight():
    """卖家精灵原型使用独立端口时也应通过共享 CORS 预检。"""
    from opscli.mcp.server import _build_dual_endpoint_app

    app = _build_dual_endpoint_app(api_key="test-api-key")
    response = TestClient(app).options(
        "/api/v1/seller-sprite/jobs",
        headers={
            "Origin": "http://127.0.0.1:4174",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4174"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_mcp_server_allows_private_lan_seller_sprite_cors_preflight():
    """SellerSprite prototype should allow private-LAN origins on port 4174."""
    from opscli.mcp.server import _build_dual_endpoint_app

    app = _build_dual_endpoint_app(api_key="test-api-key")
    response = TestClient(app).options(
        "/api/v1/seller-sprite/jobs",
        headers={
            "Origin": "http://10.6.53.56:4174",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://10.6.53.56:4174"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_mcp_server_allows_private_lan_prototype_cors_preflight():
    """局域网设备打开的 HTML 原型也应能跨端口调用本机 API。"""
    from opscli.mcp.server import _build_dual_endpoint_app

    app = _build_dual_endpoint_app(api_key="test-api-key")
    response = TestClient(app).options(
        "/api/v1/keepa/run",
        headers={
            "Origin": "http://10.6.53.56:4173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://10.6.53.56:4173"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_mcp_server_adds_cors_header_to_private_lan_auth_failure():
    """鉴权层返回 401 时也必须允许局域网页面读取错误详情。"""
    from opscli.mcp.server import _build_dual_endpoint_app

    app = _build_dual_endpoint_app(api_key="test-api-key")
    response = TestClient(app).post(
        "/api/v1/keepa/run",
        headers={
            "Origin": "http://10.6.53.56:4173",
            "Authorization": "Bearer invalid-api-key",
        },
        json={
            "scenario": "product-search",
            "site": "US",
            "params": {"keyword": "flashlight"},
        },
    )

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://10.6.53.56:4173"
    assert response.json()["error"]["code"] == "authentication_required"


def test_mcp_server_exposes_public_health_outside_mcp_api_key_boundary():
    """健康检查不应被 MCP API Key 鉴权边界拦截。"""
    from opscli.mcp.server import _build_dual_endpoint_app

    app = _build_dual_endpoint_app(api_key="test-api-key")
    with TestClient(app) as client:
        response = client.get("/health/live")

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
