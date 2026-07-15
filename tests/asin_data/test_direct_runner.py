import json
import subprocess
from pathlib import Path

from opscli.asin_data.services.collector import DirectOpsRunner, load_legacy_collector


class DummyWriter:
    def __init__(self):
        self.rows = []

    def write(self, payload):
        self.rows.append(payload)


class DummyLegacy:
    @staticmethod
    def is_payload_failure(payload):
        return isinstance(payload, dict) and payload.get("success") is False

    @staticmethod
    def strip_large_output(result):
        return result

    @staticmethod
    def write_json(path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def extract_error_message(payload, stderr):
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error = payload["error"]
            return f"{error.get('code')}: {error.get('message')}"
        return stderr


class DummyQueryManager:
    def __init__(self):
        self.called_with = None

    def metadata(self, **kwargs):
        raise AssertionError("metadata should not be called in this test")

    def build_simple_and_run(self, **kwargs):
        self.called_with = kwargs
        return {"result": {"data": [{"f_asin": "B0TEST1234", "f_order_qty": 3}]}}


class DummySellerSpriteResult:
    def to_dict(self):
        return {
            "job_id": "job-1",
            "scenario": "keyword-reverse",
            "site": "US",
            "period": "30d",
            "row_count": 1,
            "data": [{"keyword": "pool vacuum"}],
            "export": None,
        }


class DummySellerSpriteManager:
    def __init__(self):
        self.request = None

    async def run(self, request):
        self.request = request
        return DummySellerSpriteResult()


class MissingListingAnalysisExportManager:
    def __init__(self, job_id):
        self.job_id = job_id
        self.request = None
        self.missing_path = None

    async def run(self, request):
        self.request = request
        root_dir = Path(request.output_dir) / self.job_id
        root_dir.mkdir(parents=True, exist_ok=True)
        (root_dir / "raw.json").write_text(
            json.dumps(
                {
                    "job_id": self.job_id,
                    "scenario": "listing-analysis",
                    "response": {
                        "code": "OK",
                        "success": True,
                        "data": {
                            "taskId": "task-listing-1",
                            "taskStatus": "COMPLETED",
                            "content": json.dumps({"moduleName": "LA"}, ensure_ascii=False),
                            "completedTime": "2026-06-09 11:19:13",
                        },
                    },
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.missing_path = root_dir / f"{self.job_id}.json"
        raise FileNotFoundError(2, "No such file or directory", str(self.missing_path))


class DummyRufusManager:
    def __init__(self):
        self.called_with = None

    def get_backend(self, **kwargs):
        self.called_with = kwargs
        return {
            "asin": kwargs["asin"],
            "country": kwargs["country"],
            "answers": [{"index": 1, "question": kwargs["questions"][0], "answer": "ok"}],
        }


class DummyReportWriter:
    def __init__(self, report_path):
        self.report_path = report_path
        self.payload = None

    def write(self, payload):
        self.payload = payload
        self.report_path.write_text("# Rufus\n", encoding="utf-8")
        return self.report_path


def test_query_simple_runs_direct_manager_without_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("subprocess used")))
    payload_path = tmp_path / "query.json"
    payload_path.write_text(
        json.dumps(
            {
                "dimensions": [{"field": "ds_sales.asin", "alias": "f_asin"}],
                "metrics": [{"field": "ds_sales.order_qty", "aggregation": "SUM", "alias": "f_order_qty"}],
                "limit": 10,
            }
        ),
        encoding="utf-8",
    )
    query_manager = DummyQueryManager()
    runner = DirectOpsRunner(
        DummyLegacy(),
        query_manager=query_manager,
        seller_sprite_manager=object(),
        rufus_manager=object(),
        amazon_manager=object(),
        remote_consent_store=object(),
        report_writer=object(),
    )

    command_log = DummyWriter()
    result = runner.run_or_plan(
        source="query.sales",
        command=["__direct__", "query", "simple", "--table-id", "1103", "--payload", str(payload_path), "--run"],
        dry_run=False,
        command_log=command_log,
        error_log=DummyWriter(),
    )

    assert result["status"] == "success"
    assert result["execution"] == "direct"
    assert result["json"]["command"] == "query simple-run"
    assert query_manager.called_with["table_id"] == 1103
    assert query_manager.called_with["dimensions"] == [{"field": "ds_sales.asin", "alias": "f_asin"}]
    assert query_manager.called_with["validate_fields"] is True
    assert command_log.rows[0]["execution"] == "direct"


def test_seller_sprite_runs_direct_manager_without_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("subprocess used")))
    seller_manager = DummySellerSpriteManager()
    runner = DirectOpsRunner(
        DummyLegacy(),
        query_manager=object(),
        seller_sprite_manager=seller_manager,
        rufus_manager=object(),
        amazon_manager=object(),
        remote_consent_store=object(),
        report_writer=object(),
    )

    result = runner.run_or_plan(
        source="seller_sprite.keyword_reverse",
        command=[
            "__direct__",
            "seller-sprite",
            "run",
            "keyword-reverse",
            "--site",
            "US",
            "--period",
            "30d",
            "--params",
            '{"asin":"B0TEST1234"}',
            "--page-size",
            "50",
            "--export-format",
            "json",
            "--output-dir",
            str(tmp_path),
        ],
        dry_run=False,
        command_log=DummyWriter(),
        error_log=DummyWriter(),
        asin="B0TEST1234",
    )

    assert result["status"] == "success"
    assert result["execution"] == "direct"
    assert result["json"]["job_id"] == "job-1"
    assert seller_manager.request.scenario == "keyword-reverse"
    assert seller_manager.request.params == {"asin": "B0TEST1234"}
    assert seller_manager.request.page_size == 50


def test_listing_analysis_recovers_from_raw_when_export_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("subprocess used")))
    job_id = "SellerSprite-ListingAnalysis-US-B0TEST1234-Last-30-days-20260609-120000-abcdef"
    seller_manager = MissingListingAnalysisExportManager(job_id)
    error_log = DummyWriter()
    runner = DirectOpsRunner(
        DummyLegacy(),
        query_manager=object(),
        seller_sprite_manager=seller_manager,
        rufus_manager=object(),
        amazon_manager=object(),
        remote_consent_store=object(),
        report_writer=object(),
    )

    result = runner.run_or_plan(
        source="seller_sprite.listing_analysis",
        command=[
            "__direct__",
            "seller-sprite",
            "run",
            "listing-analysis",
            "--site",
            "US",
            "--period",
            "30d",
            "--params",
            '{"asin":"B0TEST1234","station":"GLOBAL"}',
            "--page-size",
            "100",
            "--export-format",
            "json",
            "--output-dir",
            str(tmp_path),
        ],
        dry_run=False,
        command_log=DummyWriter(),
        error_log=error_log,
        asin="B0TEST1234",
    )

    assert result["status"] == "success"
    assert error_log.rows == []
    assert result["json"]["job_id"] == job_id
    assert result["json"]["row_count"] == 1
    assert result["json"]["data"][0]["taskId"] == "task-listing-1"
    assert result["json"]["data"][0]["taskStatus"] == "COMPLETED"
    assert result["json"]["export"]["format"] == "json"
    assert seller_manager.missing_path is not None
    assert not seller_manager.missing_path.exists()
    assert Path(result["json"]["export"]["path"]).exists()
    assert (seller_manager.missing_path.parent / "result.json").exists()


def test_rufus_backend_writes_report_stdout_that_legacy_parser_understands(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("subprocess used")))
    legacy = load_legacy_collector()
    rufus_manager = DummyRufusManager()
    report_path = tmp_path / "rufus-report.md"
    report_writer = DummyReportWriter(report_path)
    runner = DirectOpsRunner(
        legacy,
        query_manager=object(),
        seller_sprite_manager=object(),
        rufus_manager=rufus_manager,
        amazon_manager=object(),
        remote_consent_store=object(),
        report_writer=report_writer,
    )

    result = runner.run_or_plan(
        source="rufus.get_backend",
        command=[
            "__direct__",
            "amazon-rufus",
            "get-backend",
            "B0TEST1234",
            "US",
            "--skills-dir",
            ".agents/skills",
            "--timeout",
            "15",
            "--no-upload-payload",
            "-q",
            "这是什么商品？",
        ],
        dry_run=False,
        command_log=DummyWriter(),
        error_log=DummyWriter(),
        asin="B0TEST1234",
    )

    assert result["status"] == "success"
    assert rufus_manager.called_with["asin"] == "B0TEST1234"
    assert rufus_manager.called_with["questions"] == ["这是什么商品？"]
    assert rufus_manager.called_with["include_upload_payload"] is False
    assert report_writer.payload["asin"] == "B0TEST1234"
    assert legacy.extract_rufus_report_path(result["stdout"]) == report_path.as_posix()
