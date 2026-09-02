import asyncio
from pathlib import Path
from types import SimpleNamespace

from opscli.keepa.domain.models import KeepaExportResult, KeepaScenarioResult
from opscli.mcp.tools import keepa as keepa_tools
from opscli.shared.collection_storage.result_cache import CachedCollectionResult


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    last_request = None
    init_kwargs = None

    def __init__(self, *args, **kwargs):
        self.__class__.init_kwargs = kwargs

    def scenarios(self):
        return [{"scenario_id": "product", "title": "商品详情"}]

    async def run(self, request):
        self.__class__.last_request = request
        result = KeepaScenarioResult.empty(
            job_id="job-1",
            scenario=request.scenario,
            site=request.site,
            root_dir=Path("/tmp/job-1"),
            params_path=Path("/tmp/job-1/params.json"),
            raw_path=Path("/tmp/job-1/raw.json"),
            result_path=Path("/tmp/job-1/result.json"),
        )
        result.row_count = 1
        result.export = KeepaExportResult(path="/tmp/job-1.xlsx", filename="job-1.xlsx")
        result.export.url = "https://example.com/job-1.xlsx"
        result.quota = {"estimated_tokens": 1, "after": {"tokensLeft": 1190, "tokensConsumed": 10}}
        result.warnings = [
            {
                "stage": "quota_precheck",
                "message": "Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。",
                "tokens_left": 1,
                "estimated_tokens": 10,
                "reserve_tokens": 200,
            }
        ]
        result.data = [
            {
                "asin": "B0088PUEPK",
                "title": "Test Product",
                "brand": "Test Brand",
                "dealMetadataStatus": "available",
                "dealTypesJoined": "LIMITED_TIME_DEAL",
                "statsBuyBoxLandedPrice": 125.99,
                "statsBuyBoxSavingBasis": 139.99,
                "statsBuyBoxSavingPercentage": 10,
                "stats": {"current": [1299] * 100},
                "offers": [{"offerId": f"offer-{index}"} for index in range(100)],
                "unknownField": "do not return",
            }
        ]
        return result

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "row_count": 1,
            "export": {
                "path": f"/tmp/{job_id}.xlsx",
                "url": f"https://example.com/{job_id}.xlsx",
                "filename": f"{job_id}.xlsx",
            },
            "quota": {"after": {"tokensLeft": 1190, "tokensConsumed": 10}},
        }


def test_keepa_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(keepa_tools.keepa_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "product"


def test_keepa_quota_status_returns_snapshot(monkeypatch):
    class FakeLimiter:
        def quota_snapshot(self, tool_name, identity):
            assert tool_name == "keepa_run"
            assert identity == "email:mcp-user@example.com"
            return {
                "service": "keepa",
                "limit": 5,
                "used": 1,
                "remaining": 4,
                "failures": 0,
                "reset_at": "2026-06-24T00:00:00+08:00",
            }

    monkeypatch.setattr(keepa_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr("opscli.mcp.tools.keepa.get_quota_limiter", lambda: FakeLimiter())

    result = _run(keepa_tools.keepa_quota_status())

    assert result["success"] is True
    assert result["data"]["service"] == "keepa"
    assert result["data"]["remaining"] == 4


def test_keepa_quota_status_returns_error_when_user_email_missing(monkeypatch):
    monkeypatch.setattr(keepa_tools, "_get_current_mcp_user_email", lambda: None)

    result = _run(keepa_tools.keepa_quota_status())

    assert result["success"] is False
    assert "邮箱" in result["error"]["message"]


def test_keepa_spec_reads_internal_reference():
    result = _run(keepa_tools.keepa_spec_must_read())

    assert result["success"] is True
    assert "opscli/skills/templates/ops-keepa" in result["data"]["spec"]
    source = Path(result["data"]["source"])
    assert source.parts[-3:] == ("templates", "ops-keepa", "SKILL_MCP.md")
    assert any(path.endswith(("ops-keepa\\references\\OFFICIAL.md", "ops-keepa/references/OFFICIAL.md")) for path in result["data"]["sources"])


def test_keepa_skill_templates_require_daily_quota_prompt():
    skill_dir = keepa_tools._keepa_skill_dir()
    expected_prompt = "今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at"

    for filename in ("SKILL.md", "SKILL_MCP.md"):
        content = (skill_dir / filename).read_text(encoding="utf-8")
        assert expected_prompt in content
        assert "job_status` 和 `export` 默认不重复提示额度" in content


def test_keepa_skill_templates_document_deal_request_boundaries():
    skill_dir = keepa_tools._keepa_skill_dir()

    for filename in ("SKILL.md", "SKILL_MCP.md"):
        content = (skill_dir / filename).read_text(encoding="utf-8")
        assert "selection.priceTypes" in content
        assert "20-100" in content


def test_keepa_run_accepts_params_json_string(monkeypatch):
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(
        keepa_tools.keepa_run(
            scenario="product",
            site="US",
            params='{"asin":"B0088PUEPK"}',
            force=True,
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert DummyManager.last_request.params == {"asin": "B0088PUEPK"}
    assert DummyManager.last_request.force is True
    assert DummyManager.last_request.export_format == "xls"
    assert "quota" not in result["data"]
    assert "params_path" not in result["data"]
    assert "raw_path" not in result["data"]
    assert "root_dir" not in result["data"]
    assert "result_path" not in result["data"]
    assert result["data"]["export"]["url"] == "https://example.com/job-1.xlsx"
    assert "path" not in result["data"]["export"]
    assert "tokens_left" not in str(result["data"])
    assert "data" not in result["data"]
    assert result["data"]["data_preview"] == [
        {
            "asin": "B0088PUEPK",
            "title": "Test Product",
            "brand": "Test Brand",
            "dealMetadataStatus": "available",
            "dealTypesJoined": "LIMITED_TIME_DEAL",
            "statsBuyBoxLandedPrice": 125.99,
            "statsBuyBoxSavingBasis": 139.99,
            "statsBuyBoxSavingPercentage": 10,
        }
    ]
    assert result["data"]["data_omitted"] == 0
    assert any(
        warning["stage"] == "mcp_response_compact"
        for warning in result["data"]["warnings"]
    )
    assert result["data"]["warnings"][0]["message"] == "Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。"


def test_keepa_run_returns_mysql_cache_before_auth(monkeypatch):
    class CacheRepository:
        def find_cached_result(self, **kwargs):
            assert kwargs["data_environment"] == "production"
            assert kwargs["cache_scope"] == "shared"
            return CachedCollectionResult(
                source_job_id="keepa-source-job",
                scenario="product",
                site="US",
                row_count=1,
                completed_at=None,
                persistence_completed_at="2026-09-01T01:00:00Z",
                result_metadata={
                    "row_count": 1,
                    "export": {
                        "filename": "keepa-source-job.xlsx",
                        "format": "xlsx",
                        "url": "https://files.example.com/keepa-source-job.xlsx",
                    },
                    "warnings": [],
                },
                datasets=({
                    "dataset_code": "main",
                    "records": [{"payload": {"asin": "B0088PUEPK", "title": "Cached"}}],
                },),
            )

    monkeypatch.setattr(
        keepa_tools,
        "_get_auth_pair",
        lambda *_args: (_ for _ in ()).throw(AssertionError("缓存命中不得读取认证")),
    )

    result = _run(
        keepa_tools._keepa_run_impl(
            scenario="product",
            site="US",
            params={"asin": "B0088PUEPK"},
            cache_repository=CacheRepository(),
            cache_environment="production",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "keepa-source-job"
    assert result["data"]["data_preview"] == [
        {"asin": "B0088PUEPK", "title": "Cached"}
    ]
    assert result["data"]["export"]["url"].startswith("https://")


def test_keepa_run_auto_logins_when_session_missing(monkeypatch):
    DummyManager.last_request = None
    DummyManager.init_kwargs = None
    auth_calls = []
    auth_pairs = iter([(None, None), ("sid-auto", "jwt-auto")])

    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)
    monkeypatch.setattr(keepa_tools, "_get_auth_pair", lambda system, session_id, jwt: next(auth_pairs))
    monkeypatch.setattr(keepa_tools, "_load_keepa_settings", lambda: SimpleNamespace(api_key=None))
    monkeypatch.setattr(
        keepa_tools,
        "_try_auto_mcp_login",
        lambda: _async_return(_record_and_return(auth_calls, {"success": True, "data": {"session_id": "sid-auto"}})),
    )

    result = _run(
        keepa_tools.keepa_run(
            scenario="product",
            site="US",
            params='{"asin":"B0088PUEPK"}',
        )
    )

    assert result["success"] is True
    assert auth_calls == [{"success": True, "data": {"session_id": "sid-auto"}}]
    assert DummyManager.init_kwargs == {"jwt": "jwt-auto", "session_id": "sid-auto"}
    assert DummyManager.last_request.params == {"asin": "B0088PUEPK"}


def test_keepa_run_returns_auth_error_when_auto_login_fails(monkeypatch):
    DummyManager.last_request = None
    DummyManager.init_kwargs = None

    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)
    monkeypatch.setattr(keepa_tools, "_get_auth_pair", lambda system, session_id, jwt: (None, None))
    monkeypatch.setattr(keepa_tools, "_load_keepa_settings", lambda: SimpleNamespace(api_key=None))
    monkeypatch.setattr(
        keepa_tools,
        "_try_auto_mcp_login",
        lambda: _async_return(
            {
                "success": False,
                "error": {
                    "message": "auth_mcp_login 仅适用于 HTTP/SSE 模式（需携带 X-MCP-API-Key）。",
                },
            }
        ),
    )

    result = _run(
        keepa_tools.keepa_run(
            scenario="product",
            site="US",
            params='{"asin":"B0088PUEPK"}',
        )
    )

    assert result["success"] is False
    assert "无 session_id" in result["error"]["message"]
    assert "auth_mcp_login" in result["error"]["message"]
    assert DummyManager.last_request is None


def test_keepa_run_skips_auto_login_when_env_api_key_present(monkeypatch):
    DummyManager.last_request = None
    DummyManager.init_kwargs = None
    auto_login_called = False

    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)
    monkeypatch.setattr(keepa_tools, "_get_auth_pair", lambda system, session_id, jwt: (None, None))
    monkeypatch.setattr(keepa_tools, "_load_keepa_settings", lambda: SimpleNamespace(api_key="env-key"))

    def _unexpected_auto_login():
        nonlocal auto_login_called
        auto_login_called = True
        return {"success": True, "data": {"session_id": "sid-auto"}}

    monkeypatch.setattr(keepa_tools, "_try_auto_mcp_login", _unexpected_auto_login)

    result = _run(
        keepa_tools.keepa_run(
            scenario="product",
            site="US",
            params='{"asin":"B0088PUEPK"}',
        )
    )

    assert result["success"] is True
    assert auto_login_called is False
    assert DummyManager.init_kwargs == {"jwt": None, "session_id": None}


def test_keepa_run_accepts_json_export_format(monkeypatch):
    DummyManager.last_request = None
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(
        keepa_tools.keepa_run(
            scenario="product",
            site="US",
            params='{"asin":"B0088PUEPK"}',
            export_format="json",
        )
    )

    assert result["success"] is True
    assert DummyManager.last_request.export_format == "json"


def test_keepa_run_api_mode_returns_formatted_data_without_export(monkeypatch):
    """REST mode returns complete formatted rows and disables file upload."""
    DummyManager.last_request = None
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)
    monkeypatch.setattr(keepa_tools, "_get_auth_pair", lambda system, session_id, jwt: (None, None))
    monkeypatch.setattr(
        keepa_tools,
        "_load_keepa_settings",
        lambda: SimpleNamespace(api_key="env-key"),
    )

    token = keepa_tools._KEEPA_API_MODE.set(True)
    try:
        result = _run(
            keepa_tools.keepa_run(
                scenario="product",
                site="US",
                params='{"asin":"B0088PUEPK"}',
            )
        )
    finally:
        keepa_tools._KEEPA_API_MODE.reset(token)

    assert result["success"] is True
    assert result["data"]["request_source"] == "api"
    assert result["data"]["response_mode"] == "formatted_data"
    assert result["data"]["data"][0]["asin"] == "B0088PUEPK"
    assert "data_preview" not in result["data"]
    assert "export" not in result["data"]
    assert DummyManager.last_request.upload_export is False


def test_keepa_job_status_hides_quota(monkeypatch):
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(keepa_tools.keepa_job_status("job-1"))

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert "quota" not in result["data"]
    assert "tokensLeft" not in str(result["data"])
    assert result["data"]["export"]["url"] == "https://example.com/job-1.xlsx"
    assert "path" not in result["data"]["export"]


def test_keepa_export_returns_export_info(monkeypatch):
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(keepa_tools.keepa_export("job-1"))

    assert result["success"] is True
    assert result["data"]["url"] == "https://example.com/job-1.xlsx"
    assert "path" not in result["data"]


def test_keepa_job_status_warns_when_export_url_missing(monkeypatch):
    class NoUrlManager(DummyManager):
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "row_count": 1,
                "export": {
                    "path": f"/tmp/{job_id}.xlsx",
                    "filename": f"{job_id}.xlsx",
                },
            }

    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", NoUrlManager)

    result = _run(keepa_tools.keepa_job_status("job-2"))

    assert result["success"] is True
    assert result["data"]["export"]["filename"] == "job-2.xlsx"
    assert "path" not in result["data"]["export"]
    assert not result["data"]["export"].get("url")
    assert any(item["stage"] == "export_url_unavailable" for item in result["data"]["warnings"])


def test_keepa_export_fails_when_download_url_missing(monkeypatch):
    class NoUrlManager(DummyManager):
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "export": {
                    "path": f"/tmp/{job_id}.xlsx",
                    "filename": f"{job_id}.xlsx",
                },
            }

    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", NoUrlManager)

    result = _run(keepa_tools.keepa_export("job-2"))

    assert result["success"] is False
    assert "没有可下载地址" in result["error"]["message"]


def test_keepa_history_reads_persisted_rows_by_job_id(monkeypatch):
    class HistoryRepository:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def query_history_page(self, **kwargs):
            assert kwargs["source_system"] == "keepa"
            assert kwargs["source_job_id"] == "job-1"
            return {
                "total": 1,
                "limit": 20,
                "offset": 0,
                "has_more": False,
                "runs": [{
                    "job_id": "job-1",
                    "scenario": "product",
                    "site": "US",
                    "request_params": {
                        "normalized_params": {"asin": "B0088PUEPK"},
                        "account": {"api_key": "secret"},
                    },
                    "datasets": [
                        {
                            "dataset_code": "main",
                            "row_count": 1,
                            "records": [
                                {"row_number": 1, "payload": {"asin": "B0088PUEPK"}}
                            ],
                            "records_omitted": 0,
                        }
                    ],
                }],
            }

    monkeypatch.setattr(
        "opscli.shared.collection_storage.config.load_storage_settings",
        lambda runtime_id: SimpleNamespace(enabled=True, mysql=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "opscli.shared.collection_storage.mysql_repository.MySqlCollectionRepository",
        HistoryRepository,
    )

    result = _run(keepa_tools.keepa_history(job_id="job-1"))

    assert result["success"] is True
    assert result["data"]["run_count"] == 1
    assert result["data"]["total"] == 1
    assert result["data"]["found"] is True
    assert result["data"]["has_more"] is False
    assert result["data"]["runs"][0]["request_params"] == {
        "asin": "B0088PUEPK"
    }
    assert "secret" not in str(result)


def test_keepa_history_requires_a_history_selector():
    result = _run(keepa_tools.keepa_history())

    assert result["success"] is False
    assert "至少提供" in result["error"]["message"]


def test_keepa_history_normalizes_site_and_scenario_param_aliases(monkeypatch):
    captured = {}

    class HistoryRepository:
        def __init__(self, **kwargs):
            pass

        def query_history_page(self, **kwargs):
            captured.update(kwargs)
            return {
                "total": 0,
                "limit": 10,
                "offset": 20,
                "has_more": False,
                "runs": [],
            }

    monkeypatch.setattr(
        "opscli.shared.collection_storage.config.load_storage_settings",
        lambda runtime_id: SimpleNamespace(enabled=True, mysql=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "opscli.shared.collection_storage.mysql_repository.MySqlCollectionRepository",
        HistoryRepository,
    )

    result = _run(
        keepa_tools.keepa_history(
            scenario=" PRODUCT-SEARCH ",
            site=" us ",
            params={"keyword": "flashlight"},
            limit=10,
            offset=20,
            include_records=False,
        )
    )

    assert result["success"] is True
    assert result["data"]["found"] is False
    assert captured["scenario"] == "product-search"
    assert captured["site"] == "US"
    assert captured["site_aliases"] == ("1",)
    assert captured["request_params"]["term"] == "flashlight"
    assert captured["original_request_params"] == {"keyword": "flashlight"}
    assert captured["include_records"] is False


def test_keepa_history_site_aliases_treat_gb_and_uk_as_one_domain():
    assert set(keepa_tools._history_site_aliases("UK")) == {"GB", "2"}
    assert set(keepa_tools._history_site_aliases("GB")) == {"UK", "2"}


def _record_and_return(storage, value):
    storage.append(value)
    return value


async def _async_return(value):
    return value
