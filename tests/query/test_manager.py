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


def test_catalog_defaults_to_remote(monkeypatch):
    manager = QueryManager()
    called = {}

    def fake_fetch_dataset_catalog():
        called["remote"] = True
        return {"version": "remote", "intent_count": 1, "intents": [{"intent_code": "sales"}]}

    monkeypatch.setattr(manager.client, "fetch_dataset_catalog", fake_fetch_dataset_catalog)

    result = manager.catalog()

    assert called["remote"] is True
    assert result["version"] == "remote"


def test_catalog_can_force_local(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    local_payload = {"version": "local", "intent_count": 0, "intents": []}
    (data_dir / "dataset_catalog.json").write_text(json.dumps(local_payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])
    monkeypatch.setattr(manager.client, "fetch_dataset_catalog", lambda: pytest.fail("remote should not be called"))

    result = manager.catalog(source="local")

    assert result == local_payload


def test_catalog_falls_back_to_local_when_remote_fails(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    local_payload = {"version": "local", "intent_count": 0, "intents": []}
    (data_dir / "dataset_catalog.json").write_text(json.dumps(local_payload), encoding="utf-8")
    record = SkillRecord(
        name="ops-dataset-query",
        version="v0.1.0",
        runtime="claude",
        root=skill_root,
        version_file=data_dir / "VERSION.json",
    )
    monkeypatch.setattr(manager.detector, "discover", lambda **kwargs: [record])
    monkeypatch.setattr(manager.client, "fetch_dataset_catalog", lambda: (_ for _ in ()).throw(RuntimeError("remote down")))

    result = manager.catalog()

    assert result == local_payload


def test_catalog_can_disable_local_fallback(monkeypatch):
    manager = QueryManager()
    monkeypatch.setattr(manager.client, "fetch_dataset_catalog", lambda: (_ for _ in ()).throw(RuntimeError("remote down")))

    with pytest.raises(RuntimeError, match="remote down"):
        manager.catalog(fallback_local=False)


def test_catalog_rejects_invalid_source():
    manager = QueryManager()

    with pytest.raises(InvalidPayloadError):
        manager.catalog(source="server")


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


def test_build_defaults_alias_to_global_alias_and_supports_verbose_name(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [
            {
                "table_id": 1103,
                "field_name": "country_name",
                "verbose_name": "国家",
                "field_type": "dimension",
                "global_alias": "ga_country_name",
            },
            {
                "table_id": 1103,
                "field_name": "price",
                "verbose_name": "销售额",
                "field_type": "metric",
                "global_alias": "ga_price",
            },
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
        dimensions=["国家"],
        metrics=["ga_price:sum"],
    )

    assert result["payload"]["query"]["select"] == [
        {"expr": "ds_xxx.country_name", "alias": "ga_country_name"},
        {"expr": "ds_xxx.price", "alias": "ga_price", "aggregation": "SUM"},
    ]
    assert result["payload"]["query"]["groupBy"] == ["ga_country_name"]


def test_build_uses_summary_expression_for_formula_metric(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [
            {
                "table_id": 1103,
                "field_name": "days_on_hand",
                "field_type": "metric",
                "global_alias": "ga_days_on_hand",
                "summary_expression": "ROUND(30 / (SUM(total_sell_qty) / SUM(sell_avg_qty)))",
                "detail_expression": "ROUND(30 / (total_sell_qty / sell_avg_qty))",
                "has_formula_config": 1,
            },
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
        metrics=["ga_days_on_hand:sum"],
    )

    assert result["payload"]["query"]["select"] == [
        {
            "expr": "ROUND(30 / (SUM(total_sell_qty) / SUM(sell_avg_qty)))",
            "alias": "ga_days_on_hand",
        }
    ]


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


def test_build_rejects_non_ascii_alias(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [{"table_id": 1103, "field_name": "date_id", "field_type": "dimension", "global_alias": "ga_date_id"}],
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
        manager.build(dataset_alias="ds_xxx", dimensions=["date_id:日期"])


def test_build_rejects_ambiguous_verbose_name(tmp_path, monkeypatch):
    manager = QueryManager()
    skill_root = tmp_path / ".claude" / "skills" / "ops-dataset-query"
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [
            {"table_id": 1103, "field_name": "country_name", "verbose_name": "名称", "field_type": "dimension", "global_alias": "ga_country_name"},
            {"table_id": 1103, "field_name": "dept_name", "verbose_name": "名称", "field_type": "dimension", "global_alias": "ga_dept_name"},
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

    with pytest.raises(InvalidPayloadError):
        manager.build(dataset_alias="ds_xxx", dimensions=["名称"])


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


# ── chart query 测试 ──────────────────────────────────────────────────

def test_build_payload_from_chart_query_converts_structure():
    manager = QueryManager()
    chart_item = {
        "query": {
            "from": {"alias": "ds_xxx", "database": ""},
            "select": [{"expr": "ds_xxx.date_id", "alias": "f_date"}],
            "where": {"operator": "AND", "conditions": []},
            "limit": 100,
        },
        "dataSource": "doris_analytics",
        "tableId": 1103,
    }

    payload = manager.build_payload_from_chart_query(chart_item)

    assert payload["tableId"] == 1103
    assert "from" not in payload["query"]
    assert payload["query"]["select"] == [{"expr": "ds_xxx.date_id", "alias": "f_date"}]
    assert payload["query"]["limit"] == 100


def test_build_payload_from_chart_query_raises_when_table_id_missing():
    manager = QueryManager()

    with pytest.raises(InvalidPayloadError):
        manager.build_payload_from_chart_query({"query": {"select": []}})


def test_run_chart_queries_executes_all_and_merges_results(monkeypatch):
    manager = QueryManager()
    chart_items = [
        {"query": {"select": [{"expr": "a", "alias": "f1"}]}, "dataSource": "doris", "tableId": 1},
        {"query": {"select": [{"expr": "b", "alias": "f2"}]}, "dataSource": "doris", "tableId": 2},
    ]

    def fake_fetch(uuid):
        return chart_items

    def fake_cli_query(payload):
        table_id = payload["tableId"]
        return {"rows": [{"v": table_id}], "meta": {"rowCount": 1}}

    monkeypatch.setattr(manager.client, "fetch_chart_queries", fake_fetch)
    monkeypatch.setattr(manager.client, "cli_query", fake_cli_query)

    result = manager.run_chart_queries("chart-123")

    assert result["chart_uuid"] == "chart-123"
    assert len(result["queries"]) == 2
    assert result["queries"][0]["result"]["rows"][0]["v"] == 1
    assert result["queries"][1]["result"]["rows"][0]["v"] == 2
    # merged
    assert len(result["merged"]["rows"]) == 2
    assert result["merged"]["rows"][0]["_query_index"] == 0
    assert result["merged"]["rows"][1]["_query_index"] == 1
    assert result["merged"]["meta"]["rowCount"] == 2
    assert result["merged"]["meta"]["successCount"] == 2


def test_run_chart_queries_continues_on_single_failure(monkeypatch):
    manager = QueryManager()
    chart_items = [
        {"query": {"select": []}, "dataSource": "doris", "tableId": 1},
        {"query": {"select": []}, "dataSource": "doris", "tableId": 2},
    ]

    def fake_fetch(uuid):
        return chart_items

    def fake_cli_query(payload):
        if payload["tableId"] == 1:
            raise ValueError(" simulated failure")
        return {"rows": [{"ok": True}], "meta": {"rowCount": 1}}

    monkeypatch.setattr(manager.client, "fetch_chart_queries", fake_fetch)
    monkeypatch.setattr(manager.client, "cli_query", fake_cli_query)

    result = manager.run_chart_queries("chart-456")

    assert result["queries"][0]["error"] is not None
    assert result["queries"][1]["result"] is not None
    assert result["merged"]["meta"]["successCount"] == 1
    assert len(result["merged"]["rows"]) == 1


def test_run_chart_queries_supports_dry_run(monkeypatch):
    manager = QueryManager()
    chart_items = [
        {"query": {"select": []}, "dataSource": "doris", "tableId": 1},
    ]

    called = {}

    def fake_fetch(uuid):
        return chart_items

    def fake_cli_query(payload):
        called["dry_run"] = payload.get("dryRun")
        return {"rows": [], "meta": {"rowCount": 0}}

    monkeypatch.setattr(manager.client, "fetch_chart_queries", fake_fetch)
    monkeypatch.setattr(manager.client, "cli_query", fake_cli_query)

    manager.run_chart_queries("chart-789", dry_run=True)

    assert called["dry_run"] is True


def test_generate_chart_doc_uses_server_field_mappings(monkeypatch):
    manager = QueryManager()
    bundle = {
        "chart_uuid": "chart-123",
        "request_id": "req-1",
        "datasets": [
            {
                "dataset_alias": "ds_sales",
                "tableId": 3,
                "dataSource": "doris_analytics",
                "filterable_fields": [
                    {
                        "column_name": "date_id",
                        "verbose_name": "日期",
                        "source_column_name": "date_id",
                    }
                ],
                "fields": [
                    {
                        "field_type": "dimension",
                        "verbose_name": "渠道",
                        "field_name": "channel_name",
                        "origin_name": "ds_sales.channel_name",
                        "global_alias": "ga_channel_name",
                        "query_aliases": ["f_channel"],
                        "aggregations": [],
                        "sources": ["select"],
                    },
                    {
                        "field_type": "metric",
                        "verbose_name": "订单量",
                        "field_name": "order_qty",
                        "origin_name": "ds_sales.order_qty",
                        "global_alias": "ga_order_qty",
                        "query_aliases": ["f_order_qty"],
                        "aggregations": ["SUM"],
                        "sources": ["select"],
                    },
                    {
                        "field_type": "dimension",
                        "verbose_name": "日期",
                        "field_name": "date_id",
                        "origin_name": "ds_sales.date_id",
                        "global_alias": "ga_date_id",
                        "query_aliases": [],
                        "aggregations": [],
                        "sources": ["where"],
                    },
                ],
            }
        ],
        "queries": [
            {
                "query_index": 0,
                "dataset_alias": "ds_sales",
                "tableId": 3,
                "dataSource": "doris_analytics",
                "query": {
                    "from": {"alias": "ds_sales", "database": ""},
                    "select": [
                        {"expr": "ds_sales.channel_name", "alias": "f_channel"},
                        {"expr": "ds_sales.order_qty", "alias": "f_order_qty", "aggregation": "SUM"},
                    ],
                    "where": {
                        "operator": "AND",
                        "conditions": [
                            {"field": "ds_sales.date_id", "operator": "between", "value": ["2026-04-01", "2026-04-30"]},
                        ],
                    },
                    "groupBy": ["f_channel"],
                    "orderBy": [],
                    "limit": 1000,
                    "offset": 0,
                },
                "filterable_fields": [
                    {
                        "column_name": "date_id",
                        "verbose_name": "日期",
                        "source_column_name": "date_id",
                    }
                ],
                "field_mappings": [
                    {
                        "source": "select",
                        "query_alias": "f_channel",
                        "query_expr": "ds_sales.channel_name",
                        "field_type": "dimension",
                        "verbose_name": "渠道",
                        "field_name": "channel_name",
                        "origin_name": "ds_sales.channel_name",
                        "global_alias": "ga_channel_name",
                    },
                    {
                        "source": "select",
                        "query_alias": "f_order_qty",
                        "query_expr": "ds_sales.order_qty",
                        "aggregation": "SUM",
                        "field_type": "metric",
                        "verbose_name": "订单量",
                        "field_name": "order_qty",
                        "origin_name": "ds_sales.order_qty",
                        "global_alias": "ga_order_qty",
                    },
                    {
                        "source": "where",
                        "query_field": "ds_sales.date_id",
                        "field_type": "dimension",
                        "verbose_name": "日期",
                        "field_name": "date_id",
                        "origin_name": "ds_sales.date_id",
                        "global_alias": "ga_date_id",
                    },
                ],
            }
        ],
    }

    monkeypatch.setattr(manager.client, "fetch_chart_bundle", lambda uuid: bundle)

    result = manager.generate_chart_doc("chart-123")
    markdown = result["markdown"]

    assert result["dataset_aliases"] == ["ds_sales"]
    assert result["dataset_count"] == 1
    assert "## 五、数据集字段信息表" in markdown
    assert "#### 5.1 字段信息总表" in markdown
    assert "| 订单量 | `metric` | `order_qty` | `ds_sales.order_qty` | `ga_order_qty` | `f_order_qty` | `SUM` | `select` |" in markdown
    assert "## 七、Query 逐条拆解" in markdown
    assert "#### 7.1 输出字段映射" in markdown
    # 7.1 拆分为两张 4 列表：表A（语义）和表B（引用）
    assert "**表A — 字段语义**" in markdown
    assert "| 订单量 | `metric` | `SUM` | `order_qty` |" in markdown
    assert "**表B — 字段引用**" in markdown
    assert "| `order_qty` | `f_order_qty` | `ds_sales.order_qty` | `ga_order_qty` |" in markdown
    # 7.2 条件字段映射格式不变
    assert "| `where` | `ds_sales.date_id` | 日期 | `dimension` | `date_id` | `ds_sales.date_id` | `ga_date_id` |" in markdown
    # 7.3 可过滤字段与数据集相同时改为引用第五章，不重复渲染完整表格
    assert "可过滤字段与数据集 `ds_sales` 完全相同，见第五章 §5.2，共 1 个字段。" in markdown


def test_generate_chart_doc_falls_back_when_field_mappings_missing(monkeypatch):
    manager = QueryManager()
    bundle = {
        "chart_uuid": "chart-456",
        "request_id": "req-2",
        "datasets": [],
        "queries": [
            {
                "query": {
                    "from": {"alias": "ds_sales", "database": ""},
                    "select": [
                        {"expr": "ds_sales.channel_name", "alias": "f_channel"},
                    ],
                    "where": {
                        "operator": "AND",
                        "conditions": [
                            {"field": "ds_sales.date_id", "operator": "eq", "value": "2026-04-29"},
                        ],
                    },
                    "groupBy": ["f_channel"],
                    "orderBy": [],
                },
                "dataSource": "doris_analytics",
                "tableId": 3,
            }
        ],
    }

    monkeypatch.setattr(manager.client, "fetch_chart_bundle", lambda uuid: bundle)

    result = manager.generate_chart_doc("chart-456")
    markdown = result["markdown"]

    assert "当前数据集没有返回 `filterable_fields` 配置。" in markdown
    # 7.1 fallback 也使用新双表格式：表A 语义列，表B 引用列
    assert "**表A — 字段语义**" in markdown
    assert "| - | `-` | `-` | `channel_name` |" in markdown
    assert "**表B — 字段引用**" in markdown
    assert "| `channel_name` | `f_channel` | `ds_sales.channel_name` | `f_channel` |" in markdown
    # 7.2 条件字段映射：fallback 时 field_name 从 origin_name 末段提取（date_id），不为 -
    assert "| `where` | `ds_sales.date_id` | - | `-` | `date_id` | `ds_sales.date_id` | `-` |" in markdown
