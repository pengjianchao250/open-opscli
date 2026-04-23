import json

from typer.testing import CliRunner

from opscli.query.cli import app


runner = CliRunner()


def test_metadata_outputs_doc_aligned_json(monkeypatch):
    class DummyResult:
        def to_dict(self):
            return {
                "dataset": {"table_id": 1103, "dataset_alias": "ds_xxx"},
                "fields": [{"field_name": "date_id"}],
                "source": "local",
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
