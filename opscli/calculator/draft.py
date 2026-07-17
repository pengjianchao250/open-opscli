"""新品计算器草稿包与本地校验逻辑。"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from opscli.calculator.fields import FIELD_BY_KEY, FIELD_SPECS, FieldSpec
from opscli.calculator.models import read_json_file, write_json_file

DRAFT_JSON_FILENAME = "draft.json"
DRAFT_CSV_FILENAME = "填写表格.csv"
LEGACY_DRAFT_CSV_FILENAME = "填写表格-旧版.csv"
OPTIONS_CACHE_FILENAME = ".dropdown-cache.json"
WEB_CALCULATOR_URL = "https://bi.xenkee.com/#/newProductCalculator"
# Amazon.sg 官方 FBA 费率资料，用于生成单件商品包装参考说明。
_AMAZON_SG_FBA_FEES_URL = "https://m.media-amazon.com/images/G/65/SG3P/FBA_fulfilment_fees_for_Amazon.sg_orders.pdf"
# Amazon 美国站 FBA 入库箱规公告，用于生成外箱合规上限提示。
_AMAZON_US_FBA_BOX_URL = "https://sellercentral.amazon.com/seller-forums/discussions/t/dae82165-50b2-4b52-99d9-a7e7db80caec"
DRAFT_CSV_COLUMNS = ("分组", "是否必填", "字段", "中文说明", "当前值", "请填写", "单位/格式", "示例", "备注")

_NUMERIC_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
_PICKUP_CODE_RE = re.compile(r"^\d+$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_NUMERIC_EXCLUDE_KEYS = {"pick_up_province", "pick_up_city", "baiyi_warehouse_ids", "two_zone_combine", "three_zone_combine"}
_ARRAY_FIELD_KEYS = {"platforms", "checkbox_stock", "two_zone_combine", "three_zone_combine", "baiyi_warehouse_ids"}
_STRING_FIELD_KEYS = {"country_code", "department", "reference", "reference_value", "pick_up_province", "pick_up_city", "calc_method", "task_name"}
_BOOL_TRUE_VALUES = {"1", "true", "yes", "y", "是"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "n", "否"}
# 新草稿缺少试算方案或分区时，沿用页面默认选择。
_DEFAULT_CALC_METHOD = "GROSS_PROFIT"
_DEFAULT_CHECKBOX_STOCK = ["one_zone_all", "specify_part"]
_DEFAULT_TWO_ZONE_COMBINE = ["zone_1_2"]
# 当前只计算仓配费用，利润试算输入统一使用非零占位值，避免后端拒绝计算。
_DEFAULT_COST_FIELD_KEYS = {
    "product_price",
    "gross_profit_percent",
    "purchase_cost_with_tax",
    "purchase_cost",
    "tax_rate_percent",
    "fee_percent",
    "advertising_percent",
    "marketing_percent",
    "refund_percent",
    "fixed_cost_percent",
    "tariff_rate",
}
_BUILTIN_OPTIONS = {
    "calc_method": [("GROSS_PROFIT", "算毛利"), ("PRICING", "算定价")],
    "checkbox_stock": [("one_zone_all", "1区全部"), ("specify_part", "指定分区"), ("specify_stock", "指定仓库")],
}
_OPTION_PREVIEW_LIMIT = 18


@dataclass(frozen=True)
class ValidationIssue:
    """单条草稿校验问题。"""

    field: str
    message: str
    group: str


@dataclass(frozen=True)
class DraftOption:
    """CSV 中文显示值和后端字段值之间的映射。"""

    key: Any
    value: str
    parent_key: str | None = None


def _is_empty(value: Any) -> bool:
    """判断字段是否为空，空字符串、None 和空列表都视为空。"""
    return value is None or value == "" or value == []


def _to_decimal(value: Any) -> Decimal | None:
    """将数值转换为 Decimal，无法转换时返回 None。"""
    if isinstance(value, bool) or _is_empty(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _has_at_most_two_decimals(value: Any) -> bool:
    """判断数值是否最多两位小数。"""
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return False
    return abs(decimal_value.as_tuple().exponent) <= 2


def normalize_draft_data(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """归一化后端返回数据，模拟前端初始化行为。"""
    normalized = copy.deepcopy(data)
    notes: list[str] = []

    for key, value in list(normalized.items()):
        if value == "":
            normalized[key] = None
        elif key not in _NUMERIC_EXCLUDE_KEYS and isinstance(value, str) and _NUMERIC_RE.match(value):
            number = float(value) if "." in value else int(value)
            normalized[key] = number

    for key in _DEFAULT_COST_FIELD_KEYS:
        normalized[key] = 1

    if _is_empty(normalized.get("calc_method")):
        normalized["calc_method"] = _DEFAULT_CALC_METHOD
        notes.append("试算方案未返回，已默认选择算毛利。")

    if _is_empty(normalized.get("checkbox_stock")):
        normalized["checkbox_stock"] = list(_DEFAULT_CHECKBOX_STOCK)
        notes.append("备货区域未返回，已默认选择 1区全部、指定分区。")

    country_code = str(normalized.get("country_code") or "").upper()
    if country_code in {"US", "CA"} and _is_empty(normalized.get("two_zone_combine")):
        normalized["two_zone_combine"] = list(_DEFAULT_TWO_ZONE_COMBINE)
        notes.append("指定二区未返回，已默认选择美东+美西。")

    bi_message = normalized.get("bi_message")
    if bi_message:
        normalized["reference"] = "NONE"
        normalized["reference_value"] = None
        notes.append(str(bi_message))

    return normalized, notes


def _append_required_issue(issues: list[ValidationIssue], key: str) -> None:
    """追加必填字段缺失问题。"""
    field = FIELD_BY_KEY[key]
    unit = "" if field.unit == "-" else f"，单位 {field.unit}"
    issues.append(ValidationIssue(key, f"{field.label}：必填{unit}，例如 {field.example}。", field.group))


def _validate_number(issues: list[ValidationIssue], key: str, value: Any, positive: bool, percent: bool) -> None:
    """校验数值格式、小数位和正数要求。"""
    if _is_empty(value):
        return
    field = FIELD_BY_KEY[key]
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        issues.append(ValidationIssue(key, f"{field.label}：必须填写数字，例如 {field.example}。", field.group))
        return
    if not _has_at_most_two_decimals(value):
        issues.append(ValidationIssue(key, f"{field.label}：最多只能保留两位小数。", field.group))
    if positive and decimal_value <= 0:
        issues.append(ValidationIssue(key, f"{field.label}：必须大于 0。", field.group))
    if percent and decimal_value < 0:
        issues.append(ValidationIssue(key, f"{field.label}：不能小于 0。", field.group))


def _validate_pickup_code(issues: list[ValidationIssue], key: str, value: Any) -> None:
    """校验提货地址编码，前端下拉使用字符串编码作为值。"""
    if _is_empty(value):
        return
    field = FIELD_BY_KEY[key]
    code_type = "省份" if key == "pick_up_province" else "城市"
    if not isinstance(value, str) or not _PICKUP_CODE_RE.match(value):
        issues.append(ValidationIssue(key, f"{field.label}：必须填写{code_type}编码字符串，例如 {field.example}。", field.group))


def validate_draft_data(data: dict[str, Any]) -> list[ValidationIssue]:
    """校验草稿数据，返回中文校验问题列表。"""
    issues: list[ValidationIssue] = []

    for field in FIELD_SPECS:
        value = data.get(field.key)
        if field.required and _is_empty(value):
            _append_required_issue(issues, field.key)
            continue
        if field.key in {"pick_up_province", "pick_up_city"}:
            _validate_pickup_code(issues, field.key, value)
        if field.positive or field.percent:
            _validate_number(issues, field.key, value, field.positive, field.percent)

    stock_values = [
        _to_decimal(data.get("stock_qty_first_percent")) or Decimal("0"),
        _to_decimal(data.get("stock_qty_second_percent")) or Decimal("0"),
        _to_decimal(data.get("stock_qty_third_percent")) or Decimal("0"),
    ]
    stock_total = sum(stock_values)
    if stock_total != Decimal("100"):
        display_total = int(stock_total) if stock_total == stock_total.to_integral_value() else stock_total
        issues.append(
            ValidationIssue(
                "stock_qty_first_percent",
                f"仓租分摊比例错误：30天、60天、90天三项之和必须等于 100。当前为 {display_total}。",
                "备货设置",
            )
        )

    checkbox_stock = data.get("checkbox_stock") or []
    country_code = str(data.get("country_code") or "").upper()
    if country_code in {"US", "CA"} and {"one_zone_all", "specify_part"}.intersection(checkbox_stock) and _is_empty(data.get("two_zone_combine")):
        issues.append(ValidationIssue("two_zone_combine", "指定二区：US/CA 站点选择 1区全部或指定分区时必须填写。", "备货设置"))
    if "specify_stock" in checkbox_stock and _is_empty(data.get("baiyi_warehouse_ids")):
        issues.append(ValidationIssue("baiyi_warehouse_ids", "指定仓库：勾选指定仓库时必须选择至少一个仓库。", "备货设置"))

    return issues


def build_missing_items_markdown(data: dict[str, Any]) -> str:
    """生成缺失项 Markdown。"""
    issues = validate_draft_data(data)
    missing_keys = [issue.field for issue in issues if "必填" in issue.message or "必须填写" in issue.message]
    lines = ["# 缺失项", "", "请补充以下字段后再提交。", ""]
    if not missing_keys:
        lines.append("当前没有必填缺失项。")
        return "\n".join(lines).rstrip() + "\n"

    current_group = None
    for key in missing_keys:
        field = FIELD_BY_KEY.get(key)
        if field is None:
            continue
        if field.group != current_group:
            if current_group is not None:
                lines.append("")
            current_group = field.group
            lines.extend([f"## {field.group}", "", "| 中文名称 | JSON 字段 | 单位 | 示例 |", "|---|---|---|---|"])
        lines.append(f"| {field.label} | {field.key} | {field.unit} | {field.example} |")
    return "\n".join(lines).rstrip() + "\n"


def _option_value_text(value: Any) -> str:
    """归一化选项值用于宽松匹配。"""
    return str(value).strip()


def _same_option_value(left: Any, right: Any) -> bool:
    """比较 CSV 输入和下拉 key/value，英文 key 忽略大小写。"""
    left_text = _option_value_text(left)
    right_text = _option_value_text(right)
    return left_text == right_text or left_text.casefold() == right_text.casefold()


def _option_from_item(item: Any, parent_key: str | None = None) -> DraftOption | None:
    """将后端下拉项对象转换为内部选项。"""
    if not isinstance(item, dict):
        return None
    key = item.get("key")
    if key is None:
        key = item.get("id")
    if key is None:
        key = item.get("value")
    value = item.get("value")
    if value is None:
        value = item.get("label") or item.get("name") or item.get("title") or key
    if key is None or _is_empty(value):
        return None
    return DraftOption(key=key, value=str(value), parent_key=parent_key)


def _as_option_list(raw_options: Any, parent_key: str | None = None) -> list[DraftOption]:
    """将常见 key/value 下拉数组转换为选项列表。"""
    options: list[DraftOption] = []
    if isinstance(raw_options, dict):
        option = _option_from_item(raw_options, parent_key)
        if option is not None:
            options.append(option)
        return options
    if not isinstance(raw_options, list):
        return options
    for item in raw_options:
        option = _option_from_item(item, parent_key)
        if option is not None:
            options.append(option)
    return options


def _extract_nested_options(raw_options: Any) -> list[DraftOption]:
    """从嵌套下拉结构中提取选项。"""
    if isinstance(raw_options, dict):
        option = _option_from_item(raw_options)
        if option is not None:
            return [option]
        options: list[DraftOption] = []
        for parent_key, children in raw_options.items():
            options.extend(_as_option_list(children, str(parent_key)))
        return options
    return _as_option_list(raw_options)


def _add_options(field_options: dict[str, list[DraftOption]], field_key: str, options: list[DraftOption]) -> None:
    """追加字段选项，按 key/value/parent 去重。"""
    if not options:
        return
    current = field_options.setdefault(field_key, [])
    seen = {(_option_value_text(option.key), option.value, option.parent_key) for option in current}
    for option in options:
        marker = (_option_value_text(option.key), option.value, option.parent_key)
        if marker in seen:
            continue
        current.append(option)
        seen.add(marker)


def build_field_options(option_cache: dict[str, Any] | None = None) -> dict[str, list[DraftOption]]:
    """根据内置枚举和后端下拉快照构造字段选项映射。"""
    field_options: dict[str, list[DraftOption]] = {}
    for field_key, options in _BUILTIN_OPTIONS.items():
        _add_options(field_options, field_key, [DraftOption(key, value) for key, value in options])

    cache = option_cache or {}
    dropdown = cache.get("dropdown_list") if isinstance(cache.get("dropdown_list"), dict) else {}
    zones = cache.get("zones_warehouse_list") if isinstance(cache.get("zones_warehouse_list"), dict) else {}

    if isinstance(dropdown, dict):
        _add_options(field_options, "country_code", _as_option_list(dropdown.get("marketplaces")))
        _add_options(field_options, "platforms", _as_option_list(dropdown.get("platforms")))
        _add_options(field_options, "hs_code_id", _as_option_list(dropdown.get("customs_category")))
        _add_options(field_options, "department", _as_option_list(dropdown.get("departments")))
        _add_options(field_options, "reference", _as_option_list(dropdown.get("references")))
        _add_options(field_options, "pick_up_province", _as_option_list(dropdown.get("provinces")))
        cities = dropdown.get("cities")
        if isinstance(cities, dict):
            for province_key, city_options in cities.items():
                _add_options(field_options, "pick_up_city", _as_option_list(city_options, str(province_key)))
        else:
            _add_options(field_options, "pick_up_city", _extract_nested_options(cities))

    if isinstance(zones, dict):
        _add_options(field_options, "two_zone_combine", _as_option_list(zones.get("two_zone_combine")))
        _add_options(field_options, "three_zone_combine", _as_option_list(zones.get("three_zone_combine")))
        _add_options(field_options, "baiyi_warehouse_ids", _as_option_list(zones.get("by_warehouses")))

    return field_options


def write_options_cache(package_dir: str | Path, option_cache: dict[str, Any] | None) -> Path | None:
    """将下拉快照写入草稿包，供离线校验或接口失败时兜底。"""
    if not option_cache:
        return None
    cache_path = Path(package_dir) / OPTIONS_CACHE_FILENAME
    cache_path.write_text(json.dumps(option_cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cache_path


def read_options_cache(package_dir: str | Path) -> dict[str, Any] | None:
    """读取草稿包内的下拉快照，不存在时返回 None。"""
    cache_path = Path(package_dir) / OPTIONS_CACHE_FILENAME
    if not cache_path.exists():
        return None
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _field_has_options(field_key: str, field_options: dict[str, list[DraftOption]] | None) -> bool:
    """判断字段是否存在可用下拉选项。"""
    return bool(field_options and field_options.get(field_key))


def _format_option_item(field_key: str, value: Any, field_options: dict[str, list[DraftOption]] | None) -> str:
    """将单个后端 key/code 转成 CSV 中文显示值。"""
    if _is_empty(value):
        return ""
    for option in (field_options or {}).get(field_key, []):
        if _same_option_value(option.key, value):
            return option.value
    return str(value)


def _format_csv_value(value: Any, field_key: str, field_options: dict[str, list[DraftOption]] | None = None) -> str:
    """将草稿值转成 CSV 中适合用户查看的文本。"""
    if _is_empty(value):
        return ""
    if isinstance(value, list | tuple):
        return "、".join(_format_option_item(field_key, item, field_options) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return _format_option_item(field_key, value, field_options)


def _option_labels(field_key: str, field_options: dict[str, list[DraftOption]] | None, limit: int = _OPTION_PREVIEW_LIMIT) -> list[str]:
    """返回字段下拉中文值预览。"""
    labels = [option.value for option in (field_options or {}).get(field_key, []) if option.value]
    return labels[:limit]


def _csv_required_text(field_key: str, issue_by_field: dict[str, str]) -> str:
    """生成 CSV 必填状态，当前有问题的字段直接标出待处理。"""
    field = FIELD_BY_KEY[field_key]
    if field.conditional_required:
        text = "条件必填"
    else:
        text = "是" if field.required else "否"
    return f"{text}（待处理）" if field_key in issue_by_field else text


def _csv_unit_text(field_key: str, field_options: dict[str, list[DraftOption]] | None) -> str:
    """生成 CSV 单位或填写格式提示。"""
    if _field_has_options(field_key, field_options):
        if field_key in _ARRAY_FIELD_KEYS:
            return "下拉中文名称，多个值用顿号或逗号分隔"
        return "下拉中文名称"
    field = FIELD_BY_KEY[field_key]
    return "" if field.unit == "-" else field.unit


def _csv_example(field_key: str, field_options: dict[str, list[DraftOption]] | None) -> str:
    """生成 CSV 示例，优先使用中文下拉值。"""
    if _field_has_options(field_key, field_options):
        if field_key == "checkbox_stock":
            return "1区全部、指定分区"
        labels = _option_labels(field_key, field_options, limit=2)
        if labels:
            return "、".join(labels) if field_key in _ARRAY_FIELD_KEYS else labels[0]
    return FIELD_BY_KEY[field_key].example


def _csv_option_remark(field_key: str, field_options: dict[str, list[DraftOption]] | None) -> str | None:
    """生成下拉选项填写备注。"""
    if not _field_has_options(field_key, field_options):
        return None
    parts = ["请填写中文名称，CLI 会自动转换为接口 key/code；高级用户也可填写原 key/code"]
    if field_key == "pick_up_city":
        parts.append("城市会按已填写的提货省份匹配")
    labels = _option_labels(field_key, field_options)
    if labels:
        suffix = "等" if len((field_options or {}).get(field_key, [])) > len(labels) else ""
        parts.append(f"可选：{'、'.join(labels)}{suffix}")
    return "；".join(parts)


def _csv_remark(field_key: str, issue_by_field: dict[str, str], field_options: dict[str, list[DraftOption]] | None = None) -> str:
    """合并字段说明、填写提示和当前校验问题。"""
    field = FIELD_BY_KEY[field_key]
    option_remark = _csv_option_remark(field_key, field_options)
    parts = [option_remark or field.description]
    if field.conditional_required:
        parts.append(field.conditional_required)
    if field.percent:
        parts.append("百分比可填 10 或 10%")
    if field_key in _ARRAY_FIELD_KEYS and not option_remark:
        parts.append("多个值用英文逗号分隔")
    if field_key in issue_by_field:
        parts.append(f"当前问题：{issue_by_field[field_key]}")
    return "；".join(parts)


def _build_draft_csv_text(
    data: dict[str, Any],
    field_specs: tuple[FieldSpec, ...],
    notice: str,
    field_options: dict[str, list[DraftOption]] | None = None,
) -> str:
    """按指定字段生成 CSV 表格文本。"""
    issues = validate_draft_data(data)
    issue_by_field = {issue.field: issue.message for issue in issues}
    indexed_fields = list(enumerate(field_specs))
    indexed_fields.sort(key=lambda item: (0 if item[1].key in issue_by_field else 1, item[0]))

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=DRAFT_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "分组": "说明",
            "中文说明": notice,
            "备注": WEB_CALCULATOR_URL,
        }
    )
    for _, field in indexed_fields:
        writer.writerow(
            {
                "分组": field.group,
                "是否必填": _csv_required_text(field.key, issue_by_field),
                "字段": field.key,
                "中文说明": field.label,
                "当前值": _format_csv_value(data.get(field.key), field.key, field_options),
                "请填写": "",
                "单位/格式": _csv_unit_text(field.key, field_options),
                "示例": _csv_example(field.key, field_options),
                "备注": _csv_remark(field.key, issue_by_field, field_options),
            }
        )
    return output.getvalue()


def build_draft_csv_text(data: dict[str, Any], field_options: dict[str, list[DraftOption]] | None = None) -> str:
    """生成不含成本费用的新版业务填写表格。"""
    # 成本字段仍保留在 draft.json 提交给后端，但不再暴露给业务用户填写。
    visible_fields = tuple(field for field in FIELD_SPECS if field.group != "成本费用")
    return _build_draft_csv_text(
        data,
        visible_fields,
        "当前值仅来自接口或用户已确认数据，不会把示例自动写入；包装与箱规请按实物填写",
        field_options,
    )


def build_legacy_draft_csv_text(data: dict[str, Any], field_options: dict[str, list[DraftOption]] | None = None) -> str:
    """生成保留完整字段但已弃用的旧版填写表格。"""
    return _build_draft_csv_text(
        data,
        FIELD_SPECS,
        "旧版填写表格已弃用，仅保留历史完整字段；校验和提交不会读取本文件",
        field_options,
    )


def write_draft_csv(package_dir: str | Path, data: dict[str, Any], field_options: dict[str, list[DraftOption]] | None = None) -> Path:
    """写入新版和已弃用旧版 CSV，返回新版文件路径。"""
    csv_path = Path(package_dir) / DRAFT_CSV_FILENAME
    csv_path.write_text(build_draft_csv_text(data, field_options), encoding="utf-8-sig")
    legacy_csv_path = Path(package_dir) / LEGACY_DRAFT_CSV_FILENAME
    legacy_csv_path.write_text(build_legacy_draft_csv_text(data, field_options), encoding="utf-8-sig")
    return csv_path


def _parse_decimal_number(text: str, row_number: int, field_key: str) -> int | float:
    """解析 CSV 中的数字，并在失败时返回带行号的中文错误。"""
    try:
        decimal_value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        field = FIELD_BY_KEY[field_key]
        raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行 `{field_key}` 应填写数字，例如 {field.example}。") from exc
    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)
    return float(decimal_value)


def _parse_bool_value(text: str, row_number: int, field_key: str) -> bool:
    """解析 CSV 中的布尔值，兼容中文是/否。"""
    normalized = text.lower()
    if normalized in _BOOL_TRUE_VALUES:
        return True
    if normalized in _BOOL_FALSE_VALUES:
        return False
    raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行 `{field_key}` 应填写 是/否、true/false 或 1/0。")


def _option_preview(field_key: str, field_options: dict[str, list[DraftOption]] | None) -> str:
    """生成错误提示中的中文选项预览。"""
    labels = _option_labels(field_key, field_options, limit=8)
    if not labels:
        return ""
    suffix = "等" if len((field_options or {}).get(field_key, [])) > len(labels) else ""
    return f"可选项：{'、'.join(labels)}{suffix}。"


def _looks_like_raw_option(field_key: str, text: str) -> bool:
    """判断输入是否像高级用户填写的原始 key/code。"""
    if field_key in {"platforms", "hs_code_id"}:
        return bool(_NUMERIC_RE.match(text))
    if field_key in {"pick_up_province", "pick_up_city"}:
        return bool(_PICKUP_CODE_RE.match(text))
    if field_key in {"two_zone_combine", "three_zone_combine"}:
        return text.startswith("zone_")
    if field_key in _BUILTIN_OPTIONS:
        return any(_same_option_value(key, text) for key, _ in _BUILTIN_OPTIONS[field_key])
    return not _CJK_RE.search(text)


def _coerce_raw_option_value(field_key: str, text: str) -> Any:
    """将高级用户填写的原始 key/code 转成字段期望类型。"""
    if field_key in {"platforms", "hs_code_id"} and _NUMERIC_RE.match(text):
        return int(text) if Decimal(text) == Decimal(text).to_integral_value() else float(text)
    return text


def _match_options(field_key: str, text: str, field_options: dict[str, list[DraftOption]] | None, context_data: dict[str, Any]) -> list[DraftOption]:
    """按中文值或原始 key 匹配下拉选项。"""
    options = (field_options or {}).get(field_key, [])
    matches = [option for option in options if _same_option_value(option.key, text) or _same_option_value(option.value, text)]
    if field_key == "pick_up_city" and matches:
        province = context_data.get("pick_up_province")
        if province:
            scoped = [option for option in matches if option.parent_key in (None, str(province))]
            if scoped:
                return scoped
    return matches


def _parse_option_value(
    field_key: str,
    value: Any,
    row_number: int,
    field_options: dict[str, list[DraftOption]] | None,
    context_data: dict[str, Any],
) -> Any:
    """将 CSV 下拉中文值解析成后端 key/code。"""
    text = _option_value_text(value)
    matches = _match_options(field_key, text, field_options, context_data)
    if matches:
        distinct_keys = {_option_value_text(option.key) for option in matches}
        if len(distinct_keys) > 1:
            field = FIELD_BY_KEY[field_key]
            raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行 `{field_key}` 的 `{text}` 对应多个{field.label}，请补充上级选项或直接填写编码。")
        return matches[0].key
    if _looks_like_raw_option(field_key, text):
        return _coerce_raw_option_value(field_key, text)
    field = FIELD_BY_KEY[field_key]
    preview = _option_preview(field_key, field_options)
    raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行 `{field_key}` 的 `{text}` 不在{field.label}下拉选项中。{preview}")


def _parse_array_value(
    text: str,
    row_number: int,
    field_key: str,
    field_options: dict[str, list[DraftOption]] | None = None,
    context_data: dict[str, Any] | None = None,
) -> list[Any]:
    """解析 CSV 中用逗号分隔或 JSON 数组表示的多选字段。"""
    if text == "[]":
        return []
    if text.startswith("["):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行 `{field_key}` 数组格式错误。") from exc
        if not isinstance(value, list):
            raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行 `{field_key}` 必须填写数组。")
        values = value
    else:
        values = [item.strip().strip('"\'') for item in re.split(r"[，,、;；\n]+", text) if item.strip()]

    if _field_has_options(field_key, field_options):
        context = context_data or {}
        return [_parse_option_value(field_key, item, row_number, field_options, context) for item in values]
    if field_key == "platforms":
        try:
            return [int(item) for item in values]
        except ValueError as exc:
            raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行 `platforms` 平台值必须是数字 ID。") from exc
    return values


def _parse_csv_value(
    field_key: str,
    raw_value: str,
    current_value: Any,
    row_number: int,
    field_options: dict[str, list[DraftOption]] | None = None,
    context_data: dict[str, Any] | None = None,
) -> Any:
    """按字段类型解析 CSV 的“请填写”值。"""
    value = raw_value.strip()
    field = FIELD_BY_KEY[field_key]
    if field_key in _ARRAY_FIELD_KEYS or isinstance(current_value, list):
        return _parse_array_value(value, row_number, field_key, field_options, context_data)
    if _field_has_options(field_key, field_options):
        return _parse_option_value(field_key, value, row_number, field_options, context_data or {})
    if isinstance(current_value, bool):
        return _parse_bool_value(value, row_number, field_key)
    if field.percent and value.endswith("%"):
        value = value[:-1].strip()
    if field_key in _STRING_FIELD_KEYS:
        return value
    if field.positive or field.percent or field_key.endswith("_id") or (isinstance(current_value, int | float) and not isinstance(current_value, bool)):
        return _parse_decimal_number(value, row_number, field_key)
    return value


def read_draft_csv_updates(
    csv_path: str | Path,
    current_data: dict[str, Any],
    field_options: dict[str, list[DraftOption]] | None = None,
) -> dict[str, Any]:
    """读取 CSV 的“请填写”列，只返回用户实际填写的字段更新。"""
    path = Path(csv_path)
    context_data = copy.deepcopy(current_data)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = [name.strip() for name in (reader.fieldnames or []) if name]
        missing_columns = [name for name in ("字段", "请填写") if name not in fieldnames]
        if missing_columns:
            raise ValueError(f"{DRAFT_CSV_FILENAME} 缺少必要列：{'、'.join(missing_columns)}。请不要删除表头。")

        updates: dict[str, Any] = {}
        for row_number, row in enumerate(reader, start=2):
            # Excel/WPS 可能在行尾留下额外空列，DictReader 会把它们放到 None 键下；这些列不参与解析。
            normalized_row = {key.strip(): (value or "").strip() for key, value in row.items() if key is not None}
            field_key = normalized_row.get("字段", "")
            raw_value = normalized_row.get("请填写", "")
            if not raw_value:
                continue
            if not field_key:
                raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行缺少字段名。")
            if field_key not in FIELD_BY_KEY:
                raise ValueError(f"{DRAFT_CSV_FILENAME} 第 {row_number} 行字段 `{field_key}` 不支持，请检查是否改错字段列。")
            parsed_value = _parse_csv_value(field_key, raw_value, context_data.get(field_key), row_number, field_options, context_data)
            updates[field_key] = parsed_value
            context_data[field_key] = parsed_value
    return updates


def resolve_draft_json_path(path: str | Path) -> Path:
    """兼容草稿目录和 draft.json 文件两种输入。"""
    source = Path(path)
    return source / DRAFT_JSON_FILENAME if source.is_dir() else source


def load_draft_data(
    path: str | Path,
    sync_csv: bool = False,
    field_options: dict[str, list[DraftOption]] | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    """读取草稿；传入目录且启用 sync_csv 时，先同步 CSV 到 draft.json。"""
    source = Path(path)
    draft_path = resolve_draft_json_path(source)
    data = read_json_file(draft_path)
    synced = False

    if sync_csv and source.is_dir():
        csv_path = draft_path.parent / DRAFT_CSV_FILENAME
        if csv_path.exists():
            updates = read_draft_csv_updates(csv_path, data, field_options)
            if updates:
                data.update(updates)
                write_json_file(draft_path, data)
                synced = True
            # 每次目录校验/提交后刷新 CSV：已填写值进入“当前值”，剩余问题继续标注。
            write_draft_csv(draft_path.parent, data, field_options)
    return draft_path, data, synced


def build_usage_markdown(draft_path: str, notes: list[str] | None = None) -> str:
    """生成包含包装参考的草稿使用说明。

    Args:
        draft_path: 草稿目录或 draft.json 路径。
        notes: 需要附加到说明末尾的系统提示。

    Returns:
        可直接写入使用说明文件的 Markdown 文本。
    """
    draft_path_obj = Path(draft_path)
    package_path = draft_path_obj.parent if draft_path_obj.name == DRAFT_JSON_FILENAME else draft_path_obj
    lines = [
        "# 使用说明",
        "",
        "## 推荐填写方式",
        "",
        f"1. 打开 `{DRAFT_CSV_FILENAME}`。",
        "2. 只填写“请填写”这一列；省份、城市、备货区域、分区和仓库可直接填中文名称，CLI 会自动转换为接口 key/code。",
        f"3. 保存后执行 `opscli calculator validate {package_path}`。",
        f"4. 校验通过后执行 `opscli calculator submit {package_path}`。",
        f"5. `{LEGACY_DRAFT_CSV_FILENAME}` 已弃用，仅用于保留历史完整字段，不参与校验和提交。",
        "",
        "## 单件 SKU 包装参考",
        "",
        "以下是 Amazon.sg 官方商品示例，只用于帮助理解尺寸量级，不会自动写入；FBA 费用应以目标站点规则和实测数据为准：",
        "",
        "- 按实物填写（推荐）。",
        "- SD 卡：3.2 × 2.4 × 0.2 cm / 0.03 kg。",
        "- 图书：24 × 16.2 × 3.5 cm / 0.15 kg。",
        "- 电子玩具：37 × 15.4 × 7 cm / 0.49 kg。",
        f"- 官方资料：{_AMAZON_SG_FBA_FEES_URL}",
        "",
        "## FBA 入库外箱参考",
        "",
        "- 按实际装箱填写（推荐）。",
        "- 美国 FBA 普通入库箱合规上限：91.44 × 63.5 × 63.5 cm / 22.68 kg；这是上限提示，不会自动写入。",
        "- 单箱数量没有通用默认值，必须按供应商实际装箱确认。",
        f"- 官方公告：{_AMAZON_US_FBA_BOX_URL}",
        "",
        "单件 SKU 包装用于 FBA 配送费用，入库外箱用于头程运输费用，两者不能混用。",
        "",
        "## 不想本地填写？",
        "",
        "如果你不想在本地编辑 CSV/JSON，也可以直接使用网页端新品计算器：",
        WEB_CALCULATOR_URL,
        "",
        "## 高级用户",
        "",
        f"同目录下的 `{DRAFT_JSON_FILENAME}` 仍会保留给 CLI 提交和自动化场景；普通用户不建议手动替换整个 JSON。",
        "",
    ]
    if notes:
        lines.extend(["## 系统提示", ""])
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_value(value: Any, empty_text: str = "未填写") -> str:
    """格式化摘要字段值。"""
    return empty_text if _is_empty(value) else str(value)


def build_summary_text(data: dict[str, Any]) -> str:
    """生成草稿中文摘要。"""
    issues = validate_draft_data(data)
    lines = [
        "新品试算草稿摘要",
        "",
        "基础信息：",
        f"- 试算站点：{_format_value(data.get('country_code'))}",
        f"- 试算平台：{_format_value(data.get('platforms'))}",
        f"- 海关类目：{_format_value(data.get('hs_code_id'))}",
        "",
        "产品信息：",
        f"- 包装尺寸：{_format_value(data.get('package_length'))} / {_format_value(data.get('package_width'))} / {_format_value(data.get('package_height'))} CM",
        f"- 外箱尺寸：{_format_value(data.get('box_length'))} / {_format_value(data.get('box_width'))} / {_format_value(data.get('box_height'))} CM",
        f"- SKU毛重：{_format_value(data.get('product_gross_weight'))} KG",
        "",
        "成本费用：",
        f"- 试算方案：{_format_value(data.get('calc_method'))}",
        f"- 商品售价：{_format_value(data.get('product_price'))} 站点币种",
        f"- 目标毛利率：{_format_value(data.get('gross_profit_percent'))} %",
        f"- 含税采购价：{_format_value(data.get('purchase_cost_with_tax'))} CNY",
        "",
        "备货设置：",
        f"- 仓租分摊：{_format_value(data.get('stock_qty_first_percent'))} / {_format_value(data.get('stock_qty_second_percent'))} / {_format_value(data.get('stock_qty_third_percent'))} %",
        f"- 当前校验问题：{len(issues)} 个",
    ]
    return "\n".join(lines)


def prepare_submit_payload(data: dict[str, Any]) -> dict[str, Any]:
    """生成提交 payload，提交前处理与前端一致的派生字段。"""
    payload = copy.deepcopy(data)
    # 兼容已生成的旧草稿：提交前覆盖成本字段，避免历史 0 值导致后端计算失败。
    for key in _DEFAULT_COST_FIELD_KEYS:
        payload[key] = 1
    if payload.get("pick_up_province"):
        payload["pick_up_province_code"] = payload["pick_up_province"]
    if payload.get("pick_up_city"):
        payload["pick_up_city_code"] = payload["pick_up_city"]

    checkbox_stock = payload.get("checkbox_stock") or []
    payload["one_zone_all"] = 1 if "one_zone_all" in checkbox_stock else 0
    if "specify_stock" not in checkbox_stock:
        payload["baiyi_warehouse_ids"] = []

    checkbox_special = payload.get("checkbox_special") or []
    payload["tyre_flag"] = 1 if "tyre_flag" in checkbox_special else 0
    payload["snow_species_flag"] = 1 if "snow_species_flag" in checkbox_special else 0
    payload["electricity_flag"] = 1 if payload.get("battery_power_value") else 0
    return payload


def create_draft_package(
    raw_data: dict[str, Any],
    out_dir: str | Path,
    notes: list[str] | None = None,
    option_cache: dict[str, Any] | None = None,
) -> Path:
    """创建草稿包目录，并返回 draft.json 路径。"""
    normalized, normalize_notes = normalize_draft_data(raw_data)
    all_notes = [*(notes or []), *normalize_notes]
    package_dir = Path(out_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    field_options = build_field_options(option_cache)
    draft_path = package_dir / DRAFT_JSON_FILENAME
    write_json_file(draft_path, normalized)
    write_options_cache(package_dir, option_cache)
    write_draft_csv(package_dir, normalized, field_options)
    (package_dir / "使用说明.md").write_text(build_usage_markdown(str(draft_path), all_notes), encoding="utf-8")
    return draft_path
