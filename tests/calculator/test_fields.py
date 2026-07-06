from opscli.calculator.fields import FIELD_BY_KEY, get_field_label, render_field_reference_markdown


def test_core_fields_have_chinese_labels_and_examples():
    assert get_field_label("package_length") == "包装长"
    assert get_field_label("purchase_cost_with_tax") == "含税采购价"
    assert get_field_label("stock_qty_first_percent") == "30天仓租分摊"
    assert get_field_label("unknown_field") == "unknown_field"

    spec = FIELD_BY_KEY["product_price"]
    assert spec.group == "成本费用"
    assert spec.unit == "站点币种"
    assert spec.example == "39.99"


def test_field_reference_markdown_contains_required_columns():
    text = render_field_reference_markdown()

    assert text.startswith("# 字段说明")
    assert "| JSON 字段 | 中文名称 | 单位 | 是否必填 | 示例 | 说明 |" in text
    assert "| package_length | 包装长 | CM | 是 | 12.5 | 单个 SKU 包装长度 |" in text
    assert "| pick_up_province | 提货省份 | - | 是 | 130000 | 提货省份编码，对应下拉选项 key |" in text
    assert "| pick_up_city | 提货城市 | - | 是 | 130200 | 提货城市编码，对应下拉选项 key |" in text
    assert "| gross_profit_percent | 目标毛利率 | % | 条件必填 | 30 | 算定价时填写 |" in text
    assert "| two_zone_combine | 指定二区 | - | 条件必填 | [\"zone_1_3\"] | US/CA 站点选择 1区全部或指定分区时必填 |" in text
    assert "## 产品信息" in text
    assert "## 成本费用" in text
    assert "## 备货设置" in text
