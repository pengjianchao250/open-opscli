"""新品计算器字段字典。

本模块集中维护后端 JSON 字段与运营同学可理解的中文名称、单位、示例和说明。
字段字典会同时用于草稿说明、缺失项提示、摘要展示和校验错误。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    """单个试算字段的中文说明。"""

    key: str
    label: str
    group: str
    unit: str
    example: str
    description: str
    required: bool = False
    positive: bool = False
    percent: bool = False
    conditional_required: str | None = None


GROUP_ORDER: tuple[str, ...] = ("基本信息", "产品信息", "成本费用", "备货设置", "其他设置")

FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("country_code", "试算站点", "基本信息", "-", "US", "试算国家或站点", True),
    FieldSpec("platforms", "试算平台", "基本信息", "-", "[1, 7]", "支持多平台", True),
    FieldSpec("hs_code_id", "海关类目", "基本信息", "-", "12345", "从下拉数据中选择", True),
    FieldSpec("department", "部门", "基本信息", "-", "1001", "试算参考部门"),
    FieldSpec("reference", "试算参考", "基本信息", "-", "NONE", "参考类型"),
    FieldSpec("reference_value", "参考值", "基本信息", "-", "B0XXXX", "参考产品、类目或其他参考值"),
    FieldSpec("package_length", "包装长", "产品信息", "CM", "12.5", "单个 SKU 包装长度", True, True),
    FieldSpec("package_width", "包装宽", "产品信息", "CM", "8.2", "单个 SKU 包装宽度", True, True),
    FieldSpec("package_height", "包装高", "产品信息", "CM", "4", "单个 SKU 包装高度", True, True),
    FieldSpec("box_length", "外箱长", "产品信息", "CM", "50", "外箱长度", True, True),
    FieldSpec("box_width", "外箱宽", "产品信息", "CM", "40", "外箱宽度", True, True),
    FieldSpec("box_height", "外箱高", "产品信息", "CM", "30", "外箱高度", True, True),
    FieldSpec("product_gross_weight", "SKU毛重", "产品信息", "KG", "0.65", "单个 SKU 毛重", True, True),
    FieldSpec("box_gross_weight", "外箱毛重", "产品信息", "KG", "12", "单箱毛重", True, True),
    FieldSpec("box_number", "单箱数量", "产品信息", "件", "20", "一个外箱中的产品数量", True, True),
    FieldSpec("pick_up_province", "提货省份", "产品信息", "-", "130000", "提货省份编码，对应下拉选项 key", True),
    FieldSpec("pick_up_city", "提货城市", "产品信息", "-", "130200", "提货城市编码，对应下拉选项 key", True),
    FieldSpec("battery_power_value", "带电功率", "产品信息", "WH", "10.5", "带电产品填写", False, True),
    FieldSpec("calc_method", "试算方案", "成本费用", "-", "GROSS_PROFIT", "GROSS_PROFIT 算毛利，PRICING 算定价", True),
    FieldSpec("product_price", "商品售价", "成本费用", "站点币种", "1", "无需填写，默认 1"),
    FieldSpec("gross_profit_percent", "目标毛利率", "成本费用", "%", "1", "无需填写，默认 1"),
    FieldSpec("purchase_cost_with_tax", "含税采购价", "成本费用", "CNY", "1", "无需填写，默认 1"),
    FieldSpec("tax_rate_percent", "税率", "成本费用", "%", "1", "无需填写，默认 1"),
    FieldSpec("purchase_cost", "非税采购价", "成本费用", "CNY", "1", "无需填写，默认 1"),
    FieldSpec("fee_percent", "平台佣金比", "成本费用", "%", "1", "无需填写，默认 1"),
    FieldSpec("advertising_percent", "站内广告", "成本费用", "%", "1", "无需填写，默认 1"),
    FieldSpec("marketing_percent", "站外营销", "成本费用", "%", "1", "无需填写，默认 1"),
    FieldSpec("refund_percent", "退款", "成本费用", "%", "1", "无需填写，默认 1"),
    FieldSpec("fixed_cost_percent", "固定成本", "成本费用", "%", "1", "无需填写，默认 1"),
    FieldSpec("tariff_rate", "关税率", "成本费用", "%", "1", "无需填写，默认 1"),
    FieldSpec("rate", "汇率", "成本费用", "-", "7.2", "系统返回汇率"),
    FieldSpec("stock_qty_first_percent", "30天仓租分摊", "备货设置", "%", "50", "三项之和必须为 100", True, False, True),
    FieldSpec("stock_qty_second_percent", "60天仓租分摊", "备货设置", "%", "30", "三项之和必须为 100", True, False, True),
    FieldSpec("stock_qty_third_percent", "90天仓租分摊", "备货设置", "%", "20", "三项之和必须为 100", True, False, True),
    FieldSpec("first_order_qty", "首单数量", "备货设置", "件", "100", "可选，填写时必须大于 0", False, True),
    FieldSpec("checkbox_stock", "备货区域", "备货设置", "-", "[\"specify_part\"]", "1区全部、指定分区或指定仓库", True),
    FieldSpec(
        "two_zone_combine",
        "指定二区",
        "备货设置",
        "-",
        "[\"zone_1_2\"]",
        "默认美东+美西",
        False,
        False,
        False,
        "US/CA 站点选择 1区全部或指定分区时必填",
    ),
    FieldSpec("three_zone_combine", "指定三区", "备货设置", "-", "[]", "US 站适用"),
    FieldSpec("baiyi_warehouse_ids", "指定仓库", "备货设置", "-", "[]", "勾选指定仓库时必填"),
    FieldSpec("task_name", "试算名称", "其他设置", "-", "新品试算", "最长 25 字"),
)

FIELD_BY_KEY: dict[str, FieldSpec] = {field.key: field for field in FIELD_SPECS}


def get_field_label(key: str) -> str:
    """返回字段中文名，未知字段返回原字段名。"""
    return FIELD_BY_KEY[key].label if key in FIELD_BY_KEY else key


def _required_text(field: FieldSpec) -> str:
    """生成字段必填说明，用于 Markdown 表格。"""
    if field.conditional_required:
        return "条件必填"
    return "是" if field.required else "否"


def render_field_reference_markdown() -> str:
    """渲染面向运营同学的字段说明 Markdown。"""
    lines = ["# 字段说明", "", "本文件说明 `draft.json` 中常见字段的中文含义、单位、是否必填和示例。", ""]
    for group in GROUP_ORDER:
        group_fields = [field for field in FIELD_SPECS if field.group == group]
        if not group_fields:
            continue
        lines.extend([
            f"## {group}",
            "",
            "| JSON 字段 | 中文名称 | 单位 | 是否必填 | 示例 | 说明 |",
            "|---|---|---|---|---|---|",
        ])
        for field in group_fields:
            lines.append(
                f"| {field.key} | {field.label} | {field.unit} | {_required_text(field)} | {field.example} | {field.description} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
