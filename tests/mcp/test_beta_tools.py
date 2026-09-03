"""Canopy beta MCP 工具合同与多账号故障转移测试。"""

import asyncio
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from opscli.beta.canopy.services import api_manager as canopy_api_manager
from opscli.api_credentials.models import ApiCredentialLease
from opscli.mcp.server import mcp
from opscli.mcp.tools import beta as beta_tools


def _run(coro):
    return asyncio.run(coro)


class DisabledUploadClient:
    """测试用上传客户端，默认关闭真实文件上传。"""

    enabled = False

    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def disable_real_file_upload_client(monkeypatch):
    monkeypatch.setattr(canopy_api_manager, "FileUploadClient", DisabledUploadClient)


@pytest.fixture(autouse=True)
def allow_all_tools_without_local_credentials(monkeypatch):
    async def allow_all():
        return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)


@pytest.fixture(autouse=True)
def use_fake_canopy_credential_pool(monkeypatch):
    class FakePool:
        successes = []
        failures = []

        def acquire(self, provider, *, exclude_account_ids=None):
            assert provider == "canopy"
            return ApiCredentialLease(
                account_id=9,
                provider="canopy",
                account_name="test-pool",
                secret="pool-canopy-key",
                secret_version=2,
            )

        def report_success(self, lease, *, runtime=None):
            self.__class__.successes.append((lease, runtime))

        def report_failure(self, lease, **kwargs):
            self.__class__.failures.append((lease, kwargs))

    monkeypatch.setattr("opscli.api_credentials.pool.ApiCredentialPool", FakePool)


def test_mcp_exposes_beta_tools():
    async def scenario():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return [tool.name for tool in tools]

    names = _run(scenario())

    assert "beta_spec_must_read" in names
    assert "beta_canopy_scenarios" in names
    assert "beta_canopy_run" in names
    assert "beta_canopy_job_status" in names
    assert "beta_canopy_export" in names
    assert "beta_canopy_api_key_set" not in names
    assert "beta_canopy_api_key_status" not in names
    assert "beta_canopy_api_key_clear" not in names


def test_beta_spec_reads_internal_reference():
    result = _run(beta_tools.beta_spec_must_read())

    assert result["success"] is True
    assert "Canopy 测试调研服务 MCP 说明" in result["data"]["spec"]
    assert "OPSCLI_MCP_CANOPY_ENABLED" in result["data"]["spec"]
    source = result["data"]["source"].replace("\\", "/")
    assert source.endswith("opscli/mcp/references/canopy/SKILL_MCP.md")
    assert result["data"]["sources"] == [result["data"]["source"]]


def test_beta_canopy_scenarios_returns_all_openapi_endpoints():
    result = _run(beta_tools.beta_canopy_scenarios())

    assert result["success"] is True
    scenarios = {item["scenario_id"]: item for item in result["data"]}
    assert len(scenarios) == 17
    assert {"product", "search", "product-reviews"}.issubset(scenarios)
    assert scenarios["search"]["optional_params"] == [
        "page",
        "limit",
        "categoryId",
        "minPrice",
        "maxPrice",
        "conditions",
        "sort",
    ]


class RecordingMcp:
    def __init__(self):
        self.registered = []

    def tool(self, **kwargs):
        def decorator(fn):
            self.registered.append((fn.__name__, kwargs))
            return fn

        return decorator


def test_beta_registers_canopy_tools_by_default(monkeypatch):
    monkeypatch.delenv(beta_tools.ENV_CANOPY_ENABLED, raising=False)
    mcp = RecordingMcp()

    beta_tools.register(mcp)

    assert [name for name, _ in mcp.registered] == [fn.__name__ for fn in beta_tools._ALL_TOOLS]


@pytest.mark.parametrize("value", ["0", "false", "no", "off", " FALSE "])
def test_beta_does_not_register_canopy_tools_when_disabled(monkeypatch, value):
    monkeypatch.setenv(beta_tools.ENV_CANOPY_ENABLED, value)
    mcp = RecordingMcp()

    beta_tools.register(mcp)

    assert mcp.registered == []


def test_beta_canopy_job_status_hides_local_paths(monkeypatch):
    class FakeManager:
        def __init__(self, *args, **kwargs):
            pass

        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "root_dir": "D:/tmp/private",
                "params_path": "D:/tmp/private/params.json",
                "raw_path": "D:/tmp/private/raw.json",
                "result_path": "D:/tmp/private/result.json",
                "response": {"api_key": "secret"},
                "request": {
                    "url": "https://rest.canopyapi.co/api/amazon/product",
                    "api_key_placeholder_used": True,
                },
                "export": {
                    "path": "D:/tmp/private/canopy-job-1.xlsx",
                    "filename": "canopy-job-1.xlsx",
                    "url": None,
                },
            }

    monkeypatch.setattr(beta_tools, "CanopyApiManager", FakeManager)

    result = _run(beta_tools.beta_canopy_job_status("job-1"))

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert "root_dir" not in result["data"]
    assert "params_path" not in result["data"]
    assert "raw_path" not in result["data"]
    assert "result_path" not in result["data"]
    assert "response" not in result["data"]
    assert "api_key_placeholder_used" not in str(result["data"])
    assert "api_key_placeholder_used" not in result["data"]["request"]
    assert "path" not in result["data"]["export"]
    assert result["data"]["export"].get("url") is None
    assert "file://" not in str(result["data"])
    assert result["data"]["warnings"] == [
        {
            "stage": "export_url_unavailable",
            "message": "当前任务导出文件没有可下载地址，请稍后重试或联系管理员检查上传链路。",
        }
    ]


def test_beta_canopy_export_fails_without_remote_upload_url(monkeypatch):
    class FakeManager:
        def __init__(self, *args, **kwargs):
            pass

        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "export": {
                    "path": "D:/tmp/private/canopy-job-1.xlsx",
                    "filename": "canopy-job-1.xlsx",
                    "url": None,
                },
            }

    monkeypatch.setattr(beta_tools, "CanopyApiManager", FakeManager)

    result = _run(beta_tools.beta_canopy_export("job-1"))

    assert result["success"] is False
    assert result["error"]["code"] == "ValueError"
    assert "没有可下载地址" in result["error"]["message"]


def test_beta_canopy_export_returns_json_fallback_after_upload_failure(monkeypatch):
    class FakeManager:
        def __init__(self, *args, **kwargs):
            pass

        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "data": [{"asin": "B0B3JBVDYP", "title": "Fallback Product"}],
                "export": {
                    "path": "D:/tmp/private/canopy-job-1.xlsx",
                    "filename": "canopy-job-1.xlsx",
                    "url": None,
                },
                "warnings": [{"stage": "file_upload", "message": "upload failed"}],
            }

    monkeypatch.setattr(beta_tools, "CanopyApiManager", FakeManager)

    result = _run(beta_tools.beta_canopy_export("job-1"))

    assert result["success"] is True
    assert result["data"]["url"] is None
    assert result["data"]["json_data"] == [
        {"asin": "B0B3JBVDYP", "title": "Fallback Product"}
    ]
    assert "path" not in result["data"]


def test_beta_canopy_export_returns_remote_url_only(monkeypatch):
    class FakeManager:
        def __init__(self, *args, **kwargs):
            pass

        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "export": {
                    "path": "D:/tmp/private/canopy-job-1.xlsx",
                    "filename": "canopy-job-1.xlsx",
                    "url": "https://ops.example.com/canopy-job-1.xlsx",
                },
            }

    monkeypatch.setattr(beta_tools, "CanopyApiManager", FakeManager)

    result = _run(beta_tools.beta_canopy_export("job-1"))

    assert result["success"] is True
    assert result["data"]["filename"] == "canopy-job-1.xlsx"
    assert result["data"]["url"] == "https://ops.example.com/canopy-job-1.xlsx"
    assert "path" not in result["data"]


def test_beta_canopy_run_calls_canopy_with_domain_placeholder_key_and_xls_export(monkeypatch, tmp_path: Path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("API-KEY")
        captured["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={"success": True, "data": {"product": {"asin": "B0B3JBVDYP", "title": "Test Product"}}})

    _patch_async_client(monkeypatch, handler)

    result = _run(
        beta_tools.beta_canopy_run(
            scenario="product",
            domain="us",
            params={"asin": "B0B3JBVDYP"},
            output_dir=str(tmp_path),
            job_id="beta-product-regression",
        )
    )

    assert result["success"] is True
    data = result["data"]
    assert data["job_id"] == "beta-product-regression"
    assert data["row_count"] == 1
    assert data["request"]["url"] == "https://rest.canopyapi.co/api/amazon/product"
    assert "api_key_placeholder_used" not in str(data)
    assert "api_key_placeholder_used" not in data["request"]
    assert data["request"]["export_format"] == "xls"
    assert data["export"]["filename"] == "beta-product-regression.xlsx"
    assert "path" not in data["export"]
    assert data["export"].get("url") is None
    assert "root_dir" not in data
    assert "params_path" not in data
    assert "raw_path" not in data
    assert "result_path" not in data
    assert "response" not in data
    assert "file://" not in str(data)
    assert data["warnings"] == [
        {
            "stage": "export_url_unavailable",
            "message": "当前任务导出文件没有可下载地址，请稍后重试或联系管理员检查上传链路。",
        }
    ]
    assert data["data_preview"][0]["asin"] == "B0B3JBVDYP"
    assert "asin=B0B3JBVDYP" in captured["url"]
    assert "domain=US" in captured["url"]
    assert "country=" not in captured["url"]
    assert captured["api_key"] == "pool-canopy-key"
    assert captured["content_type"] == "application/json"


def test_beta_canopy_run_product_reviews_uses_pool_account(monkeypatch, tmp_path: Path):
    """评论场景应使用统一凭据池账号并落到正确接口。"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("API-KEY")
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "amazonProduct": {
                        "asin": "B0B3JBVDYP",
                        "title": "Test Product",
                        "reviewsPaginated": {
                            "reviews": [
                                {
                                    "id": "R1",
                                    "rating": "ONE_STAR",
                                    "title": "Battery issue",
                                    "body": "Battery drains quickly.",
                                    "isVerifiedPurchase": True,
                                    "profileName": "Alice",
                                },
                                {
                                    "id": "R2",
                                    "rating": "ONE_STAR",
                                    "title": "Stopped working",
                                    "body": "Stopped working after a week.",
                                    "isVerifiedPurchase": True,
                                    "profileName": "Bob",
                                },
                            ],
                            "pageInfo": {"currentPage": 1, "totalPages": 1, "totalResults": 2},
                        },
                    }
                },
            },
        )

    _patch_async_client(monkeypatch, handler)

    result = _run(
        beta_tools.beta_canopy_run(
            scenario="product-reviews",
            domain="US",
            params={
                "asin": "B0B3JBVDYP",
                "rating": "ONE_STAR",
                "onlyVerifiedReviews": True,
            },
            export_format="xls",
            output_dir=str(tmp_path),
            job_id="beta-review-local-debug",
        )
    )

    assert result["success"] is True
    data = result["data"]
    assert data["scenario"] == "product-reviews"
    assert data["row_count"] == 2
    assert data["request"]["url"] == "https://rest.canopyapi.co/api/amazon/product/reviews"
    assert data["request"]["export_format"] == "xls"
    assert data["export"]["filename"] == "beta-review-local-debug.xlsx"
    assert data["export"].get("url") is None
    assert "file://" not in str(data)
    assert data["data_preview"][0]["reviewTitle"] == "Battery issue"
    assert "asin=B0B3JBVDYP" in captured["url"]
    assert "domain=US" in captured["url"]
    assert "rating=ONE_STAR" in captured["url"]
    assert "onlyVerifiedReviews=true" in captured["url"]
    assert captured["api_key"] == "pool-canopy-key"
    assert "local-debug-key" not in str(data)


def test_beta_canopy_run_product_reviews_defaults_page_and_longer_timeout(monkeypatch, tmp_path: Path):
    """评论场景默认限制第一页，避免默认拉取过多评论导致请求超时。"""
    captured = {}

    async def fake_run(self, request):
        captured["params"] = request.params
        captured["timeout_seconds"] = request.timeout_seconds
        from opscli.beta.canopy.domain.models import CanopyScenarioResult

        return CanopyScenarioResult.empty(
            job_id="beta-review-default-page",
            scenario=request.scenario,
            domain=request.domain,
            root_dir=tmp_path / "beta-review-default-page",
            params_path=tmp_path / "beta-review-default-page" / "params.json",
            raw_path=tmp_path / "beta-review-default-page" / "raw.json",
            result_path=tmp_path / "beta-review-default-page" / "result.json",
        )

    monkeypatch.setattr(beta_tools.CanopyApiManager, "run", fake_run)

    result = _run(
        beta_tools.beta_canopy_run(
            scenario="product-reviews",
            domain="US",
            params={"asin": "B0CDQFTWQ2"},
            output_dir=str(tmp_path),
            job_id="beta-review-default-page",
        )
    )

    assert result["success"] is True
    assert captured["params"]["page"] == 1
    assert captured["timeout_seconds"] == 60


def test_beta_canopy_run_product_reviews_infers_alias_params(monkeypatch, tmp_path: Path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "amazonProduct": {
                        "asin": "B0B3JBVDYP",
                        "reviewsPaginated": {
                            "reviews": [
                                {
                                    "id": "R1",
                                    "rating": "ONE_STAR",
                                    "title": "Battery issue",
                                    "body": "Battery drains quickly.",
                                    "isVerifiedPurchase": True,
                                }
                            ],
                            "pageInfo": {"currentPage": 1, "totalPages": 1, "totalResults": 1},
                        },
                    }
                },
            },
        )

    _patch_async_client(monkeypatch, handler)

    result = _run(
        beta_tools.beta_canopy_run(
            scenario="product-reviews",
            domain="US",
            params={"asin": "B0B3JBVDYP", "query": "查差评和已验证购买"},
            output_dir=str(tmp_path),
            job_id="beta-review-alias-infer",
        )
    )

    assert result["success"] is True
    assert "asin=B0B3JBVDYP" in captured["url"]
    assert "domain=US" in captured["url"]
    assert "rating=ONE_STAR" in captured["url"]
    assert "onlyVerifiedReviews=true" in captured["url"]


def test_beta_canopy_run_product_reviews_keeps_structured_params(monkeypatch, tmp_path: Path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"success": True, "data": {"reviews": []}})

    _patch_async_client(monkeypatch, handler)

    result = _run(
        beta_tools.beta_canopy_run(
            scenario="product-reviews",
            domain="US",
            params={
                "asin": "B0B3JBVDYP",
                "query": "查差评和已验证购买",
                "rating": "FIVE_STAR",
                "onlyVerifiedReviews": False,
            },
            output_dir=str(tmp_path),
            job_id="beta-review-alias-structured-wins",
        )
    )

    assert result["success"] is True
    assert "rating=FIVE_STAR" in captured["url"]
    assert "onlyVerifiedReviews=false" in captured["url"]
    assert "rating=ONE_STAR" not in captured["url"]
    assert "onlyVerifiedReviews=true" not in captured["url"]


def test_beta_canopy_run_alias_params_only_apply_to_reviews(monkeypatch, tmp_path: Path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"success": True, "data": {"product": {"asin": "B0B3JBVDYP"}}})

    _patch_async_client(monkeypatch, handler)

    result = _run(
        beta_tools.beta_canopy_run(
            scenario="product",
            domain="US",
            params={"asin": "B0B3JBVDYP", "query": "查差评和已验证购买"},
            output_dir=str(tmp_path),
            job_id="beta-product-alias-noop",
        )
    )

    assert result["success"] is True
    assert "asin=B0B3JBVDYP" in captured["url"]
    assert "domain=US" in captured["url"]
    assert "rating=" not in captured["url"]
    assert "onlyVerifiedReviews=" not in captured["url"]


def test_beta_canopy_run_accepts_json_params_and_blank_export_format(monkeypatch, tmp_path: Path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("API-KEY")
        return httpx.Response(200, json={"success": True, "data": {"products": [{"asin": "B001"}]}})

    _patch_async_client(monkeypatch, handler)

    result = _run(
        beta_tools.beta_canopy_run(
            scenario="search",
            domain="US",
            params='{"searchTerm":"coffee grinder","page":1,"limit":20}',
            export_format="",
            output_dir=str(tmp_path),
            job_id="beta-search-regression",
        )
    )

    assert result["success"] is True
    assert "searchTerm=coffee+grinder" in captured["url"]
    assert "domain=US" in captured["url"]
    assert captured["api_key"] == "pool-canopy-key"
    assert "api_key_placeholder_used" not in str(result["data"])
    assert "api_key_placeholder_used" not in result["data"]["request"]
    assert result["data"]["request"]["export_format"] == "xls"
    assert result["data"]["export"].get("url") is None
    assert "file://" not in str(result["data"])


def test_beta_canopy_run_ignores_env_and_uses_credential_pool(monkeypatch, tmp_path: Path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["api_key"] = request.headers.get("API-KEY")
        return httpx.Response(200, json={"success": True, "data": {"categories": [{"categoryId": "1", "name": "Root"}]}})

    _patch_async_client(monkeypatch, handler)
    monkeypatch.setenv("OPSCLI_BETA_CANOPY_API_KEY", "env-key")
    monkeypatch.setenv("CANOPY_API_KEY", "legacy-env-key")

    result = _run(
        beta_tools.beta_canopy_run(
            "categories",
            domain="US",
            output_dir=str(tmp_path),
            job_id="beta-categories-regression",
        )
    )

    assert result["success"] is True
    assert captured["api_key"] == "pool-canopy-key"


def test_beta_canopy_run_fails_over_after_unauthorized_account(monkeypatch, tmp_path: Path):
    attempted_keys = []

    class FailoverPool:
        def acquire(self, provider, *, exclude_account_ids=None):
            excluded = exclude_account_ids or set()
            account_id = 1 if 1 not in excluded else 2
            return ApiCredentialLease(
                account_id=account_id,
                provider=provider,
                account_name=f"account-{account_id}",
                secret=f"canopy-key-{account_id}",
                secret_version=1,
            )

        def report_success(self, lease, *, runtime=None):
            pass

        def report_failure(self, lease, **kwargs):
            pass

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.headers.get("API-KEY")
        attempted_keys.append(api_key)
        if api_key == "canopy-key-1":
            return httpx.Response(401, json={"message": "invalid key"})
        return httpx.Response(200, json={"success": True, "data": {"categories": []}})

    monkeypatch.setattr("opscli.api_credentials.pool.ApiCredentialPool", FailoverPool)
    _patch_async_client(monkeypatch, handler)

    result = _run(
        beta_tools.beta_canopy_run(
            "categories",
            domain="US",
            output_dir=str(tmp_path),
            job_id="beta-canopy-failover",
        )
    )

    assert result["success"] is True
    assert attempted_keys == ["canopy-key-1", "canopy-key-2"]


def test_beta_canopy_run_rejects_unknown_scenario():
    result = _run(beta_tools.beta_canopy_run("unknown", params={}))

    assert result["success"] is False
    assert result["error"]["code"] == "ValueError"
    assert "不支持的 beta Canopy 场景" in result["error"]["message"]


def test_beta_canopy_run_validates_required_params():
    result = _run(beta_tools.beta_canopy_run("product", params={}))

    assert result["success"] is False
    assert result["error"]["code"] == "ValueError"
    assert "至少需要提供以下参数之一" in result["error"]["message"]


def test_beta_canopy_run_validates_domain():
    result = _run(beta_tools.beta_canopy_run("categories", domain="CN"))

    assert result["success"] is False
    assert result["error"]["code"] == "ValueError"
    assert "不支持的 Canopy domain" in result["error"]["message"]


def test_beta_canopy_run_rejects_non_xls_export_format_before_http(monkeypatch):
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"success": True})

    _patch_async_client(monkeypatch, handler)

    for value in ["xlsx", "csv", "json"]:
        result = _run(beta_tools.beta_canopy_run("categories", domain="US", export_format=value))
        assert result["success"] is False
        assert "不支持的导出格式" in result["error"]["message"]

    assert called is False


def test_request_canopy_api_requires_json_object(monkeypatch):
    _patch_async_client(monkeypatch, lambda request: httpx.Response(200, json=[{"asin": "B0B3JBVDYP"}]))

    try:
        _run(
            beta_tools._request_canopy_api(
                path="/api/amazon/product",
                params={"asin": "B0B3JBVDYP", "domain": "US"},
                api_key="test-key",
                timeout_seconds=3,
            )
        )
    except ValueError as exc:
        assert "JSON 对象" in str(exc)
    else:
        raise AssertionError("非 JSON 对象响应应抛出 ValueError")


def _patch_async_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(canopy_api_manager.httpx, "AsyncClient", fake_client)
