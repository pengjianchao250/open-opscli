#!/usr/bin/env python3
"""把查询返回 JSON 拍平为受限的证据与披露合同（evidence_contract_v1）。

输入：通过 stdin 传入的一次查询返回 JSON（对象）。
输出：required_evidence（结论必须引用的证据路径与原值）、
required_disclosures_zh（必须披露的中文事项）、
forbidden_inferences_zh（禁止做出的推断）。
结果分析阶段只允许基于本合同组织结论，防止对返回数据的过度推断。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable, Sequence


CONTRACT = "evidence_contract_v1"
MAX_EVIDENCE = 24
MAX_OUTPUT_BYTES = 8000
# 证据路径优先标记：命中这些关键词的字段是结论必须引用的核心证据
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
    "requested_",
)
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


def _value_for_path(flattened: Sequence[dict[str, Any]], suffix: str) -> Any:
    """按完整路径或末段字段名取第一个命中的证据值。"""
    for item in flattened:
        path = str(item.get("path", ""))
        if path == suffix or path.rsplit(".", 1)[-1] == suffix:
            return item.get("value")
    return None


def _dataset_name(source: dict) -> str:
    """收集返回中所有 dataset* 字符串字段作为数据集中文名（顿号连接）。"""
    names = []
    for key, value in source.items():
        if not str(key).startswith("dataset") or not isinstance(value, str):
            continue
        if value and value not in names:
            names.append(value)
    return "、".join(names)


def build_evidence_contract(source: dict, max_evidence: int = MAX_EVIDENCE) -> dict:
    """从一次查询返回构建证据与披露合同。

    披露与禁止推断按信号自动叠加：缺失值、零行、新鲜度不完整、
    币种未声明、跨数据集口径待确认等，每类信号对应固定话术。
    """
    if not isinstance(source, dict):
        raise TypeError("evidence_source_must_be_object")
    if max_evidence < 1:
        raise ValueError("max_evidence_must_be_positive")
    flattened = _flatten(source)
    required = [item for item in flattened if _is_required_evidence(item)]
    missing_paths = [
        str(item["path"])
        for item in flattened
        if item.get("all_values_missing") or item.get("value") is None
    ]
    freshness_status = str(_value_for_path(flattened, "freshness_status") or "")
    owner_status = str(_value_for_path(flattened, "status") or "")
    row_count = _value_for_path(flattened, "row_count")
    total_count = _value_for_path(flattened, "total_count")
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
    if currency_status == "not_explicitly_declared":
        disclosures.append("currency_not_declared")
    if owner_status == "owner_confirmation_required":
        disclosures.append("owner_confirmation_required")
        forbidden.append("datasets_directly_mergeable")

    result = {
        "contract": CONTRACT,
        "dataset_name_zh": _dataset_name(source),
        "numeric_evidence_policy_zh": (
            "required_evidence 中用于结论的数值必须原样引用，不得四舍五入或改写精度。"
        ),
        "required_evidence": required[:max_evidence],
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
    size = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > MAX_OUTPUT_BYTES:
        raise RuntimeError("evidence_contract_output_too_large")
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """命令行参数：查询返回 JSON 固定从 stdin 读取。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-evidence", type=int, default=MAX_EVIDENCE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        value = json.loads(sys.stdin.read())
        result = build_evidence_contract(value, args.max_evidence)
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
