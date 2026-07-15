import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from opscli.calculator import cli
from opscli.calculator.draft import DRAFT_CSV_FILENAME


runner = CliRunner()


class FakeClient:
    last_do_calc_payload = None

    def dropdown_list(self):
        return {
            "code": 200,
            "data": {
                "marketplaces": [{"key": "US", "value": "美国"}],
                "platforms": [{"key": 1, "value": "亚马逊"}, {"key": 7, "value": "沃尔玛"}],
                "customs_category": [
                    {"key": 4, "value": "8544421100-USB数据线"},
                    {"key": 20, "value": "8544421100-USB连接线"},
                    {"key": 1, "value": "8507600090-移动电源"},
                ],
                "provinces": [{"key": "130000", "value": "河北省"}],
                "cities": {"130000": [{"key": "130200", "value": "唐山市"}]},
            },
        }

    def query_cost(self, payload):
        return {"code": 200, "data": {**payload, "tariff_rate": "", "calc_method": "GROSS_PROFIT"}}

    def do_calc(self, payload):
        FakeClient.last_do_calc_payload = payload
        return {"code": 200, "message": "success", "data": {"task_code": "NPC001", "sudo": "admin"}}

    def zones_warehouse_list(self, country):
        return {
            "code": 200,
            "data": {
                "country_code": country,
                "two_zone_combine": [{"key": "zone_1_3", "value": "美东+美中"}],
                "three_zone_combine": [{"key": "zone_1_2_3", "value": "美东+美中+美西"}],
                "by_warehouses": [{"key": "WH-1", "value": "深圳仓"}],
            },
        }

    def forecast_list(self, payload):
        assert payload["limit"] == 20
        assert "page_size" not in payload
        return {
            "code": 200,
            "data": {
                "list": [{"task_code": payload.get("task_code") or "NPC001", "country_code": "US", "sudo": "admin"}],
                "total": 1,
            },
        }

    def task_details(self, payload):
        assert payload["sudo"] == "admin"
        assert isinstance(payload["_t"], int)
        return {
            "code": 200,
            "data": {
                "task_code": payload["task_code"],
                "sudo": payload["sudo"],
                "task_name": "测试试算",
                "task_status_text": "已完成",
                "calc_date": "2026-07-03 10:00:00",
                "base": {
                    "country": "美国",
                    "hs_name": "测试类目",
                    "platforms": "亚马逊、沃尔玛",
                    "trial_refer": "无",
                    "currency": "USD",
                },
                "cost": {"product_price": 39.99, "gross_profit_percent": 20, "purchase_cost_with_tax": 100, "calc_method": "PRICING"},
                "trial_result": {
                    "winner": "fba",
                    "mfn": {
                        "sales_price": 39.99,
                        "sales_price_range": [35, 45],
                        "gross_profit": 7.2,
                        "gross_profit_range": [5, 9],
                        "gross_profit_percent": 18,
                        "gross_profit_percent_range": [10, 30],
                        "purchase_cost": 12,
                        "purchase_cost_percent": 25,
                        "first_leg": 1.2,
                        "first_leg_percent": 3,
                        "storage_fees": 0.8,
                        "freight": 2.3,
                        "advertising_fee": 4,
                        "marketing_fee": 1,
                        "fee": 5.9,
                        "refund": 0.6,
                        "fixed_cost": 0.4,
                        "warehouses": [{"area": "美西"}, {"area": "美东"}],
                    },
                    "fba": {
                        "sales_price": 39.99,
                        "sales_price_range": [36, 46],
                        "gross_profit": 8.8,
                        "gross_profit_percent": 22,
                        "purchase_cost": 12,
                        "purchase_cost_percent": 25,
                        "first_leg": 1.5,
                        "first_leg_percent": 4,
                        "storage_fees": 1.1,
                        "freight": 3.2,
                        "advertising_fee": 4,
                        "marketing_fee": 1,
                        "fee": 5.9,
                        "refund": 0.6,
                        "fixed_cost": 0.4,
                        "remark": {"size": "Small standard", "first": "海运"},
                    },
                },
                "allPlans": [
                    {
                        "partition_recommend": "1区",
                        "total_fee": 88.9416,
                        "schemes": [
                            {
                                "lines": "美西南",
                                "first_fee": {"value": 2.3181, "range": [2.2882, 2.3583]},
                                "storage_fees": {"value": 0.1882, "range": [0.1165, 0.3013]},
                                "freight": {"value": 86.4353, "range": [63.4573, 94.4781]},
                                "scheme_fee": 88.9416,
                                "scheme_range": [65.8620, 97.1377],
                            }
                        ],
                    }
                ],
            },
        }

    def copy_task(self, payload):
        assert payload["sudo"] == "admin"
        assert isinstance(payload["_t"], int)
        return {"code": 200, "data": {"task_code": payload["task_code"], "country_code": "US", "tariff_rate": ""}}


def test_search_category_filters_customs_category(monkeypatch):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())

    result = runner.invoke(cli.app, ["search-category", "线"])

    assert result.exit_code == 0
    assert "海关类目搜索结果" in result.output
    assert "4" in result.output
    assert "USB数据线" in result.output
    assert "USB连接线" in result.output
    assert "移动电源" not in result.output


def test_recommend_command_prints_smoke_test_parameters(monkeypatch):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())

    result = runner.invoke(cli.app, ["recommend"])

    assert result.exit_code == 0
    assert "推荐第一轮烟测参数" in result.output
    assert "亚马逊 + 沃尔玛" in result.output
    assert "--country US" in result.output
    assert "--platform 1" in result.output
    assert "--platform 7" in result.output
    assert "--hs-code-id 4" in result.output
    assert "tmp-validation" in result.output


def test_draft_command_creates_package(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "tmp-validation" / "calculator" / "calculator-draft"

    result = runner.invoke(
        cli.app,
        ["draft", "--country", "US", "--platform", "1", "--platform", "7", "--hs-code-id", "12345"],
    )

    assert result.exit_code == 0
    assert (out_dir / "draft.json").exists()
    assert (out_dir / DRAFT_CSV_FILENAME).exists()
    assert not (out_dir / "字段说明.md").exists()
    csv_text = (out_dir / DRAFT_CSV_FILENAME).read_text(encoding="utf-8-sig")
    assert "已生成试算草稿包" in result.output
    assert DRAFT_CSV_FILENAME in result.output
    assert "https://bi.xenkee.com/#/newProductCalculator" in result.output
    assert "tmp-validation" in result.output
    assert "算毛利" in csv_text
    assert "1区全部、指定分区" in csv_text
    assert "河北省" in csv_text
    assert "美东+美中" in csv_text
    assert "GROSS_PROFIT" not in csv_text
    assert "zone_1_3" not in csv_text
    assert (out_dir / ".dropdown-cache.json").exists()


def test_draft_command_keeps_first_stage_fields_when_backend_omits_them(monkeypatch, tmp_path):
    class BackendOmittingFirstStageClient(FakeClient):
        def query_cost(self, payload):
            return {"code": 200, "data": {"tariff_rate": "", "calc_method": "GROSS_PROFIT", "currency": "USD"}}

    monkeypatch.setattr(cli, "CalculatorClient", lambda: BackendOmittingFirstStageClient())
    out_dir = tmp_path / "draft-pkg"

    result = runner.invoke(
        cli.app,
        ["draft", "--country", "US", "--platform", "1", "--platform", "7", "--hs-code-id", "337", "--out", str(out_dir)],
    )

    assert result.exit_code == 0
    draft_data = json.loads((out_dir / "draft.json").read_text(encoding="utf-8"))
    assert draft_data["country_code"] == "US"
    assert draft_data["platforms"] == [1, 7]
    assert draft_data["hs_code_id"] == 337
    assert "试算站点：US" in result.output
    assert "试算平台：[1, 7]" in result.output
    assert "海关类目：337" in result.output


def test_validate_command_syncs_csv_when_directory_is_passed(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())
    out_dir = tmp_path / "draft-pkg"
    result = runner.invoke(
        cli.app,
        ["draft", "--country", "US", "--platform", "1", "--platform", "7", "--hs-code-id", "12345", "--out", str(out_dir)],
    )
    assert result.exit_code == 0

    rows = list(csv.DictReader((out_dir / DRAFT_CSV_FILENAME).read_text(encoding="utf-8-sig").splitlines()))
    values = {
        "package_length": "12",
        "package_width": "8",
        "package_height": "4",
        "box_length": "50",
        "box_width": "40",
        "box_height": "30",
        "product_gross_weight": "0.65",
        "box_gross_weight": "12",
        "box_number": "20",
        "pick_up_province": "河北省",
        "pick_up_city": "唐山市",
        "product_price": "39.99",
        "purchase_cost_with_tax": "100",
        "tax_rate_percent": "13",
        "fee_percent": "15",
        "advertising_percent": "10%",
        "marketing_percent": "5",
        "refund_percent": "3",
        "fixed_cost_percent": "2",
        "stock_qty_first_percent": "50",
        "stock_qty_second_percent": "30",
        "stock_qty_third_percent": "20",
        "checkbox_stock": "1区全部、指定分区",
        "two_zone_combine": "美东+美中",
    }
    for row in rows:
        if row["字段"] in values:
            row["请填写"] = values[row["字段"]]
    with (out_dir / DRAFT_CSV_FILENAME).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    result = runner.invoke(cli.app, ["validate", str(out_dir)])

    assert result.exit_code == 0
    assert "已读取" in result.output
    assert "校验通过" in result.output
    assert "opscli calculator submit" in result.output
    draft_data = json.loads((out_dir / "draft.json").read_text(encoding="utf-8"))
    assert draft_data["package_length"] == 12
    assert draft_data["advertising_percent"] == 10
    assert draft_data["pick_up_province"] == "130000"
    assert draft_data["pick_up_city"] == "130200"
    assert draft_data["checkbox_stock"] == ["one_zone_all", "specify_part"]
    assert draft_data["two_zone_combine"] == ["zone_1_3"]


def test_show_command_prints_chinese_summary(tmp_path):
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps({"country_code": "US", "platforms": [1], "hs_code_id": 1}, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(cli.app, ["show", str(draft)])

    assert result.exit_code == 0
    assert "新品试算草稿摘要" in result.output


def test_validate_command_fails_with_chinese_message(tmp_path):
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps({"country_code": "US", "platforms": [1], "hs_code_id": 1}, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(cli.app, ["validate", str(draft)])

    assert result.exit_code == 1
    assert "校验失败" in result.output
    assert "包装长" in result.output


def test_submit_command_syncs_csv_when_directory_is_passed(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())
    payload = {
        "country_code": "US",
        "platforms": [1, 7],
        "hs_code_id": 12345,
        "package_length": None,
        "package_width": 8,
        "package_height": 4,
        "box_length": 50,
        "box_width": 40,
        "box_height": 30,
        "product_gross_weight": 0.65,
        "box_gross_weight": 12,
        "box_number": 20,
        "pick_up_province": "130000",
        "pick_up_city": "130200",
        "calc_method": "GROSS_PROFIT",
        "product_price": 39.99,
        "purchase_cost_with_tax": 100,
        "tax_rate_percent": 13,
        "fee_percent": 15,
        "advertising_percent": 10,
        "marketing_percent": 5,
        "refund_percent": 3,
        "fixed_cost_percent": 2,
        "tariff_rate": 25,
        "stock_qty_first_percent": 50,
        "stock_qty_second_percent": 30,
        "stock_qty_third_percent": 20,
        "checkbox_stock": ["specify_part"],
        "two_zone_combine": ["zone_1_3"],
    }
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with (tmp_path / DRAFT_CSV_FILENAME).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=("字段", "请填写"))
        writer.writeheader()
        writer.writerow({"字段": "package_length", "请填写": "12"})
        writer.writerow({"字段": "pick_up_province", "请填写": "河北省"})
        writer.writerow({"字段": "pick_up_city", "请填写": "唐山市"})
        writer.writerow({"字段": "checkbox_stock", "请填写": "1区全部、指定分区"})
        writer.writerow({"字段": "two_zone_combine", "请填写": "美东+美中"})

    result = runner.invoke(cli.app, ["submit", str(tmp_path)])

    assert result.exit_code == 0
    assert "已读取" in result.output
    assert "提交成功" in result.output
    draft_data = json.loads(draft.read_text(encoding="utf-8"))
    assert draft_data["package_length"] == 12
    assert draft_data["pick_up_province"] == "130000"
    assert draft_data["pick_up_city"] == "130200"
    assert draft_data["checkbox_stock"] == ["one_zone_all", "specify_part"]
    assert draft_data["two_zone_combine"] == ["zone_1_3"]
    assert FakeClient.last_do_calc_payload["pick_up_province_code"] == "130000"
    assert FakeClient.last_do_calc_payload["one_zone_all"] == 1


def test_submit_validates_then_calls_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())
    payload = {
        "country_code": "US",
        "platforms": [1, 7],
        "hs_code_id": 12345,
        "package_length": 12,
        "package_width": 8,
        "package_height": 4,
        "box_length": 50,
        "box_width": 40,
        "box_height": 30,
        "product_gross_weight": 0.65,
        "box_gross_weight": 12,
        "box_number": 20,
        "pick_up_province": "130000",
        "pick_up_city": "130200",
        "calc_method": "GROSS_PROFIT",
        "product_price": 39.99,
        "purchase_cost_with_tax": 100,
        "tax_rate_percent": 13,
        "fee_percent": 15,
        "advertising_percent": 10,
        "marketing_percent": 5,
        "refund_percent": 3,
        "fixed_cost_percent": 2,
        "tariff_rate": 25,
        "stock_qty_first_percent": 50,
        "stock_qty_second_percent": 30,
        "stock_qty_third_percent": 20,
        "checkbox_stock": ["specify_part"],
        "two_zone_combine": ["zone_1_3"],
    }
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(cli.app, ["submit", str(draft)])

    assert result.exit_code == 0
    assert "提交成功" in result.output
    assert "NPC001" in result.output
    assert "代查标识：admin" in result.output
    assert "查看详情：opscli calculator detail --task-code NPC001 --sudo admin" in result.output
    assert "Web详情页：https://bi.xenkee.com/#/calculatorDatail?task_code=NPC001&sudo=admin" in result.output


def test_zones_command_outputs_warehouse_json(monkeypatch):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())

    result = runner.invoke(cli.app, ["zones", "--country", "US", "--json"])

    assert result.exit_code == 0
    assert "深圳仓" in result.output
    assert "WH-1" in result.output


def test_zones_command_prints_by_warehouses(monkeypatch):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())

    result = runner.invoke(cli.app, ["zones", "--country", "US"])

    assert result.exit_code == 0
    assert "站点 US 仓库分区数据" in result.output
    assert "WH-1: 深圳仓" in result.output


def test_list_command_prints_task_codes(monkeypatch):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())

    result = runner.invoke(cli.app, ["list", "--task-code", "NPC001"])

    assert result.exit_code == 0
    assert "试算任务列表" in result.output
    assert "NPC001" in result.output
    assert "sudo=admin" in result.output
    assert "opscli calculator detail --task-code NPC001 --sudo admin" in result.output
    assert "https://bi.xenkee.com/#/calculatorDatail?task_code=NPC001&sudo=admin" in result.output


def test_detail_command_prints_summary(monkeypatch):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())

    result = runner.invoke(cli.app, ["detail", "--task-code", "NPC001", "--sudo", "admin"])

    assert result.exit_code == 0
    assert "任务详情" in result.output
    assert "NPC001" in result.output
    assert "测试试算" in result.output
    assert "已完成" in result.output
    assert "美国" in result.output
    assert "费用方案" in result.output
    assert "分区推荐" in result.output
    assert "分区线路" in result.output
    assert "每PCS头程费用(CNY)" in result.output
    assert "每PCS目的仓费用(CNY)" in result.output
    assert "每PCS尾程费用(CNY)" in result.output
    assert "每PCS全程费用(CNY)" in result.output
    assert "每PCS全程平均费用(CNY)" in result.output
    assert "美西南" in result.output
    assert "88.9416" in result.output
    assert "(65.8620~97.1377)" in result.output
    assert "售价" not in result.output
    assert "毛利" not in result.output
    assert "非税采购价" not in result.output
    assert "Web详情页" not in result.output
    assert "原始JSON" not in result.output


def test_detail_command_prints_chinese_error_without_traceback(monkeypatch):
    class TimeoutClient(FakeClient):
        def task_details(self, payload):
            raise RuntimeError("Polaris 接口请求失败：The read operation timed out")

    monkeypatch.setattr(cli, "CalculatorClient", lambda: TimeoutClient())

    result = runner.invoke(cli.app, ["detail", "--task-code", "NPC001", "--sudo", "admin"])

    assert result.exit_code == 1
    assert "查询任务详情失败" in result.output
    assert "接口响应超时" in result.output
    assert "opscli calculator list --task-code NPC001 --json" in result.output
    assert "Traceback" not in result.output


def test_copy_command_creates_draft_package(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())
    out_dir = tmp_path / "copy-pkg"

    result = runner.invoke(cli.app, ["copy", "--task-code", "NPC001", "--sudo", "admin", "--out", str(out_dir)])

    assert result.exit_code == 0
    assert (out_dir / "draft.json").exists()
    assert "已复制试算任务为草稿" in result.output


def test_root_cli_registers_calculator_command():
    from opscli.cli import app as root_app

    result = runner.invoke(root_app, ["calculator", "--help"])

    assert result.exit_code == 0
    assert "新品计算器" in result.output


def test_root_cli_registers_feedback_submit_command():
    from opscli.cli import app as root_app

    result = runner.invoke(root_app, ["feedback", "submit", "--help"])

    assert result.exit_code == 0
    assert "--type" in result.output
    assert "--title" in result.output
    assert "--content" in result.output


def test_root_cli_registers_feedtask_command():
    from opscli.cli import app as root_app

    result = runner.invoke(root_app, ["feedtask", "--help"])

    assert result.exit_code == 0
    assert "create" in result.output
    assert "status" in result.output
