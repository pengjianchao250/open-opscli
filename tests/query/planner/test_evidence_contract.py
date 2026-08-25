"""规划器内核 evidence_contract：证据与披露规划器纯函数迁入验证。

断言样例的期望值直接从 skill 版
`opscli/skills/templates/ops-dataset-query/scripts/evidence_contract.py`
现行为跑出的真值取值（迁移任务 K3 的行为等价铁律：只搬家，不改算法），
锁定内核 `build_evidence_contract` 与源实现逐字节一致。
"""

import json

import pytest

from opscli.query.services.planner import evidence_contract


def test_build_evidence_contract_combined_signals_matches_skill_truth():
    """缺失值 + 零行 + 新鲜度部分 + 币种未声明 + 待负责人确认：五类信号同时命中。

    期望值取自 skill 版对同一输入的真实运行结果（见任务报告 Step 1 移植清单）。
    """
    source = {
        "row_count": 0,
        "total_count": 0,
        "freshness_status": "partial_data_suspected",
        "currency_metadata_status": "not_explicitly_declared",
        "status": "owner_confirmation_required",
        "period_filter": [None, None],
        "ratio_pct": None,
    }
    result = evidence_contract.build_evidence_contract(source, dataset_name_zh="销售数据集")

    assert result["contract"] == "evidence_contract_v1"
    assert result["dataset_name_zh"] == "销售数据集"
    assert result["required_evidence"] == [
        {"path": "row_count", "value": 0},
        {"path": "total_count", "value": 0},
        {"path": "freshness_status", "value": "partial_data_suspected"},
        {"path": "period_filter", "value": None, "all_values_missing": True},
        {"path": "ratio_pct", "value": None},
    ]
    assert result["required_disclosure_codes"] == [
        "missing_not_zero",
        "zero_rows_not_business_zero",
        "freshness_uncertain",
        "currency_not_declared",
        "owner_confirmation_required",
    ]
    assert result["required_disclosures_zh"] == [
        "空值或缺失值不等于业务值为零。",
        "零行只表示没有返回记录，不能据此判断业务值为零。",
        "数据新鲜度可能不完整或存在延迟，相关结论需要谨慎。",
        "结果未明确声明币种，不得推断具体货币。",
        "跨数据集口径需要数据负责人确认。",
    ]
    assert result["forbidden_inference_codes"] == [
        "causal_reason_without_evidence",
        "requested_period_is_zero",
        "business_value_is_zero",
        "business_drop_confirmed",
        "datasets_directly_mergeable",
    ]
    assert result["forbidden_inferences_zh"] == [
        "没有外部证据时不得断言业务原因。",
        "不得把请求周期的缺失值表述为零。",
        "不得把零行表述为业务值为零。",
        "不得把末日异常断言为真实业务下降。",
        "未经数据负责人确认，不能直接合并或混用数据集。",
    ]
    assert result["missing_paths"] == ["period_filter", "ratio_pct"]
    assert result["freshness_status"] == "partial_data_suspected"


def test_dataset_name_zh_falls_back_to_dataset_prefixed_fields_when_not_passed():
    """未传 dataset_name_zh 时，回退拼接返回体里所有 dataset* 字符串字段（顿号连接）。"""
    source = {"dataset_alias_name": "广告数据集", "dataset_extra": "曝光"}
    result = evidence_contract.build_evidence_contract(source)
    assert result["dataset_name_zh"] == "广告数据集、曝光"


def test_latest_available_period_disclosure_without_forbidden_inference():
    """freshness_status 以 monthly_data_available_through_ 开头只触发披露，不触发禁止推断。"""
    source = {"freshness_status": "monthly_data_available_through_2026-07"}
    result = evidence_contract.build_evidence_contract(source)
    assert result["required_disclosure_codes"] == ["latest_available_period"]
    # 因果推断禁令始终存在，latest_available_period 本身不追加其他禁止项
    assert result["forbidden_inference_codes"] == ["causal_reason_without_evidence"]
    assert result["freshness_status"] == "monthly_data_available_through_2026-07"


def test_max_evidence_truncates_required_evidence_and_missing_paths():
    """max_evidence 同时截断 required_evidence 与 missing_paths（两者共用同一上限）。"""
    source = {f"ratio_{i}": i for i in range(30)}
    result = evidence_contract.build_evidence_contract(source, max_evidence=5)
    assert len(result["required_evidence"]) == 5
    assert result["missing_paths"] == []


def test_non_dict_source_raises_type_error():
    """source 非 dict 时抛 TypeError，错误信息与源实现一致。"""
    with pytest.raises(TypeError, match="evidence_source_must_be_object"):
        evidence_contract.build_evidence_contract([1, 2, 3])


def test_non_positive_max_evidence_raises_value_error():
    """max_evidence < 1 时抛 ValueError，错误信息与源实现一致。"""
    with pytest.raises(ValueError, match="max_evidence_must_be_positive"):
        evidence_contract.build_evidence_contract({}, max_evidence=0)


def test_oversized_output_raises_runtime_error():
    """拍平结果超过 MAX_OUTPUT_BYTES（8000 字节）时拒绝输出，抛 RuntimeError。"""
    source = {f"ratio_field_{i}": "x" * 500 for i in range(60)}
    with pytest.raises(RuntimeError, match="evidence_contract_output_too_large"):
        evidence_contract.build_evidence_contract(source, max_evidence=60)


def test_required_evidence_marks_last_of_scalar_time_series_list():
    """非口径类标量列表只保留末位值（路径追加 [-1]），且恒判定为必需证据。"""
    source = {"metrics": {"daily_sales": [10, 20, 30]}}
    result = evidence_contract.build_evidence_contract(source)
    assert {"path": "metrics.daily_sales[-1]", "value": 30} in result["required_evidence"]
