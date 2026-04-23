import json

import pytest

from opscli.query.exceptions import DatasetNotFoundError, InvalidPayloadError
from opscli.query.manager import QueryManager
from opscli.skills.models import SkillRecord


def test_metadata_reads_from_installed_dataset_fields(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [
            {"table_id": 1103, "field_name": "date_id"},
            {"table_id": 1104, "field_name": "country_name"},
        ],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])

    result = manager.metadata(dataset_alias="ds_xxx")

    assert result.dataset["table_id"] == 1103
    assert result.fields == [{"table_id": 1103, "field_name": "date_id"}]
    assert result.source == "local"


def test_metadata_raises_when_dataset_missing(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {"datasets": [], "fields": []}
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])

    with pytest.raises(DatasetNotFoundError):
        manager.metadata(dataset_alias="missing_ds")


def test_run_validates_required_payload_structure(tmp_path):
    manager = QueryManager()
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps({"query": {}}), encoding="utf-8")

    with pytest.raises(InvalidPayloadError):
        manager.run(payload_path=str(payload_file))


def test_run_forwards_payload_to_client(tmp_path, monkeypatch):
    manager = QueryManager()
    payload = {"tableId": 1103, "query": {"select": []}}
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")
    called = {}

    def fake_cli_query(request_payload):
        called["payload"] = request_payload
        return {"rows": [], "meta": {"rowCount": 0}}

    monkeypatch.setattr(manager.client, "cli_query", fake_cli_query)

    result = manager.run(payload_path=str(payload_file))

    assert called["payload"] == payload
    assert result["meta"]["rowCount"] == 0


def test_build_constructs_payload_from_dimension_metric_and_where(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [
            {"table_id": 1103, "field_name": "country_name"},
            {"table_id": 1103, "field_name": "price"},
        ],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])

    result = manager.build(
        dataset_alias="ds_xxx",
        dimensions=["country_name:f_dim001"],
        metrics=["price:sum:f_metric001"],
        where_json=json.dumps(
            {
                "operator": "AND",
                "conditions": [{"field": "ds_xxx.country_name", "operator": "in", "value": ["美国"]}],
            }
        ),
        order_by=["f_metric001:desc"],
        limit=5,
    )

    assert result["payload"] == {
        "tableId": 1103,
        "query": {
            "select": [
                {"expr": "ds_xxx.country_name", "alias": "f_dim001"},
                {"expr": "ds_xxx.price", "alias": "f_metric001", "aggregation": "SUM"},
            ],
            "groupBy": ["f_dim001"],
            "orderBy": [{"expr": "f_metric001", "desc": True}],
            "limit": 5,
            "offset": 0,
            "where": {
                "operator": "AND",
                "conditions": [{"field": "ds_xxx.country_name", "operator": "in", "value": ["美国"]}],
            },
        },
    }


def test_build_supports_having_and_dry_run(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [
            {"table_id": 1103, "field_name": "country_name"},
            {"table_id": 1103, "field_name": "price"},
        ],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])

    result = manager.build(
        dataset_alias="ds_xxx",
        dimensions=["country_name:f_dim001"],
        metrics=["price:sum:f_metric001"],
        having_conditions=['f_metric001|gt|100'],
        dry_run=True,
    )

    assert result["payload"]["dryRun"] is True
    assert result["payload"]["query"]["having"] == [
        {"field": "f_metric001", "operator": "gt", "value": 100},
    ]


def test_build_constructs_where_from_repeated_short_flags(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [
            {"table_id": 1103, "field_name": "country_name"},
            {"table_id": 1103, "field_name": "date_id"},
            {"table_id": 1103, "field_name": "price"},
        ],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])

    result = manager.build(
        dataset_alias="ds_xxx",
        dimensions=["country_name:f_dim001"],
        metrics=["price:sum:f_metric001"],
        where_conditions=[
            'country_name|in|["美国"]',
            'date_id|between|["2022-01-01","2022-03-31"]',
        ],
    )

    assert result["payload"]["query"]["where"] == {
        "operator": "AND",
        "conditions": [
            {"field": "ds_xxx.country_name", "operator": "in", "value": ["美国"]},
            {"field": "ds_xxx.date_id", "operator": "between", "value": ["2022-01-01", "2022-03-31"]},
        ],
    }


def test_build_rejects_multiple_where_sources(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [{"table_id": 1103, "field_name": "date_id"}],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])

    with pytest.raises(InvalidPayloadError):
        manager.build(
            dataset_alias="ds_xxx",
            dimensions=["date_id"],
            where_conditions=['date_id|=|"2022-01-01"'],
            where_json='{"operator":"AND","conditions":[]}',
        )


def test_build_rejects_invalid_having(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [{"table_id": 1103, "field_name": "date_id"}],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])

    with pytest.raises(InvalidPayloadError):
        manager.build(
            dataset_alias="ds_xxx",
            dimensions=["date_id"],
            having_conditions=["bad-format"],
        )


def test_build_writes_output_file(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [{"table_id": 1103, "field_name": "date_id"}],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])
    output_file = tmp_path / "payloads" / "query.json"

    result = manager.build(
        dataset_alias="ds_xxx",
        dimensions=["date_id"],
        output_path=str(output_file),
    )

    assert output_file.exists() is True
    assert json.loads(output_file.read_text(encoding="utf-8")) == result["payload"]


def test_build_raises_when_field_missing(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [{"table_id": 1103, "field_name": "date_id"}],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])

    with pytest.raises(InvalidPayloadError):
        manager.build(dataset_alias="ds_xxx", dimensions=["missing_field"])


def test_build_and_run_uses_built_payload(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [{"table_id": 1103, "field_name": "date_id"}],
    }
    (data_dir / "query_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])
    called = {}

    def fake_cli_query(request_payload):
        called["payload"] = request_payload
        return {"success": True, "data": [{"date_id": "2022-01-01"}], "meta": {"rowCount": 1}}

    monkeypatch.setattr(manager.client, "cli_query", fake_cli_query)

    result = manager.build_and_run(dataset_alias="ds_xxx", dimensions=["date_id"])

    assert called["payload"] == result["payload"]
    assert result["result"]["meta"]["rowCount"] == 1
