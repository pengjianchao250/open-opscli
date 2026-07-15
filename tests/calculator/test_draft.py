import csv
import json

from opscli.calculator.draft import (
    DRAFT_CSV_FILENAME,
    OPTIONS_CACHE_FILENAME,
    WEB_CALCULATOR_URL,
    build_draft_csv_text,
    build_field_options,
    build_missing_items_markdown,
    build_summary_text,
    build_usage_markdown,
    create_draft_package,
    load_draft_data,
    normalize_draft_data,
    prepare_submit_payload,
    read_draft_csv_updates,
    read_options_cache,
    validate_draft_data,
)
from opscli.calculator.models import build_query_payload, read_json_file, write_json_file


def _valid_draft():
    return {
        "country_code": "US",
        "platforms": [1, 7],
        "hs_code_id": 12345,
        "package_length": 12.5,
        "package_width": 8.2,
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
        "gross_profit_percent": None,
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
        "checkbox_stock": ["one_zone_all", "specify_part"],
        "two_zone_combine": ["zone_1_3"],
        "baiyi_warehouse_ids": ["WH-1"],
    }


def _option_cache():
    return {
        "dropdown_list": {
            "marketplaces": [{"key": "US", "value": "美国"}],
            "platforms": [{"key": 1, "value": "亚马逊"}, {"key": 7, "value": "沃尔玛"}],
            "customs_category": [{"key": 12345, "value": "8544421100-USB数据线"}],
            "provinces": [{"key": "130000", "value": "河北省"}],
            "cities": {"130000": [{"key": "130200", "value": "唐山市"}]},
        },
        "zones_warehouse_list": {
            "two_zone_combine": [{"key": "zone_1_3", "value": "美东+美中"}],
            "three_zone_combine": [{"key": "zone_1_2_3", "value": "美东+美中+美西"}],
            "by_warehouses": [{"key": "WH-1", "value": "美西洛杉矶仓"}],
        },
    }


def test_normalize_draft_data_converts_numeric_strings_and_default_tariff():
    data, notes = normalize_draft_data({
        "package_length": "12.50",
        "pick_up_province": "01",
        "tariff_rate": "",
        "reference": "CUSTOM",
        "reference_value": "ABC",
        "bi_message": "未找到参考数据",
    })

    assert data["package_length"] == 12.5
    assert data["pick_up_province"] == "01"
    assert data["tariff_rate"] == 25
    assert data["reference"] == "NONE"
    assert data["reference_value"] is None
    assert "关税率未返回，已默认填 25。" in notes
    assert "备货区域未返回，已默认选择 1区全部、指定分区。" in notes
    assert data["checkbox_stock"] == ["one_zone_all", "specify_part"]
    assert "未找到参考数据" in "\n".join(notes)


def test_validate_draft_data_reports_chinese_required_and_stock_errors():
    data = _valid_draft()
    data["package_length"] = None
    data["stock_qty_third_percent"] = 10

    issues = validate_draft_data(data)
    messages = [issue.message for issue in issues]

    assert "包装长：必填，单位 CM，例如 12.5。" in messages
    assert "仓租分摊比例错误：30天、60天、90天三项之和必须等于 100。当前为 90。" in messages


def test_validate_draft_data_requires_price_by_calc_method():
    gross_profit_data = _valid_draft()
    gross_profit_data["product_price"] = None
    assert "商品售价：当前试算方案为算毛利，必须填写。" in [issue.message for issue in validate_draft_data(gross_profit_data)]

    pricing_data = _valid_draft()
    pricing_data["calc_method"] = "PRICING"
    pricing_data["product_price"] = None
    pricing_data["gross_profit_percent"] = None
    assert "目标毛利率：当前试算方案为算定价，必须填写。" in [issue.message for issue in validate_draft_data(pricing_data)]


def test_validate_draft_data_requires_two_zone_combine_for_us_stock_parts():
    data = _valid_draft()
    data["country_code"] = "US"
    data["checkbox_stock"] = ["one_zone_all"]
    data["two_zone_combine"] = []

    messages = [issue.message for issue in validate_draft_data(data)]

    assert "指定二区：US/CA 站点选择 1区全部或指定分区时必须填写。" in messages


def test_validate_draft_data_requires_pickup_address_codes_as_strings():
    data = _valid_draft()
    data["pick_up_province"] = "广东省"
    data["pick_up_city"] = 130200

    messages = [issue.message for issue in validate_draft_data(data)]

    assert "提货省份：必须填写省份编码字符串，例如 130000。" in messages
    assert "提货城市：必须填写城市编码字符串，例如 130200。" in messages


def test_validate_draft_data_accepts_valid_payload():
    assert validate_draft_data(_valid_draft()) == []


def test_prepare_submit_payload_clears_warehouse_when_not_specified():
    payload = prepare_submit_payload(_valid_draft())
    assert payload["baiyi_warehouse_ids"] == []

    data = _valid_draft()
    data["checkbox_stock"] = ["specify_stock"]
    payload = prepare_submit_payload(data)
    assert payload["baiyi_warehouse_ids"] == ["WH-1"]


def test_prepare_submit_payload_derives_pickup_address_code_fields():
    payload = prepare_submit_payload(_valid_draft())

    assert payload["pick_up_province"] == "130000"
    assert payload["pick_up_city"] == "130200"
    assert payload["pick_up_province_code"] == "130000"
    assert payload["pick_up_city_code"] == "130200"


def test_markdown_and_summary_use_chinese_labels():
    data = _valid_draft()
    data["package_length"] = None

    missing = build_missing_items_markdown(data)
    assert missing.startswith("# 缺失项")
    assert "| 包装长 | package_length | CM | 12.5 |" in missing

    summary = build_summary_text(data)
    assert "新品试算草稿摘要" in summary
    assert "包装尺寸：未填写 / 8.2 / 4 CM" in summary
    assert "含税采购价：100 CNY" in summary


def test_json_helpers_read_and_write(tmp_path):
    path = tmp_path / "payload.json"
    write_json_file(path, {"country_code": "US", "platforms": [1, 7]})

    assert json.loads(path.read_text(encoding="utf-8"))["country_code"] == "US"
    assert read_json_file(path) == {"country_code": "US", "platforms": [1, 7]}


def test_build_query_payload_prefers_payload_file_values():
    payload = build_query_payload(
        country="DE",
        platforms=[9],
        hs_code_id=999,
        department="D2",
        reference="NONE",
        reference_value=None,
        payload={"country_code": "US", "platforms": [1, 7], "hs_code_id": 12345},
    )

    assert payload == {
        "country_code": "US",
        "platforms": [1, 7],
        "hs_code_id": 12345,
        "department": None,
        "reference": "NONE",
        "reference_value": None,
    }


def test_build_query_payload_from_cli_options():
    payload = build_query_payload(
        country="US",
        platforms=[1, 7],
        hs_code_id=12345,
        department=None,
        reference="NONE",
        reference_value=None,
        payload=None,
    )

    assert payload["country_code"] == "US"
    assert payload["platforms"] == [1, 7]
    assert payload["hs_code_id"] == 12345


def test_build_draft_csv_text_combines_missing_fields_and_web_fallback():
    data = _valid_draft()
    data["package_length"] = None

    text = build_draft_csv_text(data)

    assert text.startswith("分组,是否必填,字段,中文说明,当前值,请填写,单位/格式,示例,备注")
    assert "package_length,包装长" in text
    assert "是（待处理）" in text
    assert "当前问题：包装长：必填，单位 CM，例如 12.5。" in text
    assert WEB_CALCULATOR_URL in text


def test_build_draft_csv_text_displays_chinese_options():
    text = build_draft_csv_text(_valid_draft(), build_field_options(_option_cache()))

    assert "美国" in text
    assert "亚马逊、沃尔玛" in text
    assert "河北省" in text
    assert "唐山市" in text
    assert "算毛利" in text
    assert "1区全部、指定分区" in text
    assert "美东+美中" in text
    assert "美西洛杉矶仓" in text
    assert "GROSS_PROFIT" not in text
    assert "zone_1_3" not in text


def test_read_draft_csv_updates_parses_user_filled_column(tmp_path):
    csv_path = tmp_path / DRAFT_CSV_FILENAME
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=("字段", "请填写"))
        writer.writeheader()
        writer.writerow({"字段": "package_length", "请填写": "12.5"})
        writer.writerow({"字段": "advertising_percent", "请填写": "10%"})
        writer.writerow({"字段": "two_zone_combine", "请填写": "zone_1_3, zone_4_6"})

    updates = read_draft_csv_updates(csv_path, _valid_draft())

    assert updates["package_length"] == 12.5
    assert updates["advertising_percent"] == 10
    assert updates["two_zone_combine"] == ["zone_1_3", "zone_4_6"]


def test_read_draft_csv_updates_maps_chinese_options_to_backend_keys(tmp_path):
    csv_path = tmp_path / DRAFT_CSV_FILENAME
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=("字段", "请填写"))
        writer.writeheader()
        writer.writerow({"字段": "pick_up_province", "请填写": "河北省"})
        writer.writerow({"字段": "pick_up_city", "请填写": "唐山市"})
        writer.writerow({"字段": "calc_method", "请填写": "算毛利"})
        writer.writerow({"字段": "checkbox_stock", "请填写": "1区全部、指定分区"})
        writer.writerow({"字段": "two_zone_combine", "请填写": "美东+美中"})
        writer.writerow({"字段": "baiyi_warehouse_ids", "请填写": "美西洛杉矶仓"})

    updates = read_draft_csv_updates(csv_path, _valid_draft(), build_field_options(_option_cache()))

    assert updates["pick_up_province"] == "130000"
    assert updates["pick_up_city"] == "130200"
    assert updates["calc_method"] == "GROSS_PROFIT"
    assert updates["checkbox_stock"] == ["one_zone_all", "specify_part"]
    assert updates["two_zone_combine"] == ["zone_1_3"]
    assert updates["baiyi_warehouse_ids"] == ["WH-1"]


def test_load_draft_data_syncs_csv_when_directory_is_passed(tmp_path):
    package_dir = tmp_path / "draft-pkg"
    draft_path = create_draft_package(_valid_draft(), package_dir)
    rows = list(csv.DictReader((package_dir / DRAFT_CSV_FILENAME).read_text(encoding="utf-8-sig").splitlines()))
    for row in rows:
        if row["字段"] == "package_length":
            row["请填写"] = "15"
    with (package_dir / DRAFT_CSV_FILENAME).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    resolved_path, data, synced = load_draft_data(package_dir, sync_csv=True)

    assert resolved_path == draft_path
    assert synced is True
    assert data["package_length"] == 15
    assert read_json_file(draft_path)["package_length"] == 15


def test_load_draft_data_syncs_chinese_options_with_field_options(tmp_path):
    package_dir = tmp_path / "draft-pkg"
    draft_path = create_draft_package(_valid_draft(), package_dir, option_cache=_option_cache())
    rows = list(csv.DictReader((package_dir / DRAFT_CSV_FILENAME).read_text(encoding="utf-8-sig").splitlines()))
    for row in rows:
        if row["字段"] == "pick_up_province":
            row["请填写"] = "河北省"
        if row["字段"] == "pick_up_city":
            row["请填写"] = "唐山市"
        if row["字段"] == "two_zone_combine":
            row["请填写"] = "美东+美中"
    with (package_dir / DRAFT_CSV_FILENAME).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    resolved_path, data, synced = load_draft_data(package_dir, sync_csv=True, field_options=build_field_options(_option_cache()))

    assert resolved_path == draft_path
    assert synced is True
    assert data["pick_up_province"] == "130000"
    assert data["pick_up_city"] == "130200"
    assert data["two_zone_combine"] == ["zone_1_3"]
    assert read_json_file(draft_path)["pick_up_city"] == "130200"


def test_create_draft_package_writes_csv_usage_and_json(tmp_path):
    draft_path = create_draft_package(_valid_draft(), tmp_path / "draft-pkg", notes=["测试提示"], option_cache=_option_cache())

    assert draft_path.name == "draft.json"
    assert draft_path.exists()
    assert (tmp_path / "draft-pkg" / DRAFT_CSV_FILENAME).exists()
    assert (tmp_path / "draft-pkg" / OPTIONS_CACHE_FILENAME).exists()
    assert (tmp_path / "draft-pkg" / "使用说明.md").exists()
    assert not (tmp_path / "draft-pkg" / "字段说明.md").exists()
    assert not (tmp_path / "draft-pkg" / "缺失项.md").exists()
    usage = (tmp_path / "draft-pkg" / "使用说明.md").read_text(encoding="utf-8")
    csv_text = (tmp_path / "draft-pkg" / DRAFT_CSV_FILENAME).read_text(encoding="utf-8-sig")
    assert "测试提示" in usage
    assert "可直接填中文名称" in usage
    assert DRAFT_CSV_FILENAME in usage
    assert WEB_CALCULATOR_URL in usage
    assert read_options_cache(tmp_path / "draft-pkg") == _option_cache()
    assert "河北省" in csv_text
    assert "zone_1_3" not in csv_text


def test_usage_markdown_separates_sku_package_and_fba_inbound_box_references():
    text = build_usage_markdown("tmp-validation/calculator/example/draft.json")

    assert "单件 SKU 包装参考" in text
    assert "SD 卡：3.2 × 2.4 × 0.2 cm / 0.03 kg" in text
    assert "图书：24 × 16.2 × 3.5 cm / 0.15 kg" in text
    assert "电子玩具：37 × 15.4 × 7 cm / 0.49 kg" in text
    assert "FBA 入库外箱参考" in text
    assert "91.44 × 63.5 × 63.5 cm / 22.68 kg" in text
    assert "不会自动写入" in text
    assert "单箱数量没有通用默认值" in text
