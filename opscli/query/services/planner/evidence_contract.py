#!/usr/bin/env python3
"""把查询返回 JSON 拍平为受限的证据与披露规划器（evidence_contract_v1）。

从 skill `opscli/skills/templates/ops-dataset-query/scripts/evidence_contract.py`
迁入（去 CLI 壳，只保留纯函数）。CLI 入口（`argparse`/`main`/stdin 读取）不迁入——
kernel 版直接以 Python 函数调用形式被 `entry.py:run_flow` 接入，不再需要 CLI 壳。

真实形状适配（在原样迁入之后的一次算法修正）：迁入的源实现只认造出来的返回形状，
面对 `QueryManager.run_query_template()` 的真实返回体
（`{"success", "data": [行...], "meta": {"rowCount", "totalCount", "currency", ...}, "error": null}`）
会同时踩四个坑，本模块已逐个修正：

1. 结果行（`data[i].price` 等）既不含 PRIORITY_MARKERS 也不以 `[-1]` 结尾，
   `required_evidence` 恒为空 → 见 `_row_prefix` / `_collect_evidence`（逐行完整、行数截断）；
2. `"error": null` 表示"没有错误"，却被当成缺失证据，`missing_paths` 恒为 `["error"]`
   并误加"空值不等于零"披露 → 见 `_is_missing_evidence`；
3. 零行判定只读 `row_count`/`total_count`，真实 meta 是驼峰 `rowCount`/`totalCount`
   → 见 `_count_value` 与 PRIORITY_MARKERS 的驼峰项；
4. 币种未声明只认 `currency_metadata_status`（真实返回没有该键）→ 见 `_currency_evidence`。

输入：一次查询返回 JSON（对象）。
输出：required_evidence（结论必须引用的证据路径与原值）、
required_disclosures_zh（必须披露的中文事项）、
forbidden_inferences_zh（禁止做出的推断）。
结果分析阶段只允许基于本规划器组织结论，防止对返回数据的过度推断。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Sequence


CONTRACT = "evidence_contract_v1"
MAX_EVIDENCE = 24
MAX_OUTPUT_BYTES = 8000
# 证据路径优先标记：命中这些关键词的字段是结论必须引用的核心证据
# 说明：row_count/total_count 与 rowcount/totalcount 并存——真实取数返回的 meta 用驼峰
# （rowCount/totalCount），旧规划器只写了下划线写法，导致行数证据在真实形状下漏收。
PRIORITY_MARKERS = (
    "dataset",
    "period",
    "filter",
    "freshness",
    "ratio",
    "pct_",
    "diff_",
    "latest_",
    "margin",
    "baseline_",
    "current_",
    "previous_",
    "row_count",
    "total_count",
    "rowcount",
    "totalcount",
    "requested_",
)
# 结果行下标匹配：拍平后对象列表的元素路径形如 data[0].price / data.result.data[3].x
_ROW_INDEX_PATTERN = re.compile(r"\[\d+\]")
# 末段为这些名字且取值为空时，表示"本次没有错误"，属于正常成功语义而非缺失证据
_EMPTY_MEANS_NO_ERROR = ("error", "errors")
# 行数/总行数字段的归一化名（去下划线并转小写后比较，兼容 row_count 与 rowCount）
_ROW_COUNT_NAMES = ("rowcount",)
_TOTAL_COUNT_NAMES = ("totalcount",)
# 披露代码 → 最终回答必须包含的中文披露话术
DISCLOSURE_MESSAGES = {
    "missing_not_zero": "空值或缺失值不等于业务值为零。",
    "zero_rows_not_business_zero": "零行只表示没有返回记录，不能据此判断业务值为零。",
    "freshness_uncertain": "数据新鲜度可能不完整或存在延迟，相关结论需要谨慎。",
    "latest_available_period": "请求周期尚无完整数据，只能说明最近可用周期。",
    "currency_not_declared": "结果未明确声明币种，不得推断具体货币。",
    "owner_confirmation_required": "跨数据集口径需要数据负责人确认。",
}
# 禁止推断代码 → 对应的中文禁止事项
FORBIDDEN_MESSAGES = {
    "causal_reason_without_evidence": "没有外部证据时不得断言业务原因。",
    "requested_period_is_zero": "不得把请求周期的缺失值表述为零。",
    "business_value_is_zero": "不得把零行表述为业务值为零。",
    "business_drop_confirmed": "不得把末日异常断言为真实业务下降。",
    "datasets_directly_mergeable": "未经数据负责人确认，不能直接合并或混用数据集。",
}


def _deduplicate(values: Iterable[str]) -> list[str]:
    """按出现顺序去重并剔除空值。"""
    return list(dict.fromkeys(value for value in values if value))


def _flatten(value: Any, path: str = "") -> list[dict[str, Any]]:
    """把嵌套 JSON 拍平为 path/value 证据条目。

    列表处理规则：
    - 全为 None 的列表 → 标记 all_values_missing（缺失证据）；
    - 周期/筛选/日期范围类标量列表 → 整体保留（口径证据）；
    - 其他标量列表 → 只保留末位值（时间序列取最新值）；
    - 对象列表 → 逐项递归展开。
    """
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            result.extend(_flatten(item, child))
        return result
    if isinstance(value, list):
        if not value:
            return []
        if all(item is None for item in value):
            return [{"path": path, "value": None, "all_values_missing": True}]
        scalar = [item for item in value if not isinstance(item, (dict, list))]
        if scalar:
            normalized_path = path.casefold()
            if any(marker in normalized_path for marker in ("period", "filter", "date_range")):
                return [{"path": path, "value": scalar}]
            return [{"path": f"{path}[-1]", "value": scalar[-1]}]
        result = []
        for index, item in enumerate(value):
            result.extend(_flatten(item, f"{path}[{index}]"))
        return result
    return [{"path": path, "value": value}]


def _is_required_evidence(item: dict[str, Any]) -> bool:
    """判断一条拍平结果是否属于结论必须引用的核心证据。"""
    path = str(item.get("path", "")).casefold()
    if path.endswith("[-1]"):
        return True
    return any(marker in path for marker in PRIORITY_MARKERS)


def _row_prefix(path: str) -> str:
    """取结果行前缀：路径里第一个 `[数字]` 下标（其后紧跟 `.`）之前的部分。

    真实取数返回的结果行挂在对象列表下（`data[0].price`、`rows[1].x`、
    `data.result.data[2].y`），拍平后既不含 PRIORITY_MARKERS 也不以 `[-1]` 结尾，
    旧判定会把它们全部丢弃。这里统一按"对象列表元素"识别为结果行证据。
    取第一个下标而非最后一个：行内再嵌列表时仍归属于最外层的那一行。
    非结果行（含标量列表末位路径 `xxx[-1]`）返回空串。
    """
    match = _ROW_INDEX_PATTERN.search(path)
    if not match:
        return ""
    end = match.end()
    # 必须是「行下标 + . + 列名」形态；`data[0]` 这种纯下标结尾不是列证据
    if end >= len(path) or path[end] != ".":
        return ""
    return path[:end]


def _split_result_rows(
    flattened: Sequence[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """把拍平结果拆成「结果行证据（按行分组，保持行序与行内列序）」与「其余证据」。"""
    row_groups: dict[str, list[dict[str, Any]]] = {}
    others: list[dict[str, Any]] = []
    for item in flattened:
        prefix = _row_prefix(str(item.get("path", "")))
        if prefix:
            row_groups.setdefault(prefix, []).append(item)
        else:
            others.append(item)
    return row_groups, others


def _leaf_name(path: str) -> str:
    """取路径末段字段名（不含父路径）。"""
    return path.rsplit(".", 1)[-1]


def _is_missing_evidence(item: dict[str, Any]) -> bool:
    """判断一条拍平结果是否属于缺失证据。

    `error`/`errors` 为空表示"本次没有错误"，是成功返回的正常语义。真实返回体固定带
    `"error": null`，若按缺失处理会让 missing_paths 恒为 `["error"]`，进而恒定误加
    "空值不等于零"披露与"请求周期为零"禁止项。除此之外的空值仍按缺失处理。
    """
    if not (item.get("all_values_missing") or item.get("value") is None):
        return False
    return _leaf_name(str(item.get("path", ""))).casefold() not in _EMPTY_MEANS_NO_ERROR


def _currency_evidence(flattened: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """在整个返回体里找第一条末段为 currency 且取值为非空字符串的证据。

    币种是口径证据（同一份数值在不同币种下含义完全不同），真实返回把它放在
    `meta.currency`，而不是旧实现认的 `currency_metadata_status`。找不到即视为未声明。
    """
    for item in flattened:
        if _leaf_name(str(item.get("path", ""))).casefold() != "currency":
            continue
        value = item.get("value")
        if isinstance(value, str) and value.strip():
            return item
    return None


def _count_value(flattened: Sequence[dict[str, Any]], names: Sequence[str]) -> Any:
    """按末段字段名取行数类计数值，归一化后比较以兼容 row_count 与 rowCount 两种写法。"""
    for item in flattened:
        leaf = _leaf_name(str(item.get("path", ""))).casefold().replace("_", "")
        if leaf in names:
            return item.get("value")
    return None


def _collect_evidence(
    base_required: Sequence[dict[str, Any]],
    row_groups: dict[str, list[dict[str, Any]]],
    currency_item: dict[str, Any] | None,
    max_evidence: int,
    rows_limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """按 max_evidence 预算组装 required_evidence，返回（证据列表, 完整覆盖的行数）。

    收集口径为「逐行完整、行数截断」：预算不足以放下一整行时就停在该行之前，
    保证被引用的每一行都是完整的，而不是各行残缺。
    币种证据不占预算且置顶——它是解释所有数值的前提。
    """
    evidence = list(base_required[:max_evidence])
    remaining = max_evidence - len(evidence)
    rows_covered = 0
    for group in list(row_groups.values())[:rows_limit]:
        if remaining <= 0:
            break
        if len(group) > remaining:
            # 首行列数就超预算时至少保留该行前 remaining 列，避免行证据整体为空；
            # 此时没有任何一行被完整收集，rows_covered 保持 0 以如实标记截断
            if rows_covered == 0:
                evidence.extend(group[:remaining])
            break
        evidence.extend(group)
        remaining -= len(group)
        rows_covered += 1
    if currency_item is not None:
        currency_path = currency_item.get("path")
        # 币种本身可能就是某一行的列（已被收进来），避免重复
        if all(item.get("path") != currency_path for item in evidence):
            evidence.insert(0, currency_item)
    return evidence, rows_covered


def _value_for_path(flattened: Sequence[dict[str, Any]], suffix: str) -> Any:
    """按完整路径或末段字段名取第一个命中的证据值。"""
    for item in flattened:
        path = str(item.get("path", ""))
        if path == suffix or path.rsplit(".", 1)[-1] == suffix:
            return item.get("value")
    return None


def _dataset_name(source: dict) -> str:
    """收集返回中所有 dataset* 字符串字段作为数据集中文名（顿号连接）。

    注意：opscli 的查询返回体里并没有 dataset* 键（只有 data.payload.tableId），
    所以走正式执行通道时这里恒为空串，必须由调用方用规划合同的
    model_view.dataset_name_zh 覆盖。本函数只作旁路直连（MCP/图表入口）的兜底。
    """
    names = []
    for key, value in source.items():
        if not str(key).startswith("dataset") or not isinstance(value, str):
            continue
        if value and value not in names:
            names.append(value)
    return "、".join(names)


def build_evidence_contract(
    source: dict,
    max_evidence: int = MAX_EVIDENCE,
    *,
    dataset_name_zh: str = "",
) -> dict:
    """从一次查询返回构建证据与披露规划器。

    披露与禁止推断按信号自动叠加：缺失值、零行、新鲜度不完整、
    币种未声明、跨数据集口径待确认等，每类信号对应固定话术。

    Args:
        dataset_name_zh: 规划合同给出的数据集中文名。查询返回体本身不带该信息，
            不传时 dataset_name_zh 恒为空串，而结果分析的第一条要求就是
            「先说明数据集中文名」——Agent 只能靠自己记忆回填，无法从结果侧独立核验。
    """
    if not isinstance(source, dict):
        raise TypeError("evidence_source_must_be_object")
    if max_evidence < 1:
        raise ValueError("max_evidence_must_be_positive")
    flattened = _flatten(source)
    # 结果行单独成组：行证据按行收集并可整行截断，其余证据仍按优先标记筛选
    row_groups, other_items = _split_result_rows(flattened)
    base_required = [item for item in other_items if _is_required_evidence(item)]
    currency_item = _currency_evidence(flattened)
    missing_paths = [str(item["path"]) for item in flattened if _is_missing_evidence(item)]
    freshness_status = str(_value_for_path(flattened, "freshness_status") or "")
    owner_status = str(_value_for_path(flattened, "status") or "")
    row_count = _count_value(flattened, _ROW_COUNT_NAMES)
    total_count = _count_value(flattened, _TOTAL_COUNT_NAMES)
    currency_status = str(
        _value_for_path(flattened, "currency_metadata_status") or ""
    )

    disclosures = []
    # 因果推断永远需要外部证据，无条件列入禁止项
    forbidden = ["causal_reason_without_evidence"]
    if missing_paths:
        disclosures.append("missing_not_zero")
        forbidden.append("requested_period_is_zero")
    if row_count == 0 or total_count == 0:
        disclosures.append("zero_rows_not_business_zero")
        forbidden.append("business_value_is_zero")
    if any(term in freshness_status for term in ("partial", "lagged", "suspected")):
        disclosures.append("freshness_uncertain")
        forbidden.append("business_drop_confirmed")
    if freshness_status.startswith("monthly_data_available_through_"):
        disclosures.append("latest_available_period")
    # 币种未声明：旧口径只认显式的 currency_metadata_status，真实返回没有该键，
    # 只能靠"全返回体找不到任何非空 currency"来判定
    if currency_status == "not_explicitly_declared" or currency_item is None:
        disclosures.append("currency_not_declared")
    if owner_status == "owner_confirmation_required":
        disclosures.append("owner_confirmation_required")
        forbidden.append("datasets_directly_mergeable")

    rows_total = len(row_groups)
    rows_limit = rows_total
    # 输出体积兜底：超过 MAX_OUTPUT_BYTES 时逐次把行证据行数减半重组，
    # 只有减到 1 行（或本来就没有行证据）仍超限才拒绝输出——直接抛错会让宽表取数
    # 完全拿不到证据合同，而少几行证据仍然可用。
    while True:
        required, rows_covered = _collect_evidence(
            base_required, row_groups, currency_item, max_evidence, rows_limit
        )
        result = {
            "contract": CONTRACT,
            "dataset_name_zh": str(dataset_name_zh).strip() or _dataset_name(source),
            "numeric_evidence_policy_zh": (
                "required_evidence 中用于结论的数值必须原样引用，不得四舍五入或改写精度。"
            ),
            "required_evidence": required,
            "required_disclosure_codes": _deduplicate(disclosures),
            "required_disclosures_zh": [
                DISCLOSURE_MESSAGES[code]
                for code in _deduplicate(disclosures)
                if code in DISCLOSURE_MESSAGES
            ],
            "forbidden_inference_codes": _deduplicate(forbidden),
            "forbidden_inferences_zh": [
                FORBIDDEN_MESSAGES[code]
                for code in _deduplicate(forbidden)
                if code in FORBIDDEN_MESSAGES
            ],
            "missing_paths": missing_paths[:max_evidence],
            "freshness_status": freshness_status,
        }
        if rows_covered < rows_total:
            # 只在真的截断时追加，避免污染未截断场景的输出结构
            result["evidence_truncated"] = True
            result["evidence_rows_covered"] = rows_covered
            result["evidence_rows_total"] = rows_total
        size = len(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if size <= MAX_OUTPUT_BYTES:
            return result
        if rows_covered <= 1:
            raise RuntimeError("evidence_contract_output_too_large")
        rows_limit = rows_covered // 2
