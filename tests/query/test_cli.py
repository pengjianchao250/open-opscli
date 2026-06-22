import json

from typer.testing import CliRunner

from opscli.query.cli import app


runner = CliRunner()


def test_metadata_outputs_doc_aligned_json(monkeypatch):
    class DummyResult:
        source = "remote"

        def to_dict(self):
            return {
                "dataset": {"table_id": 1103, "dataset_alias": "ds_xxx"},
                "fields": [{"field_name": "date_id"}],
                "source": self.source,
            }

    class DummyManager:
        def metadata(self, **kwargs):
            return DummyResult()

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: DummyManager())

    result = runner.invoke(app, ["metadata", "--dataset", "ds_xxx"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query metadata"
    assert payload["data"]["dataset"]["table_id"] == 1103


def test_metadata_no_args_outputs_hint(monkeypatch):
    """未指定 --dataset / --table-id 时，远端优先返回数据集列表并附带 hint。"""
    class DummyResult:
        source = "remote"

        def to_dict(self):
            return {
                "dataset": {},
                "fields": [],
                "source": self.source,
                "all_datasets": [
                    {"table_id": 1103, "dataset_alias": "ds_sales", "dataset_name": "销售数据"},
                ],
            }

    class DummyManager:
        def metadata(self, **kwargs):
            return DummyResult()

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: DummyManager())

    result = runner.invoke(app, ["metadata"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query metadata"
    assert payload["data"]["all_datasets"] == [{"table_id": 1103, "dataset_alias": "ds_sales", "dataset_name": "销售数据"}]
    assert "hint" in payload
    assert "远端最新数据集列表" in payload["hint"]


def test_metadata_no_args_local_fallback_hint(monkeypatch):
    """未指定参数时远端失败，回退到本地缓存并附带升级提示。"""
    class DummyResult:
        source = "local"

        def to_dict(self):
            return {
                "dataset": {},
                "fields": [],
                "source": self.source,
                "all_datasets": [
                    {"table_id": 1103, "dataset_alias": "ds_sales", "dataset_name": "销售数据"},
                ],
            }

    class DummyManager:
        def metadata(self, **kwargs):
            return DummyResult()

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: DummyManager())

    result = runner.invoke(app, ["metadata"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert "hint" in payload
    assert "远端获取失败" in payload["hint"]
    assert "回退到本地缓存" in payload["hint"]


def test_metadata_local_fallback_adds_hint(monkeypatch):
    """指定数据集但远端失败回退到本地时，附带升级提示。"""
    class DummyResult:
        source = "local"

        def to_dict(self):
            return {
                "dataset": {"table_id": 1103, "dataset_alias": "ds_xxx"},
                "fields": [{"field_name": "date_id"}],
                "source": self.source,
            }

    class DummyManager:
        def metadata(self, **kwargs):
            return DummyResult()

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: DummyManager())

    result = runner.invoke(app, ["metadata", "--dataset", "ds_xxx"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert "hint" in payload
    assert "远端获取失败" in payload["hint"]


def test_run_outputs_doc_aligned_json(monkeypatch, tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text("{}", encoding="utf-8")

    class DummyManager:
        def run(self, **kwargs):
            return {"rows": [{"date_id": "2022-01-01"}], "meta": {"rowCount": 1}}

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: DummyManager())

    result = runner.invoke(app, ["run", "--payload", str(payload_file)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query run"
    assert payload["data"]["meta"]["rowCount"] == 1


def test_catalog_passes_source_and_fallback_options(monkeypatch):
    class DummyManager:
        def __init__(self):
            self.called_with = None

        def catalog(self, **kwargs):
            self.called_with = kwargs
            return {"version": "remote", "intent_count": 1, "intents": []}

    manager = DummyManager()
    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: manager)

    result = runner.invoke(app, ["catalog", "--source", "remote", "--no-fallback-local", "--skills-dir", "/tmp/skills"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query catalog"
    assert payload["data"]["version"] == "remote"
    assert manager.called_with == {
        "skills_dir": "/tmp/skills",
        "source": "remote",
        "fallback_local": False,
    }


def test_intent_passes_query_and_outputs_match(monkeypatch):
    class DummyManager:
        def __init__(self):
            self.called_with = None

        def intent_match(self, **kwargs):
            self.called_with = kwargs
            return {
                "matched": True,
                "selected": {"dataset_alias": "ds_sales", "intent_constraints": {"scenario_description": "销售规则"}},
                "candidates": [],
            }

    manager = DummyManager()
    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: manager)

    result = runner.invoke(
        app,
        [
            "intent",
            "--query",
            "查看销售趋势",
            "--source",
            "local",
            "--no-fallback-local",
            "--skills-dir",
            "/tmp/skills",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query intent"
    assert payload["data"]["selected"]["dataset_alias"] == "ds_sales"
    assert manager.called_with == {
        "query": "查看销售趋势",
        "skills_dir": "/tmp/skills",
        "source": "local",
        "fallback_local": False,
    }


def test_run_outputs_query_error_payload(monkeypatch, tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text("{}", encoding="utf-8")

    class DummyManager:
        def run(self, **kwargs):
            raise ValueError("bad payload")

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: DummyManager())

    result = runner.invoke(app, ["run", "--payload", str(payload_file)])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error"]["code"] == "QUERY_ERROR"
    assert payload["error"]["message"] == "bad payload"


def test_build_outputs_doc_aligned_json(monkeypatch):
    class DummyManager:
        def build(self, **kwargs):
            return {
                "dataset": {"table_id": 1103, "dataset_alias": "ds_xxx"},
                "payload": {"tableId": 1103, "query": {"select": []}},
                "output": None,
            }

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: DummyManager())

    result = runner.invoke(app, ["build", "--dataset", "ds_xxx", "--dimension", "date_id"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query build"
    assert payload["data"]["dataset"]["table_id"] == 1103


def test_simple_passes_dataset_for_field_validation(monkeypatch, tmp_path):
    payload_file = tmp_path / "simple.json"
    payload_file.write_text(json.dumps({"dimensions": [{"field": "order_sale_trend_set.asin"}]}), encoding="utf-8")

    class DummyManager:
        def __init__(self):
            self.called_with = None

        def build_simple(self, **kwargs):
            self.called_with = kwargs
            return {"payload": {"tableId": kwargs["table_id"]}, "output": None}

    manager = DummyManager()
    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: manager)

    result = runner.invoke(
        app,
        [
            "simple",
            "--table-id",
            "1103",
            "--dataset",
            "order_sale_trend_set",
            "--payload",
            str(payload_file),
        ],
    )

    assert result.exit_code == 0
    assert manager.called_with["dataset_alias"] == "order_sale_trend_set"
    assert manager.called_with["validate_fields"] is True


def test_build_passes_short_where_flags(monkeypatch):
    class DummyManager:
        def __init__(self):
            self.called_with = None

        def build(self, **kwargs):
            self.called_with = kwargs
            return {
                "dataset": {"table_id": 1103, "dataset_alias": "ds_xxx"},
                "payload": {"tableId": 1103, "query": {"select": []}},
                "output": None,
            }

    manager = DummyManager()
    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: manager)

    result = runner.invoke(
        app,
        [
            "build",
            "--dataset",
            "ds_xxx",
            "--dimension",
            "date_id",
            "--where",
            'country_name|in|["美国"]',
            "--where",
            'date_id|between|["2022-01-01","2022-03-31"]',
        ],
    )

    assert result.exit_code == 0
    assert manager.called_with["where_conditions"] == [
        'country_name|in|["美国"]',
        'date_id|between|["2022-01-01","2022-03-31"]',
    ]


def test_build_passes_having_and_dry_run(monkeypatch):
    class DummyManager:
        def __init__(self):
            self.called_with = None

        def build(self, **kwargs):
            self.called_with = kwargs
            return {
                "dataset": {"table_id": 1103, "dataset_alias": "ds_xxx"},
                "payload": {"tableId": 1103, "query": {"select": []}, "dryRun": True},
                "output": None,
            }

    manager = DummyManager()
    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: manager)

    result = runner.invoke(
        app,
        [
            "build",
            "--dataset",
            "ds_xxx",
            "--dimension",
            "date_id",
            "--having",
            "f_metric001|gt|100",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert manager.called_with["having_conditions"] == ["f_metric001|gt|100"]
    assert manager.called_with["dry_run"] is True


def test_build_run_uses_build_and_run(monkeypatch):
    class DummyManager:
        def __init__(self):
            self.called_with = None

        def build_and_run(self, **kwargs):
            self.called_with = kwargs
            return {
                "dataset": {"table_id": 1103, "dataset_alias": "ds_xxx"},
                "payload": {"tableId": 1103, "query": {"select": []}},
                "output": None,
                "result": {"success": True, "data": [], "meta": {"rowCount": 0}},
            }

    manager = DummyManager()
    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: manager)

    result = runner.invoke(app, ["build", "--dataset", "ds_xxx", "--dimension", "date_id", "--run"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query build-and-run"
    assert payload["data"]["result"]["meta"]["rowCount"] == 0
    assert manager.called_with["dataset_alias"] == "ds_xxx"


# ── chart CLI 测试 ────────────────────────────────────────────────────

def test_chart_outputs_queries_without_run(monkeypatch):
    class DummyManager:
        def fetch_chart_bundle(self, chart_uuid):
            return {
                "chart_uuid": chart_uuid,
                "request_id": "req-1",
                "datasets": [{"dataset_alias": "ds_xxx", "tableId": 1, "dataSource": "doris", "fields": [], "filterable_fields": []}],
                "queries": [{"query": {"select": []}, "tableId": 1}],
            }

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", DummyManager)

    result = runner.invoke(app, ["chart", "--uuid", "chart-123"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query chart"
    assert payload["data"]["chart_uuid"] == "chart-123"
    assert len(payload["data"]["datasets"]) == 1
    assert len(payload["data"]["queries"]) == 1


def test_chart_run_outputs_merged_results(monkeypatch):
    class DummyManager:
        def run_chart_queries(self, chart_uuid, dry_run=False):
            return {
                "chart_uuid": chart_uuid,
                "queries": [],
                "merged": {"rows": [], "meta": {"rowCount": 0, "queryCount": 0, "successCount": 0}},
            }

    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", DummyManager)

    result = runner.invoke(app, ["chart", "--uuid", "chart-456", "--run"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query chart-run"
    assert payload["data"]["merged"]["meta"]["rowCount"] == 0


def test_chart_dry_run_passes_flag(monkeypatch):
    class DummyManager:
        def __init__(self):
            self.dry_run = None

        def run_chart_queries(self, chart_uuid, dry_run=False):
            self.dry_run = dry_run
            return {"chart_uuid": chart_uuid, "queries": [], "merged": {"rows": [], "meta": {}}}

    manager = DummyManager()
    monkeypatch.setattr("opscli.query.commands.cli.QueryManager", lambda: manager)

    result = runner.invoke(app, ["chart", "--uuid", "chart-789", "--run", "--dry-run"])

    assert result.exit_code == 0
    assert manager.dry_run is True
