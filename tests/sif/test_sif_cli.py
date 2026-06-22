import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from typer.testing import CliRunner

from opscli.sif.domain.exceptions import SifLoginRequiredError
from opscli.sif.cli import FEATURE_ALIASES, FEATURE_DEFINITIONS, app
from opscli.sif.config import DEFAULT_OUTPUT_DIR, DEFAULT_FEATURE_OUTPUT_DIRS


runner = CliRunner()


def _export(filename: str, path: str):
    return SimpleNamespace(filename=filename, path=path, to_dict=lambda: {"filename": filename, "path": path})


def _dummy_sales_result():
    export_chart = _export(
        "boughtListingHistory_B01NBNDC1T_1780000000000.xlsx",
        "output/sif-manual/job-1/boughtListingHistory_B01NBNDC1T_1780000000000.xlsx",
    )
    export_search = _export(
        "boughtByAsin_B01NBNDC1T_1780000000000.xlsx",
        "output/sif-manual/job-1/boughtByAsin_B01NBNDC1T_1780000000000.xlsx",
    )
    return SimpleNamespace(
        job_id="job-1",
        feature="查销量",
        provider="sif",
        asin="B01NBNDC1T",
        asins=[],
        site="US",
        root_dir="output/sif-manual/job-1",
        result_path="output/sif-manual/job-1/result.json",
        exports={"listing_history_xlsx": export_chart, "bought_by_asin_xlsx": export_search},
        to_dict=lambda: {"job_id": "job-1", "feature": "查销量", "provider": "sif", "asin": "B01NBNDC1T"},
    )


def _dummy_generic_result(feature="查流量"):
    export = _export(
        "listingScoreChart_B01NBNDC1T_1780000000000.xlsx",
        "output/sif-manual/job-traffic/listingScoreChart_B01NBNDC1T_1780000000000.xlsx",
    )
    return SimpleNamespace(
        job_id="job-traffic",
        feature=feature,
        provider="sif",
        asin="B01NBNDC1T" if feature == "查流量" else None,
        asins=[] if feature == "查流量" else ["B075WPKK5P", "B07KVV8RFF"],
        site="US",
        root_dir="output/sif-manual/job-traffic",
        result_path="output/sif-manual/job-traffic/result.json",
        exports={"traffic_structure_xlsx": export},
        to_dict=lambda: {"job_id": "job-traffic", "feature": feature, "provider": "sif", "site": "US"},
    )


def _dummy_keyword_result():
    export = _export(
        "产品时光机_balloon_pump_1780000000000.xlsx",
        "output/sif-manual/job-product/产品时光机_balloon_pump_1780000000000.xlsx",
    )
    return SimpleNamespace(
        job_id="job-product",
        feature="产品时光机",
        provider="sif",
        asin=None,
        asins=[],
        keyword="balloon pump",
        site="US",
        root_dir="output/sif-manual/job-product",
        result_path="output/sif-manual/job-product/result.json",
        exports={"product_time_machine_xlsx": export},
        to_dict=lambda: {"job_id": "job-product", "feature": "产品时光机", "provider": "sif", "keyword": "balloon pump"},
    )


def test_sif_run_outputs_human_summary(monkeypatch):
    class DummyProvider:
        def run(self, request, *, default_output_dir):
            assert request.feature == "查销量"
            assert request.provider == "sif"
            assert request.asin == "B01NBNDC1T"
            assert default_output_dir == DEFAULT_OUTPUT_DIR
            return _dummy_sales_result()

    monkeypatch.setattr("opscli.sif.cli.SifSalesProvider", lambda: DummyProvider())

    result = runner.invoke(app, ["run", "查销量", "--asin", "B01NBNDC1T", "--site", "US"])

    assert result.exit_code == 0
    assert "Sif 执行成功" in result.stdout
    assert "B01NBNDC1T" in result.stdout
    assert "不同变体销量" in result.stdout
    assert "同组变体销量" in result.stdout
    assert "任务目录" not in result.stdout
    assert "结构化结果" not in result.stdout
    assert "下载图表" not in result.stdout
    assert "下载搜索结果" not in result.stdout
    assert "boughtListingHistory_B01NBNDC1T_1780000000000.xlsx" in result.stdout
    assert "boughtByAsin_B01NBNDC1T_1780000000000.xlsx" in result.stdout


def test_sif_run_json_outputs_structured_payload(monkeypatch):
    class DummyProvider:
        def run(self, request, *, default_output_dir):
            return _dummy_sales_result()

    monkeypatch.setattr("opscli.sif.cli.SifSalesProvider", lambda: DummyProvider())

    result = runner.invoke(app, ["run", "查销量", "--asin", "B01NBNDC1T", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "sif run"
    assert payload["data"]["provider"] == "sif"


def test_sif_run_passes_sales_sections(monkeypatch):
    class DummyProvider:
        def run(self, request, *, default_output_dir):
            assert request.feature == "查销量"
            assert request.sections == ["同组变体销量"]
            return _dummy_sales_result()

    monkeypatch.setattr("opscli.sif.cli.SifSalesProvider", lambda: DummyProvider())

    result = runner.invoke(app, ["run", "查销量", "--asin", "B01NBNDC1T", "--sections", "同组变体销量", "--json"])

    assert result.exit_code == 0


def test_sif_run_routes_traffic_feature(monkeypatch):
    traffic_feature = FEATURE_ALIASES["traffic"]

    class DummyProvider:
        def run(self, request, *, default_output_dir):
            assert request.feature == traffic_feature
            assert request.asin == "B01NBNDC1T"
            assert request.site == "US"
            assert request.time_piece_value == "7"
            assert request.sections == []
            assert default_output_dir == DEFAULT_FEATURE_OUTPUT_DIRS["traffic"]
            return _dummy_generic_result(traffic_feature)

    monkeypatch.setitem(FEATURE_DEFINITIONS["查流量"], "provider", lambda: DummyProvider())

    result = runner.invoke(app, ["run", "traffic", "--asin", "B01NBNDC1T", "--site", "US", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["feature"] == traffic_feature


def test_sif_run_routes_ranking_feature_with_granularity(monkeypatch):
    ranking_feature = FEATURE_ALIASES["ranking"]

    class DummyProvider:
        def run(self, request, *, default_output_dir):
            assert request.feature == ranking_feature
            assert request.asin == "B0BMW2985V"
            assert request.site == "US"
            assert request.granularity == "month"
            assert default_output_dir == DEFAULT_FEATURE_OUTPUT_DIRS["ranking"]
            return _dummy_generic_result(ranking_feature)

    monkeypatch.setitem(FEATURE_DEFINITIONS["查排名"], "provider", lambda: DummyProvider())

    result = runner.invoke(app, ["run", "ranking", "--asin", "B0BMW2985V", "--granularity", "month", "--json"])

    assert result.exit_code == 0


def test_sif_run_routes_product_time_machine_without_asin(monkeypatch):
    product_feature = FEATURE_ALIASES["产品时光机"]

    class DummyProvider:
        def run(self, request, *, default_output_dir):
            assert request.feature == product_feature
            assert request.asin == ""
            assert request.keyword == "balloon pump"
            assert default_output_dir == DEFAULT_FEATURE_OUTPUT_DIRS["product_time_machine"]
            return _dummy_keyword_result()

    monkeypatch.setitem(FEATURE_DEFINITIONS["产品时光机"], "provider", lambda: DummyProvider())

    result = runner.invoke(app, ["run", "产品时光机", "--keyword", "balloon pump", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["keyword"] == "balloon pump"


def test_sif_run_passes_sections_and_page_size(monkeypatch):
    traffic_feature = FEATURE_ALIASES["traffic"]

    class DummyProvider:
        def run(self, request, *, default_output_dir):
            assert request.feature == traffic_feature
            assert request.sections == ["流量结构"]
            assert request.page_size == 20
            return _dummy_generic_result(traffic_feature)

    monkeypatch.setitem(FEATURE_DEFINITIONS["查流量"], "provider", lambda: DummyProvider())

    result = runner.invoke(
        app,
        ["run", "traffic", "--asin", "B01NBNDC1T", "--sections", "流量结构", "--page-size", "20", "--json"],
    )

    assert result.exit_code == 0


def test_sif_run_rejects_unknown_feature():
    result = runner.invoke(app, ["run", "unknown-feature", "--asin", "B01NBNDC1T", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert "不支持的 Sif 功能" in payload["error"]["message"]


def test_sif_run_permission_error_outputs_specific_code(monkeypatch):
    class DummyProvider:
        def run(self, request, *, default_output_dir):
            raise PermissionError("denied")

    monkeypatch.setattr("opscli.sif.cli.SifSalesProvider", lambda: DummyProvider())

    result = runner.invoke(app, ["run", "查销量", "--asin", "B01NBNDC1T", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "SIF_OUTPUT_PERMISSION_DENIED"
    assert payload["error"]["user_message"] == "当前输出目录没有写入权限。"
    assert "suggestion" in payload["error"]


def test_sif_run_login_error_outputs_friendly_message(monkeypatch):
    class DummyProvider:
        def run(self, request, *, default_output_dir):
            raise SifLoginRequiredError("UNAUTHORIZED")

    monkeypatch.setattr("opscli.sif.cli.SifSalesProvider", lambda: DummyProvider())

    result = runner.invoke(app, ["run", "查销量", "--asin", "B01NBNDC1T", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "SIF_LOGIN_REQUIRED"
    assert "SIF 平台账号登录状态不可用" in payload["error"]["user_message"]
    assert "opscli sif login-check" in payload["error"]["suggestion"]


def test_sif_login_check_outputs_sanitized_diagnostics(monkeypatch):
    class DummyClient:
        def __init__(self, *, settings, timeout):
            assert settings.username == "user"
            assert settings.password == "secret"
            assert timeout == 5.0

        def login_diagnostics(self):
            return {"has_cookie": True, "has_authorization": True}

    monkeypatch.setattr("opscli.sif.client.SifApiClient", DummyClient)

    result = runner.invoke(
        app,
        ["login-check", "--sif-username", "user", "--sif-password", "secret", "--timeout", "5"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert "secret" not in result.stdout


def test_sif_status_searches_feature_default_dirs(monkeypatch):
    root = Path("output") / "test-artifacts" / f"sif-status-{uuid4().hex}"
    job_dir = root / "traffic" / "runs" / "job-traffic"
    job_dir.mkdir(parents=True)
    (job_dir / "result.json").write_text(
        json.dumps({"schema_version": "sif_traffic.v1", "job_id": "job-traffic"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("opscli.sif.cli.load_settings", lambda: SimpleNamespace(output_dir=root / "sales" / "runs"))
    monkeypatch.setattr("opscli.sif.cli.DEFAULT_FEATURE_OUTPUT_DIRS", {"traffic": root / "traffic" / "runs"})

    result = runner.invoke(app, ["status", "job-traffic", "--pretty"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["schema_version"] == "sif_traffic.v1"
