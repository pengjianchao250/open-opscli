import asyncio
import json
from pathlib import Path

from opscli.google_trends.config import GoogleTrendsSettings
from opscli.google_trends.domain.models import GoogleTrendsExportResult
from opscli.google_trends.domain.models import GoogleTrendsScenarioRequest
from opscli.google_trends.services import api_manager as api_manager_module
from opscli.google_trends.services.api_manager import GoogleTrendsApiManager, extract_rows


def _run(coro):
    return asyncio.run(coro)


class DummyGoogleTrendsClient:
    """模拟 SerpApi Google Trends 客户端。"""

    requests = []

    def run(self, scenario, params):
        """记录请求并返回 SerpApi 时间序列结构。"""
        self.__class__.requests.append({"scenario": scenario, "params": params})
        return {
            "interest_over_time": {
                "timeline_data": [
                    {
                        "date": "2026-01-01",
                        "values": [
                            {"query": "flashlight", "value": "42", "extracted_value": 42}
                        ],
                    }
                ]
            }
        }

    def close(self):
        """模拟关闭 HTTP 客户端。"""


class DisabledUploadClient:
    def __init__(self, *args, **kwargs):
        self.enabled = False


def test_manager_writes_params_raw_result_and_json_export(monkeypatch, tmp_path: Path):
    DummyGoogleTrendsClient.requests = []
    monkeypatch.setattr(api_manager_module, "SerpApiGoogleTrendsClient", DummyGoogleTrendsClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)
    settings = GoogleTrendsSettings(output_dir=tmp_path)
    manager = GoogleTrendsApiManager(settings=settings)

    result = _run(
        manager.run(
            GoogleTrendsScenarioRequest(
                scenario="trends",
                geo="US",
                params={"q": "flashlight", "date": "today 12-m"},
                job_id="google-trends-offline-regression",
                export_format="json",
                hl="en-US",
                tz=360,
            )
        )
    )

    root_dir = tmp_path / "google-trends-offline-regression"
    assert result.row_count == 1
    assert (root_dir / "params.json").exists()
    assert (root_dir / "raw.json").exists()
    assert (root_dir / "result.json").exists()
    assert result.export is not None
    assert result.export.filename == "google-trends-offline-regression.json"
    assert result.export.format == "json"

    params_payload = json.loads((root_dir / "params.json").read_text(encoding="utf-8"))
    raw_payload = json.loads((root_dir / "raw.json").read_text(encoding="utf-8"))
    result_payload = json.loads((root_dir / "result.json").read_text(encoding="utf-8"))
    export_payload = json.loads((root_dir / "google-trends-offline-regression.json").read_text(encoding="utf-8"))

    assert params_payload["normalized_params"]["q"] == "flashlight"
    assert params_payload["normalized_params"]["hl"] == "en"
    assert params_payload["normalized_params"]["tz"] == "360"
    assert raw_payload["request_params"]["date"] == "today 12-m"
    assert raw_payload["response"]["interest_over_time"]["timeline_data"][0]["values"]
    assert result_payload["row_count"] == 1
    assert export_payload["rows"][0]["flashlight"] == 42
    assert export_payload["raw_response"]["interest_over_time"]["timeline_data"][0]["values"]
    assert DummyGoogleTrendsClient.requests[0]["scenario"] == "trends"
    assert DummyGoogleTrendsClient.requests[0]["params"]["hl"] == "en"
    assert DummyGoogleTrendsClient.requests[0]["params"]["tz"] == "360"


def test_manager_submits_complete_success_result_to_collection_storage(
    monkeypatch, tmp_path: Path
):
    """完整成功结果落盘后应提交到共享数据沉淀。"""
    submissions = []
    monkeypatch.setattr(api_manager_module, "SerpApiGoogleTrendsClient", DummyGoogleTrendsClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)

    def submitter(*, request, result):
        assert Path(result.result_path).is_file()
        assert result.export is not None
        assert Path(result.export.path).is_file()
        submissions.append((request, result))
        return True

    manager = GoogleTrendsApiManager(
        settings=GoogleTrendsSettings(output_dir=tmp_path),
        collection_submitter=submitter,
    )
    request = GoogleTrendsScenarioRequest(
        scenario="trends",
        geo="US",
        params={"q": "flashlight"},
        job_id="google-trends-collection-submit",
        export_format="json",
    )

    result = _run(manager.run(request))

    assert submissions == [(request, result)]


def test_manager_keeps_result_when_collection_storage_submission_fails(
    monkeypatch, tmp_path: Path
):
    """沉淀排队失败时应保留成功结果并返回脱敏 warning。"""
    monkeypatch.setattr(api_manager_module, "SerpApiGoogleTrendsClient", DummyGoogleTrendsClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)

    def submitter(**_kwargs):
        raise RuntimeError("mysql password leaked")

    manager = GoogleTrendsApiManager(
        settings=GoogleTrendsSettings(output_dir=tmp_path),
        collection_submitter=submitter,
    )
    request = GoogleTrendsScenarioRequest(
        scenario="trends",
        geo="US",
        params={"q": "flashlight"},
        job_id="google-trends-collection-warning",
        export_format="json",
    )

    result = _run(manager.run(request))
    persisted = json.loads(Path(result.result_path).read_text(encoding="utf-8"))

    assert result.row_count == 1
    assert result.warnings[-1] == {
        "stage": "collection_storage",
        "message": "Google Trends 数据沉淀排队失败，采集结果已保留",
        "error": {"code": "RuntimeError"},
    }
    assert persisted["warnings"] == result.warnings
    assert "mysql password leaked" not in json.dumps(persisted, ensure_ascii=False)


def test_manager_uses_xlsx_export_by_default(monkeypatch, tmp_path: Path):
    DummyGoogleTrendsClient.requests = []
    monkeypatch.setattr(api_manager_module, "SerpApiGoogleTrendsClient", DummyGoogleTrendsClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)

    def fake_export_rows_to_xlsx(*, rows, output_path, scenario, geo, params):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("xlsx-placeholder", encoding="utf-8")
        return GoogleTrendsExportResult(path=str(output_path), filename=output_path.name)

    monkeypatch.setattr(api_manager_module, "export_rows_to_xlsx", fake_export_rows_to_xlsx)
    settings = GoogleTrendsSettings(output_dir=tmp_path)
    manager = GoogleTrendsApiManager(settings=settings)

    result = _run(
        manager.run(
            GoogleTrendsScenarioRequest(
                scenario="trends",
                geo="US",
                params={"q": "flashlight"},
                job_id="google-trends-xlsx-regression",
            )
        )
    )

    assert result.export is not None
    assert result.export.filename == "google-trends-xlsx-regression.xlsx"
    assert (tmp_path / "google-trends-xlsx-regression" / "google-trends-xlsx-regression.xlsx").exists()
    status = manager.job_status("google-trends-xlsx-regression")
    assert status["job_id"] == "google-trends-xlsx-regression"
    assert status["export"]["filename"] == "google-trends-xlsx-regression.xlsx"


def test_extract_rows_supports_all_serpapi_result_shapes():
    """三类 SerpApi 接口及 Trends 相关查询都应生成可导出行。"""
    suggestions = extract_rows(
        "autocomplete",
        {"suggestions": [{"q": "/m/apple", "title": "Apple", "type": "Company"}]},
    )
    trending = extract_rows(
        "trending-now",
        {"trending_searches": [{"query": "flashlight", "search_volume": 20000}]},
    )
    related = extract_rows(
        "trends",
        {
            "related_queries": {
                "top": [{"query": "led flashlight", "extracted_value": 100}],
                "rising": [{"query": "rechargeable flashlight", "extracted_value": 900}],
            }
        },
    )
    regions = extract_rows(
        "trends",
        {
            "compared_breakdown_by_region": [
                {
                    "geo": "US-CA",
                    "location": "California",
                    "values": [
                        {"query": "flashlight", "extracted_value": 60},
                        {"query": "lantern", "extracted_value": 40},
                    ],
                }
            ]
        },
    )
    topics = extract_rows(
        "trends",
        {
            "related_topics": {
                "top": [
                    {
                        "topic": {
                            "value": "/m/01fdzj",
                            "title": "Flashlight",
                            "type": "Topic",
                        },
                        "extracted_value": 100,
                    }
                ]
            }
        },
    )

    assert suggestions[0]["q"] == "/m/apple"
    assert trending[0]["search_term"] == "flashlight"
    assert trending[0]["rank"] == 1
    assert related == [
        {"query": "led flashlight", "extracted_value": 100, "type": "top"},
        {"query": "rechargeable flashlight", "extracted_value": 900, "type": "rising"},
    ]
    assert regions == [
        {"geo": "US-CA", "location": "California", "flashlight": 60, "lantern": 40}
    ]
    assert topics == [
        {
            "extracted_value": 100,
            "topic_id": "/m/01fdzj",
            "topic_title": "Flashlight",
            "topic_type": "Topic",
            "type": "top",
        }
    ]
