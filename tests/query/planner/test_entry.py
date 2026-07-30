"""规划器内核入口 entry：组装缓存/适配器/规划器/执行。

覆盖 run_plan（metadata_all→adapter→build_model_query_plan）、run_flow（planned 时
经 QueryManager.run_query_template 执行一次），以及枚举值提取与模板 null 清理。
"""

from pathlib import Path

import httpx
import respx

from opscli.query.services.manager import QueryManager
from opscli.query.services.planner import entry


def _sales_metadata():
    """后端 query-metadata 全量返回的 data 段（销售数据集）。"""
    return {
        "datasets": [
            {
                "table_id": 100,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "dataset_category": "normal",
                "description": "即时综合数据集",
                "remarks": "销售 库存 广告",
                "select_columns": [],
            }
        ],
        "fields": [
            {
                "table_id": 100,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "field_name": "stat_date",
                "verbose_name": "统计日期",
                "global_alias": "f_d",
                "field_type": "dimension",
                "has_formula_config": 0,
            },
            {
                "table_id": 100,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "field_name": "sales_amount",
                "verbose_name": "销售额",
                "global_alias": "f_sa",
                "field_type": "metric",
                "summary_expression": "sum(sales_amount)",
                "detail_expression": "sales_amount",
                "has_formula_config": 1,
            },
        ],
    }


@respx.mock
def test_run_plan_returns_model_contract(tmp_path: Path):
    """run_plan：拉全量元数据→适配→规划，产出模型合同 v2。"""
    respx.get(url__regex=r".*/datasets/query-metadata.*").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": _sales_metadata()})
    )
    qm = QueryManager()
    qm.client._get_auth = lambda system: ({}, {})  # type: ignore[method-assign]
    contract = entry.run_plan(
        "查询销售额 近7天", user_email="u@x.com", base_dir=tmp_path, query_manager=qm
    )
    assert contract["contract"] == "query_plan_model_contract_v2"
    assert contract["data_state"] == "ready"


def test_run_flow_passthrough_when_not_planned(monkeypatch):
    """run_flow：非 planned 合同原样返回，不触发执行。"""
    clarify = {
        "contract": "query_plan_model_contract_v2",
        "query_mode": "dataset_query",
        "status": "clarify_required",
    }
    monkeypatch.setattr(entry, "run_plan", lambda *a, **k: clarify)
    out = entry.run_flow("随便", user_email="u@x.com")
    assert out is clarify


def test_run_flow_executes_template_when_planned(monkeypatch):
    """run_flow：planned 合同经 run_query_template 执行一次并回灌结果 + 披露延后项。"""
    planned = {
        "contract": "query_plan_model_contract_v2",
        "query_mode": "dataset_query",
        "status": "planned",
        "execution_ref": {
            "query_template": {"tableId": 1, "dimensions": [{"field": "x", "alias": "x"}]}
        },
    }
    monkeypatch.setattr(entry, "run_plan", lambda *a, **k: planned)

    class _FakeQM:
        def run_query_template(self, execution_ref):
            return {"data": {"result": {"data": [{"x": 1}]}}}

    out = entry.run_flow("查询", user_email="u@x.com", query_manager=_FakeQM())
    assert out["result"]["data"]["result"]["data"] == [{"x": 1}]
    # 未传 order_by / result_dir → 无任何延后项披露（避免对无关查询误导）
    assert "execution_notes" not in out


def _planned_with_template():
    return {
        "contract": "query_plan_model_contract_v2",
        "query_mode": "dataset_query",
        "status": "planned",
        "execution_ref": {
            "query_template": {
                "tableId": 1,
                "dimensions": [{"field": "x", "alias": "x"}],
                "metrics": [],
                "filters": [],
                "orderBy": None,
                "limit": None,
            }
        },
    }


def test_run_flow_fills_limit_order_offset(monkeypatch):
    """run_flow 把 limit/order_by/offset 填入 query_template 并重挂 plan_integrity。"""
    from opscli.query.services.planner import plan_integrity

    monkeypatch.setattr(entry, "run_plan", lambda *a, **k: _planned_with_template())
    captured = {}

    class _QM:
        def run_query_template(self, execution_ref):
            captured["template"] = execution_ref["query_template"]
            return {"data": []}

    out = entry.run_flow(
        "查询", user_email="u@x.com",
        limit=200, order_by=[{"field": "x", "desc": True}], offset=5,
        query_manager=_QM(),
    )
    t = captured["template"]
    assert t["limit"] == 200
    assert t["offset"] == 5
    assert t["orderBy"] == [{"field": "x", "desc": True}]
    # 改写模板后重挂完整性：剥离 run_flow 追加的运行时结果/披露后，规划合同仍自洽
    assert "plan_integrity" in out["execution_ref"]
    sealed = {
        k: v
        for k, v in out.items()
        if k not in ("result", "result_disclosures", "execution_notes")
    }
    assert plan_integrity.verify(sealed) is True
    # 传了 order_by → 仅出 orderBy 一条披露（未传 result_dir 不出落盘那条）
    assert out["execution_notes"] == [entry._NOTE_ORDER_BY]


def test_run_flow_result_dir_note_only_when_passed(monkeypatch):
    """传 result_dir（未传 order_by）→ 仅出落盘一条披露。"""
    monkeypatch.setattr(entry, "run_plan", lambda *a, **k: _planned_with_template())

    class _QM:
        def run_query_template(self, execution_ref):
            return {"data": []}

    from pathlib import Path
    out = entry.run_flow("查询", user_email="u@x.com", result_dir=Path("/tmp/x"), query_manager=_QM())
    assert out["execution_notes"] == [entry._NOTE_RESULT_DIR]


def test_run_flow_no_params_keeps_defaults(monkeypatch):
    """run_flow 不传 limit/order_by/offset → 模板 limit/orderBy 保持 None、不加 offset（沿用后端默认）。"""
    monkeypatch.setattr(entry, "run_plan", lambda *a, **k: _planned_with_template())
    captured = {}

    class _QM:
        def run_query_template(self, execution_ref):
            captured["template"] = execution_ref["query_template"]
            return {"data": []}

    entry.run_flow("查询", user_email="u@x.com", query_manager=_QM())
    t = captured["template"]
    assert t["limit"] is None
    assert t["orderBy"] is None
    assert "offset" not in t


def test_run_flow_auto_completes_server_default_page(monkeypatch):
    """未显式传 limit 时，服务端默认 20 行不得被当成 totalCount=145 的全量。"""
    monkeypatch.setattr(entry, "run_plan", lambda *a, **k: _planned_with_template())
    calls: list[int | None] = []

    class _QM:
        def run_query_template(self, execution_ref):
            current_limit = execution_ref["query_template"].get("limit")
            calls.append(current_limit)
            row_count = 20 if current_limit is None else 145
            return {
                "data": {
                    "result": {
                        "data": [{"asin": f"A{i}"} for i in range(row_count)],
                        "meta": {"totalCount": 145},
                    }
                }
            }

    out = entry.run_flow("查询", user_email="u@x.com", query_manager=_QM())

    assert calls == [None, 145]
    assert len(out["result"]["data"]["result"]["data"]) == 145
    assert out["result_disclosures"] == {
        "row_count_returned": 145,
        "total_count": 145,
        "truncated": False,
        "auto_complete_applied": True,
    }


def test_run_query_template_drops_null_keys():
    """QueryManager.run_query_template 删除 None 占位键（orderBy/limit）后转发。"""
    captured: dict = {}

    def _fake_post(payload):
        captured["payload"] = payload
        return {"data": {"result": {"data": []}}}

    qm = QueryManager()
    qm.client.cli_simple_query = _fake_post  # type: ignore[method-assign]
    ref = {
        "query_template": {
            "tableId": 1,
            "dimensions": [{"field": "x", "alias": "x"}],
            "metrics": [],
            "filters": [],
            "orderBy": None,
            "limit": None,
        }
    }
    qm.run_query_template(ref)
    assert "orderBy" not in captured["payload"]
    assert "limit" not in captured["payload"]
    assert captured["payload"]["tableId"] == 1


def test_extract_enum_values_dedup():
    """枚举值提取：多版本嵌套形状兜底 + 去重 + 去空。"""
    result = {
        "data": {
            "result": {
                "data": [
                    {"platform_name": "Amazon"},
                    {"platform_name": "Amazon"},
                    {"platform_name": ""},
                    {"platform_name": "Walmart"},
                ]
            }
        }
    }
    assert entry._extract_enum_values(result, "platform_name") == ["Amazon", "Walmart"]


def test_extract_enum_values_from_raw_simple_result():
    """build_simple_and_run().result 的真实形状：行直接在 result['data']（一级）。

    回归对拍发现：旧实现只兜底多级嵌套（data.result.data），漏了一级 data 形状，
    导致平台/组件权限枚举恒返回空 → 二段收敛失效。锁定真实形状。
    """
    result = {
        "success": True,
        "data": [{"platform_name": "Temu"}, {"platform_name": "Temu"}],
        "meta": {"rowCount": 2},
    }
    assert entry._extract_enum_values(result, "platform_name") == ["Temu"]
