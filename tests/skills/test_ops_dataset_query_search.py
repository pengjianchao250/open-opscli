import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path("/Users/mask/python3/opscli/opscli/skills/templates/ops-dataset-query/scripts")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_search_rows_prefers_field_name_match():
    core = _load_module("dataset_fields_core_test", SCRIPT_DIR / "core.py")

    rows = [
        {
            "dataset_alias": "sales_order_d",
            "dataset_name": "销售订单",
            "field_name": "order_cost",
            "verbose_name": "订单成本",
            "keywords": "成本 order cost",
            "description": "成本字段",
        },
        {
            "dataset_alias": "sales_order_d",
            "dataset_name": "销售订单",
            "field_name": "supplier_price",
            "verbose_name": "供应商价格",
            "keywords": "订单成本参考值",
            "description": "价格字段",
        },
    ]

    result = core.search_rows(rows, "order_cost", limit=5)

    assert len(result) == 2
    assert result[0]["field_name"] == "order_cost"


def test_search_rows_supports_global_alias_match():
    core = _load_module("dataset_fields_core_alias_test", SCRIPT_DIR / "core.py")

    rows = [
        {
            "dataset_alias": "sales_order_d",
            "dataset_name": "销售订单",
            "field_name": "order_cost",
            "verbose_name": "订单成本",
            "global_alias": "ga_order_cost",
            "keywords": "成本 order cost",
            "description": "成本字段",
        },
        {
            "dataset_alias": "sales_order_d",
            "dataset_name": "销售订单",
            "field_name": "supplier_price",
            "verbose_name": "供应商价格",
            "global_alias": "ga_supplier_price",
            "keywords": "订单成本参考值",
            "description": "价格字段",
        },
    ]

    result = core.search_rows(rows, "ga_order_cost", limit=5)

    assert len(result) == 2
    assert result[0]["global_alias"] == "ga_order_cost"


def test_filter_rows_by_dataset():
    core = _load_module("dataset_fields_core_filter_test", SCRIPT_DIR / "core.py")

    rows = [
        {"dataset_alias": "sales_order_d", "field_name": "order_cost"},
        {"dataset_alias": "inventory_d", "field_name": "stock_qty"},
    ]

    result = core.filter_rows_by_dataset(rows, "sales_order_d")

    assert result == [{"dataset_alias": "sales_order_d", "field_name": "order_cost"}]


def test_search_cli_supports_dataset_and_limit(tmp_path, monkeypatch, capsys):
    core = _load_module("core", SCRIPT_DIR / "core.py")
    _load_module("dataset_fields_search_test", SCRIPT_DIR / "search.py")
    search = sys.modules["dataset_fields_search_test"]

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "dataset_fields.csv").write_text(
        "\n".join(
            [
                "dataset_alias,dataset_name,field_name,verbose_name,global_alias,keywords,description",
                "sales_order_d,销售订单,order_cost,订单成本,ga_order_cost,cost 订单成本,成本字段",
                "inventory_d,库存,stock_qty,库存数量,ga_stock_qty,stock qty,库存字段",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(search, "Path", _build_fake_path_class(tmp_path))
    monkeypatch.setattr(sys, "argv", ["search.py", "cost", "--dataset", "sales_order_d", "-n", "1"])

    search.main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert len(payload) == 1
    assert payload[0]["dataset_alias"] == "sales_order_d"
    assert payload[0]["field_name"] == "order_cost"
    assert "inventory_d" not in output


def _build_fake_path_class(base_dir: Path):
    class FakePath(type(Path())):
        @classmethod
        def resolve(cls):
            return base_dir / "scripts" / "search.py"

    return FakePath


def test_updater_check_reports_remote_version(tmp_path, monkeypatch, capsys):
    updater_script = _load_module("dataset_fields_updater_test", SCRIPT_DIR / "updater.py")

    skill_root = tmp_path
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text('{"name":"ops-dataset-query","version":"v1.0.0"}', encoding="utf-8")

    monkeypatch.setattr(updater_script, "Path", _build_fake_path_class(skill_root))

    class DummyUpdater:
        def fetch_manifest(self, skill_name: str):
            assert skill_name == "ops-dataset-query"
            return {"version": "v1.1.0"}

        def compare_versions(self, current: str, remote: str) -> int:
            return -1 if current < remote else 0

    monkeypatch.setattr(updater_script, "SkillsUpdater", lambda: DummyUpdater())
    monkeypatch.setattr(sys, "argv", ["updater.py", "--check"])

    updater_script.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["data"]["current_version"] == "v1.0.0"
    assert payload["data"]["remote_version"] == "v1.1.0"
    assert payload["data"]["update_available"] is True


def test_updater_upgrade_supports_force(tmp_path, monkeypatch, capsys):
    updater_script = _load_module("dataset_fields_updater_upgrade_test", SCRIPT_DIR / "updater.py")

    skill_root = tmp_path
    data_dir = skill_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text('{"name":"ops-dataset-query","version":"v1.0.0"}', encoding="utf-8")

    monkeypatch.setattr(updater_script, "Path", _build_fake_path_class(skill_root))

    class DummyResult:
        def to_dict(self):
            return {
                "name": "ops-dataset-query",
                "from_version": "v1.0.0",
                "to_version": "v1.0.0",
                "runtime": "claude-code",
                "updated": True,
                "target_dir": str(skill_root),
            }

    class DummyUpdater:
        called_with_force = None

        def upgrade_ops_dataset_query(self, record, force: bool = False):
            self.called_with_force = force
            return DummyResult()

    dummy_updater = DummyUpdater()
    monkeypatch.setattr(updater_script, "SkillsUpdater", lambda: dummy_updater)
    monkeypatch.setattr(sys, "argv", ["updater.py", "--force"])

    updater_script.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["data"]["updated"] is True
    assert dummy_updater.called_with_force is True


def test_query_script_builds_metadata_command(monkeypatch):
    query_script = _load_module("dataset_fields_query_test", SCRIPT_DIR / "query.py")

    monkeypatch.setattr(query_script, "build_opscli_prefix", lambda: ["opscli"])

    class Args:
        command = "metadata"
        dataset = "ds_xxx"
        table_id = 1103
        skills_dir = "/tmp/skills"
        pretty = True

    command = query_script.build_command(Args())

    assert command == [
        "opscli",
        "query",
        "metadata",
        "--dataset",
        "ds_xxx",
        "--table-id",
        "1103",
        "--skills-dir",
        "/tmp/skills",
        "--pretty",
    ]


def test_query_script_builds_run_command(monkeypatch):
    query_script = _load_module("dataset_fields_query_run_test", SCRIPT_DIR / "query.py")

    monkeypatch.setattr(query_script, "build_opscli_prefix", lambda: ["opscli"])

    class Args:
        command = "run"
        payload = "/tmp/query.json"
        pretty = False

    command = query_script.build_command(Args())

    assert command == [
        "opscli",
        "query",
        "run",
        "--payload",
        "/tmp/query.json",
    ]


def test_query_script_builds_catalog_command(monkeypatch):
    query_script = _load_module("dataset_fields_query_catalog_test", SCRIPT_DIR / "query.py")

    monkeypatch.setattr(query_script, "build_opscli_prefix", lambda: ["opscli"])

    class Args:
        command = "catalog"
        skills_dir = "/tmp/skills"
        pretty = True

    command = query_script.build_command(Args())

    assert command == [
        "opscli",
        "query",
        "catalog",
        "--skills-dir",
        "/tmp/skills",
        "--pretty",
    ]


def test_query_script_builds_simple_command(monkeypatch):
    query_script = _load_module("dataset_fields_query_simple_test", SCRIPT_DIR / "query.py")

    monkeypatch.setattr(query_script, "build_opscli_prefix", lambda: ["opscli"])

    class Args:
        command = "simple"
        table_id = 1
        payload = None
        payload_json = '{"dimensions":[]}'
        output = "/tmp/simple.json"
        run = True
        pretty = True

    command = query_script.build_command(Args())

    assert command == [
        "opscli",
        "query",
        "simple",
        "--table-id",
        "1",
        "--json",
        '{"dimensions":[]}',
        "--output",
        "/tmp/simple.json",
        "--run",
        "--pretty",
    ]


def test_query_script_rejects_simple_payload_and_json(monkeypatch, capsys):
    query_script = _load_module("dataset_fields_query_simple_conflict_test", SCRIPT_DIR / "query.py")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query.py",
            "simple",
            "--table-id",
            "1",
            "--payload",
            "/tmp/simple.json",
            "--json",
            "{}",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        query_script.main()

    payload = json.loads(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert payload["success"] is False
    assert "--payload 和 --json" in payload["error"]


def test_query_script_builds_chart_commands(monkeypatch):
    query_script = _load_module("dataset_fields_query_chart_test", SCRIPT_DIR / "query.py")

    monkeypatch.setattr(query_script, "build_opscli_prefix", lambda: ["opscli"])

    class ChartArgs:
        command = "chart"
        uuid = "chart-123"
        run = True
        dry_run = True
        pretty = True

    class ChartDocArgs:
        command = "chart-doc"
        uuid = "chart-123"
        output = "/tmp/chart.md"
        pretty = False

    assert query_script.build_command(ChartArgs()) == [
        "opscli",
        "query",
        "chart",
        "--uuid",
        "chart-123",
        "--run",
        "--dry-run",
        "--pretty",
    ]
    assert query_script.build_command(ChartDocArgs()) == [
        "opscli",
        "query",
        "chart-doc",
        "--uuid",
        "chart-123",
        "--output",
        "/tmp/chart.md",
    ]


def test_query_script_builds_build_command(monkeypatch):
    query_script = _load_module("dataset_fields_query_build_test", SCRIPT_DIR / "query.py")

    monkeypatch.setattr(query_script, "build_opscli_prefix", lambda: ["opscli"])

    class Args:
        command = "build"
        dataset = "ds_xxx"
        table_id = 1103
        dimension = ["date_id", "country_name:f_dim001"]
        metric = ["price:sum:f_metric001"]
        where = ['country_name|in|["美国"]']
        where_json = '{"operator":"AND","conditions":[]}'
        where_file = None
        order_by = ["f_metric001:desc"]
        limit = 5
        offset = 10
        skills_dir = "/tmp/skills"
        output = "/tmp/query.json"
        run = True
        pretty = True

    command = query_script.build_command(Args())

    assert command == [
        "opscli",
        "query",
        "build",
        "--dataset",
        "ds_xxx",
        "--table-id",
        "1103",
        "--dimension",
        "date_id",
        "--dimension",
        "country_name:f_dim001",
        "--metric",
        "price:sum:f_metric001",
        "--where",
        'country_name|in|["美国"]',
        "--order-by",
        "f_metric001:desc",
        "--where-json",
        '{"operator":"AND","conditions":[]}',
        "--skills-dir",
        "/tmp/skills",
        "--output",
        "/tmp/query.json",
        "--limit",
        "5",
        "--offset",
        "10",
        "--run",
        "--pretty",
    ]


def test_query_script_emits_error_when_opscli_missing(monkeypatch, capsys):
    query_script = _load_module("dataset_fields_query_missing_test", SCRIPT_DIR / "query.py")

    monkeypatch.setattr(query_script.os, "getenv", lambda name: None)
    monkeypatch.setattr(query_script.shutil, "which", lambda name: None)
    monkeypatch.setattr(query_script.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["query.py", "metadata", "--dataset", "ds_xxx"])

    with pytest.raises(SystemExit) as exc_info:
        query_script.main()

    payload = json.loads(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert payload["success"] is False
    assert "未找到 opscli" in payload["error"]


def test_updater_mcp_marks_placeholder_data_unhealthy(tmp_path):
    updater_mcp = _load_module("dataset_fields_updater_mcp_test", SCRIPT_DIR / "updater_mcp.py")

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        '{"name":"ops-dataset-query","version":"v0.0.1","data_state":"placeholder"}',
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text("table_id,dataset_alias\n", encoding="utf-8")
    (data_dir / "dataset_fields.csv").write_text("dataset_alias,field_name\n", encoding="utf-8")
    (data_dir / "dataset_catalog.json").write_text(
        '{"version":"v0.0.0","intent_count":0,"intents":[],"query_strategy":{}}',
        encoding="utf-8",
    )
    (data_dir / "query_metadata.json").write_text('{"datasets":[],"fields":[]}', encoding="utf-8")

    status = updater_mcp.check_local_data(data_dir)

    assert status["healthy"] is False
    assert status["data_state"] == "placeholder_or_empty"
    assert status["summary"]["datasets_csv_count"] == 0
    assert status["summary"]["fields_csv_count"] == 0


def test_updater_mcp_marks_populated_data_healthy(tmp_path):
    updater_mcp = _load_module("dataset_fields_updater_mcp_ready_test", SCRIPT_DIR / "updater_mcp.py")

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        '{"name":"ops-dataset-query","version":"v1.0.0"}',
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text("table_id,dataset_alias\n1,sales_order_d\n", encoding="utf-8")
    (data_dir / "dataset_fields.csv").write_text(
        "dataset_alias,field_name\nsales_order_d,order_cost\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_catalog.json").write_text(
        '{"version":"v1.0.0","intents":[{"dataset_alias":"sales_order_d"}]}',
        encoding="utf-8",
    )
    (data_dir / "query_metadata.json").write_text(
        '{"datasets":[{"table_id":1}],"fields":[{"table_id":1,"field_name":"order_cost"}]}',
        encoding="utf-8",
    )

    status = updater_mcp.check_local_data(data_dir)

    assert status["healthy"] is True
    assert status["data_state"] == "ready"
    assert status["summary"]["metadata_field_count"] == 1
