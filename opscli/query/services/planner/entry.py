#!/usr/bin/env python3
"""规划器内核入口：组装缓存/适配器/规划器/执行。

对外暴露两个统一入口，供 CLI（opscli query plan/flow）与 MCP（query_plan/query_flow）复用：
- run_plan：自然语言请求 → query_plan_model_contract_v2（只规划不执行）。
- run_flow：一体化——规划 + planned 时按 query_template 执行一次取数。

数据源为后端 query-metadata（经用户级元数据缓存）。元数据未就绪时的刷新（refresh_fn）
与平台/组件权限枚举（enum_fn）作为回调注入规划器，替代旧 Skill 的 subprocess 调用。

依赖方向（铁律2）：仅依赖 opscli.query.* + 标准库，禁止 import opscli.mcp。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from opscli.query.services.manager import QueryManager
from opscli.query.services.metadata_cache import invalidate_metadata_cache
from opscli.query.services.planner import plan_integrity, query_plan
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


# run_flow 已知延后项：limit/order_by/offset 已可控（见 run_flow 参数），但 orderBy
# 服务端缺陷的本地兜底/加量重查、完整结果落盘 result_dir 仍未内核化（属旧 run_query.py
# 的结果后处理，作为独立后续任务补齐），执行时如实披露。
_FLOW_DEFERRED_NOTES = [
    "orderBy 服务端缺陷的本地兜底/加量重查暂未内核化（TopN 过渡方案，后续任务补齐）",
    "完整结果落盘 result_dir 暂未内核化，本次仅返回服务端查询结果",
]


def _extract_enum_values(result: Any, field_name: str) -> list[str]:
    """从 simple 查询结果中提取某字段的去重非空值。

    enum_fn 传入的是 cli_simple_query 的原始结果 {success, data:[行...], meta}，
    行直接位于 result["data"]（一级）；兼容个别版本/CLI 包裹层的多级嵌套形状
    （data.result.data / result.data / data.data），逐一兜底取第一个非空行列表，
    再按 field_name 抽取字符串值、去空去重保序。
    """
    rows: list = []
    root = result if isinstance(result, dict) else {}
    for path in (("data",), ("data", "result", "data"), ("result", "data"), ("data", "data")):
        node: Any = root
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, list) and node:
            rows = node
            break
    values: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = str(row.get(field_name, "")).strip()
        if value and value not in values:
            values.append(value)
    return values


def _make_callbacks(qm: QueryManager, user_email: str, base_dir: Path | None):
    """构造注入规划器的 refresh_fn / enum_fn 回调。

    - refresh_fn：失效用户级元数据缓存并重取全量 payload（替代 subprocess skills upgrade）。
    - enum_fn：对组件表执行一次 simple 查询并抽取字段枚举值（替代 subprocess query simple）。
    """

    def refresh_fn() -> dict:
        # 元数据未就绪：失效缓存后重取一次全量元数据
        invalidate_metadata_cache(base_dir=base_dir, user_email=user_email)
        return qm.metadata_all(user_email=user_email, base_dir=base_dir).payload

    def enum_fn(table_id: Any, field_name: str, *, limit: int) -> list[str]:
        # 权限枚举：复用内核 simple 查询取组件表某字段的可选值
        run = qm.build_simple_and_run(
            table_id=int(table_id),
            dimensions=[{"field": field_name, "alias": field_name}],
            limit=limit,
        )
        return _extract_enum_values(run.get("result"), field_name)

    return refresh_fn, enum_fn


def run_plan(
    request: str,
    *,
    user_email: str,
    base_dir: Path | None = None,
    requested_fields: Sequence[str] = (),
    top_n: int | None = None,
    query_manager: QueryManager | None = None,
) -> dict:
    """自然语言请求 → query_plan_model_contract_v2（只规划不执行）。

    Args:
        request: 用户查询原文。
        user_email: 当前账号邮箱（元数据缓存隔离维度，由 CLI/MCP 注入）。
        base_dir: 缓存根目录；CLI 默认 CONFIG_DIR，MCP 传隔离目录。
        requested_fields: 用户点名字段（CLI --field / MCP 传入）。
        top_n: 选表候选上限（缺省用规划器默认）。
        query_manager: 可注入的 QueryManager（MCP 显式凭证模式/测试用）；缺省新建。
    """
    qm = query_manager or QueryManager()
    refresh_fn, enum_fn = _make_callbacks(qm, user_email, base_dir)
    adapter = MetadataAdapter(
        qm.metadata_all(user_email=user_email, base_dir=base_dir).payload
    )
    kwargs: dict[str, Any] = {}
    if top_n is not None:
        kwargs["top_n"] = top_n
    return query_plan.build_model_query_plan(
        adapter,
        request,
        requested_fields=requested_fields,
        refresh_fn=refresh_fn,
        enum_fn=enum_fn,
        **kwargs,
    )


def run_flow(
    request: str,
    *,
    user_email: str,
    base_dir: Path | None = None,
    requested_fields: Sequence[str] = (),
    limit: int | None = None,
    order_by: list[dict] | None = None,
    offset: int | None = None,
    result_dir: Path | None = None,
    query_manager: QueryManager | None = None,
) -> dict:
    """一体化：规划 + planned 数据集查询时按 query_template 执行一次取数。

    非 planned（clarify/blocked/chart_uuid 等）合同原样返回交调用方处置。
    planned 时把 limit/order_by/offset 填入 query_template 再执行（未传则保持 None、
    执行时被剔除 → 沿用后端默认：limit=20、无排序、offset=0）。

    Args:
        limit: 返回行数上限；不传则用后端默认（20）。
        order_by: 排序，形态 [{"field": "<结果字段>", "desc": bool}]（与 query_simple 一致）。
        offset: 分页偏移；不传则后端默认 0。
        result_dir: 预留的结果落盘目录（当前未使用，落盘能力延后）。
    """
    qm = query_manager or QueryManager()
    contract = run_plan(
        request,
        user_email=user_email,
        base_dir=base_dir,
        requested_fields=requested_fields,
        query_manager=qm,
    )
    if contract.get("query_mode") != "dataset_query" or contract.get("status") != "planned":
        return contract
    execution_ref = contract.get("execution_ref") or {}
    template = execution_ref.get("query_template")
    if isinstance(template, dict):
        # 把用户/Agent 指定的 limit/order_by/offset 填进模板（未指定的保持 None，
        # run_query_template 会剔除 None 键 → 沿用后端默认）
        changed = False
        if limit is not None:
            template["limit"] = limit
            changed = True
        if offset is not None:
            template["offset"] = offset
            changed = True
        if order_by:
            template["orderBy"] = order_by
            changed = True
        # 仅当模板被改写时重挂完整性摘要，保持「规划=执行」自洽（attach 覆盖整个 contract）
        if changed:
            plan_integrity.attach(contract)
    run_result = qm.run_query_template(execution_ref)
    return {
        **contract,
        "result": run_result,
        "execution_notes": list(_FLOW_DEFERRED_NOTES),
    }
