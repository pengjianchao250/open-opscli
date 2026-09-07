"""规划器内核 evidence_contract：真实查询返回形状的证据与披露回归。

背景：`entry._execute_planned_contract` 用 `QueryManager.run_query_template()`
的真实返回体调用 `build_evidence_contract`，其形状是
`{"success", "data": [行...], "meta": {"rowCount", "totalCount", "currency", ...}, "error": null}`。
在本次修复前，这种真实形状下：

1. `required_evidence` 恒为空（结果行路径 `data[0].price` 既不含 PRIORITY_MARKERS
   也不以 `[-1]` 结尾）；
2. `missing_paths` 恒为 `["error"]`（`error: null` 表示"没有错误"，却被当成缺失证据，
   进而误加"空值不等于零"披露）；
3. 零行判定读的是 `row_count`/`total_count` 下划线路径，真实 meta 是
   `rowCount`/`totalCount`，判定失效；
4. 币种披露只认 `currency_metadata_status`，真实返回缺 `meta.currency` 时不披露。

本文件用真实形状把上述四类缺陷钉死，另覆盖行证据的截断口径与输出体积兜底。
"""

import pytest

from opscli.query.services.planner import evidence_contract


def _real_response() -> dict:
    """一次真实的 `opscli query flow` 取数返回（各平台销售额，两行）。"""
    return {
        "success": True,
        "data": [
            {"platform_name": "Amazon", "price": "10710.65310000"},
            {"platform_name": "Temu", "price": "311205.50870000"},
        ],
        "meta": {
            "dataSource": "doris_analytics",
            "rowCount": 2,
            "totalCount": 2,
            "executionTimeMs": 1105,
            "queryId": "59acaf0f-0000-0000-0000-000000000000",
            "timestamp": "2026-09-07T04:15:53.569339",
            "dialect": "doris",
            "cached": False,
            "currency": "CNY",
        },
        "error": None,
    }


def _paths(result: dict) -> list[str]:
    """取 required_evidence 的路径列表，便于断言顺序与包含关系。"""
    return [str(item["path"]) for item in result["required_evidence"]]


# ── 缺陷 1：结果行必须成为 required_evidence ────────────────────────────────


def test_real_shape_result_rows_become_required_evidence():
    """真实返回的每一行每一列标量都要进 required_evidence（修复前恒为空）。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    paths = _paths(result)
    for expected in (
        "meta.currency",
        "data[0].platform_name",
        "data[0].price",
        "data[1].platform_name",
        "data[1].price",
    ):
        assert expected in paths, f"缺少证据路径：{expected}；实际={paths}"


def test_real_shape_row_values_are_kept_verbatim():
    """行证据必须原样携带取数返回的原始值（数值精度不得被改写）。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    evidence = {str(item["path"]): item["value"] for item in result["required_evidence"]}
    assert evidence["data[0].platform_name"] == "Amazon"
    assert evidence["data[0].price"] == "10710.65310000"
    assert evidence["data[1].price"] == "311205.50870000"


def test_real_shape_rows_are_collected_row_by_row_in_column_order():
    """行证据按「行序 + 行内列序」收集，同一行的列必须连续且不打乱顺序。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    paths = _paths(result)
    row_paths = [path for path in paths if path.startswith("data[")]
    assert row_paths == [
        "data[0].platform_name",
        "data[0].price",
        "data[1].platform_name",
        "data[1].price",
    ]


@pytest.mark.parametrize(
    "wrapper",
    [
        # 结果行在返回体中的四种常见挂载位置都要识别为行证据
        lambda rows: {"data": rows},
        lambda rows: {"rows": rows},
        lambda rows: {"data": {"rows": rows}},
        lambda rows: {"data": {"result": {"data": rows}}},
    ],
)
def test_result_rows_recognized_under_common_wrappers(wrapper):
    """`data[i]` / `rows[i]` / `data.rows[i]` / `data.result.data[i]` 都算结果行。"""
    source = wrapper([{"price": "1.00"}, {"price": "2.00"}])
    result = evidence_contract.build_evidence_contract(source)
    paths = _paths(result)
    assert len(paths) == 2, f"两行各一列应产出两条行证据，实际={paths}"
    assert all(path.endswith(".price") for path in paths)


# ── 缺陷 2：error 为 null 不是缺失证据 ──────────────────────────────────────


def test_null_error_is_not_a_missing_path():
    """`error: null` 表示本次没有错误，不能计入 missing_paths。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    assert result["missing_paths"] == []


def test_null_error_does_not_trigger_missing_not_zero_disclosure():
    """`error: null` 不得触发"空值不等于零"披露与"请求周期为零"禁止项。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    assert "missing_not_zero" not in result["required_disclosure_codes"]
    assert "requested_period_is_zero" not in result["forbidden_inference_codes"]


def test_null_errors_plural_is_also_excluded_from_missing_paths():
    """末段为 `errors` 的空值同样按"没有错误"处理。"""
    source = {"errors": None, "meta": {"currency": "CNY"}}
    result = evidence_contract.build_evidence_contract(source)
    assert result["missing_paths"] == []


def test_other_null_values_are_still_missing_paths():
    """除 error/errors 外的空值仍算缺失证据，披露与禁止项照旧叠加。"""
    source = {
        "data": [{"price": None}],
        "meta": {"currency": "CNY", "rowCount": 1},
        "error": None,
    }
    result = evidence_contract.build_evidence_contract(source)
    assert result["missing_paths"] == ["data[0].price"]
    assert "missing_not_zero" in result["required_disclosure_codes"]


# ── 缺陷 3：rowCount / totalCount 驼峰写法必须等同于下划线写法 ──────────────


def test_camel_case_row_count_zero_triggers_zero_rows_disclosure():
    """`meta.rowCount == 0` 必须触发零行披露（修复前只认 `row_count`）。"""
    source = _real_response()
    source["data"] = []
    source["meta"]["rowCount"] = 0
    result = evidence_contract.build_evidence_contract(source)
    assert "zero_rows_not_business_zero" in result["required_disclosure_codes"]
    assert "business_value_is_zero" in result["forbidden_inference_codes"]


def test_camel_case_total_count_zero_triggers_zero_rows_disclosure():
    """`meta.totalCount == 0` 同样触发零行披露。"""
    source = _real_response()
    source["data"] = []
    source["meta"]["rowCount"] = 5
    source["meta"]["totalCount"] = 0
    result = evidence_contract.build_evidence_contract(source)
    assert "zero_rows_not_business_zero" in result["required_disclosure_codes"]


def test_snake_case_row_count_zero_still_triggers_zero_rows_disclosure():
    """下划线写法 `row_count` 的旧行为必须保持（两种写法一视同仁）。"""
    result = evidence_contract.build_evidence_contract({"row_count": 0})
    assert "zero_rows_not_business_zero" in result["required_disclosure_codes"]


def test_camel_case_counts_are_required_evidence():
    """`meta.rowCount` / `meta.totalCount` 与下划线写法一样属于核心证据。"""
    paths = _paths(evidence_contract.build_evidence_contract(_real_response()))
    assert "meta.rowCount" in paths
    assert "meta.totalCount" in paths


def test_non_zero_camel_row_count_does_not_trigger_zero_rows_disclosure():
    """行数非零时不得误报零行披露。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    assert "zero_rows_not_business_zero" not in result["required_disclosure_codes"]


# ── 缺陷 4：币种口径证据与未声明披露 ────────────────────────────────────────


def test_currency_evidence_is_placed_first():
    """`meta.currency` 是口径证据，必须排在 required_evidence 最前面。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    assert _paths(result)[0] == "meta.currency"


def test_declared_currency_does_not_trigger_currency_disclosure():
    """返回体已声明币种时不得再要求"未声明币种"披露。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    assert "currency_not_declared" not in result["required_disclosure_codes"]


def test_missing_currency_triggers_currency_not_declared_disclosure():
    """整个返回体找不到非空 currency 时，必须补"未声明币种"披露。"""
    source = _real_response()
    source["meta"].pop("currency")
    result = evidence_contract.build_evidence_contract(source)
    assert "currency_not_declared" in result["required_disclosure_codes"]
    assert "结果未明确声明币种，不得推断具体货币。" in result["required_disclosures_zh"]


def test_empty_currency_string_counts_as_not_declared():
    """币种为空串等同于未声明。"""
    source = _real_response()
    source["meta"]["currency"] = "  "
    result = evidence_contract.build_evidence_contract(source)
    assert "currency_not_declared" in result["required_disclosure_codes"]
    assert "meta.currency" not in _paths(result)


def test_currency_evidence_survives_full_max_evidence_budget():
    """max_evidence 已被其他证据占满时，币种证据仍必须保留（不受上限裁剪）。"""
    source = {f"ratio_{index}": index for index in range(24)}
    source["meta"] = {"currency": "USD"}
    result = evidence_contract.build_evidence_contract(source, max_evidence=24)
    paths = _paths(result)
    assert paths[0] == "meta.currency"
    assert len(paths) == 25


# ── 行证据截断口径：逐行完整、行数截断 ──────────────────────────────────────


def test_row_evidence_truncates_by_whole_rows_under_max_evidence():
    """30 行 × 3 列在 max_evidence=24 下只收 8 行，且每行三列完整。"""
    source = {
        "data": [
            {"c0": f"r{row}c0", "c1": f"r{row}c1", "c2": f"r{row}c2"} for row in range(30)
        ]
    }
    result = evidence_contract.build_evidence_contract(source, max_evidence=24)
    assert result["evidence_truncated"] is True
    assert result["evidence_rows_covered"] == 8
    assert result["evidence_rows_total"] == 30
    paths = _paths(result)
    assert len(paths) == 24
    # 逐行完整：被收进来的 8 行，每行三列都在
    for row in range(8):
        for column in range(3):
            assert f"data[{row}].c{column}" in paths
    assert "data[8].c0" not in paths


def test_truncation_keys_absent_when_all_rows_fit():
    """行数未超上限时不追加 evidence_truncated 等键（不污染既有输出结构）。"""
    result = evidence_contract.build_evidence_contract(_real_response())
    assert "evidence_truncated" not in result
    assert "evidence_rows_covered" not in result
    assert "evidence_rows_total" not in result


# ── 输出体积兜底：先减半行数，减无可减才报错 ────────────────────────────────


def test_oversized_output_halves_evidence_rows_instead_of_raising():
    """输出超过 MAX_OUTPUT_BYTES 时逐步减半行证据，而不是直接抛错。"""
    source = {
        "data": [
            {"c0": "x" * 400, "c1": "y" * 400, "c2": "z" * 400} for _ in range(8)
        ]
    }
    result = evidence_contract.build_evidence_contract(source, max_evidence=24)
    assert result["evidence_truncated"] is True
    assert result["evidence_rows_covered"] == 4
    assert result["evidence_rows_total"] == 8
    assert len(result["required_evidence"]) == 12


def test_single_oversized_row_still_raises_runtime_error():
    """减到 1 行仍超限时才抛 RuntimeError（错误信息保持不变）。"""
    source = {"data": [{f"c{index}": "x" * 400 for index in range(30)}]}
    with pytest.raises(RuntimeError, match="evidence_contract_output_too_large"):
        evidence_contract.build_evidence_contract(source, max_evidence=40)
