#!/usr/bin/env python3
"""规划器内核入口：组装缓存/适配器/规划器/执行。

对外暴露两个统一入口，供 CLI（opscli query plan/flow）与 MCP（query_plan/query_flow）复用：
- run_plan：自然语言请求 → query_plan_model_contract_v2（只规划不执行）。
- run_flow：一体化——只规划一次；单币种执行一次，多币种按 query_templates 逐项取数。

数据源为后端 query-metadata（经用户级元数据缓存）。元数据未就绪时的刷新（refresh_fn）
与平台/组件权限枚举（enum_fn）作为回调注入规划器，替代旧 Skill 的 subprocess 调用。

依赖方向（铁律2）：仅依赖 opscli.query.* + 标准库，禁止 import opscli.mcp。
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from opscli.query.services.manager import QueryManager
from opscli.query.services.metadata_cache import invalidate_metadata_cache
from opscli.query.services.planner import enum_cache, evidence_contract, plan_integrity, query_plan
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


_AUTO_COMPLETE_LIMIT_CAP = 5000
# 排序兜底重查时 limit 的放大倍数与硬上限（与 skill run_query.py:36-37 数值一致，原样迁入）
_ORDER_REQUERY_MULTIPLIER = 3
_ORDER_REQUERY_LIMIT_CAP = 5000
# 全量结果落盘 + 预览限幅（K2 内核化）：与 skill run_query.py 常量一致——
# 默认预览行数（源 --preview-rows 默认值，:557）、单字段字符串截断长度（:537，超长加"…"）
_RESULT_PREVIEW_ROWS = 20
_PREVIEW_STRING_TRUNC_LEN = 80


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


def _extract_currency(response: dict) -> str | None:
    """从返回 JSON 提取本次实际生效的币种代码（兼容多层形状）。

    与 skill run_query.py:_extract_currency（:374-390）等价迁入，逐字照抄取值逻辑：
    服务端在 `meta.currency` 声明本次查询金额使用的币种（ISO 4217，如 CNY/USD），
    实测存在 `data.result.meta`、`data.meta` 和顶层 `meta` 三种形状，逐层兜底取
    第一个非空字符串。该值必须进 run_flow 的 result_disclosures：Agent 的金额结论
    要据此声明币种，只落在全量结果文件里会导致模型为了拿币种额外读一次文件，
    实际上往往被跳过。
    """
    for path in (("data", "result", "meta"), ("data", "meta"), ("meta",)):
        node: Any = response
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            currency = node.get("currency")
            if isinstance(currency, str) and currency.strip():
                return currency.strip().upper()
    return None


def _extract_result_page(result: Any) -> tuple[list[dict], int | None]:
    """从 simple 查询结果中提取当前页行与服务端总行数。"""
    root = result if isinstance(result, dict) else {}
    rows: list[dict] = []
    for path in (("data", "result", "data"), ("result", "data"), ("data",)):
        node: Any = root
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, list):
            rows = [row for row in node if isinstance(row, dict)]
            break

    containers: list[dict] = []
    data = root.get("data")
    nested_result = data.get("result") if isinstance(data, dict) else None
    for value in (
        nested_result.get("meta") if isinstance(nested_result, dict) else None,
        nested_result,
        data,
        root.get("meta"),
        root,
    ):
        if isinstance(value, dict):
            containers.append(value)
    for key in ("totalCount", "total_count", "total"):
        for container in containers:
            value = container.get(key)
            if value is None:
                continue
            try:
                return rows, int(value)
            except (TypeError, ValueError):
                continue
    return rows, None


def _sort_value(value: Any) -> tuple[int, float | str]:
    """排序键归一：数值优先按数值比较，None 沉底。

    与 skill run_query.py:_sort_value（:393-403）等价迁入，原样照抄不做改动。
    """
    if value is None:
        return (2, "")
    if isinstance(value, (int, float)):
        return (0, float(value))
    text = str(value).replace(",", "")
    try:
        return (0, float(text))
    except ValueError:
        return (1, str(value))


def _is_monotonic(rows: list[dict], field: str, desc: bool) -> bool:
    """校验结果行是否按声明字段单调（服务端排序是否真的生效）。

    与 skill run_query.py:_is_monotonic（:406-412）等价迁入。direction 入参改为
    内核既有的 desc 布尔——内核 orderBy 形态是 {field,desc}，与 skill 的
    {field,direction} 不同（见 query_plan.py:1274 注记，两处不可直接复制粘贴），
    比较逻辑本身（reverse 排序后逐值比对）保持等价。
    """
    values = [_sort_value(row.get(field)) for row in rows if field in row]
    if len(values) < 2:
        return True
    return values == sorted(values, reverse=desc)


def _write_result_rows(run_result: dict, rows: list[dict]) -> None:
    """把本地重排/加量重查修正后的行、或落盘后的预览行写回 run_result 的原始行位置。

    kernel 的 run_flow 只有 result 一个通道把服务端结果带给调用方（不像 skill
    另有 preview_rows/全量落盘两条通道），因此排序兜底修正的行、以及 result_dir
    落盘后要回传的预览行，都必须写回 result 嵌套结构，否则 result_disclosures
    声明的行数/顺序会与 result 实际内容不一致。复用 _extract_result_page 相同的
    三条兜底路径定位行列表所在容器。
    """
    if not isinstance(run_result, dict):
        return
    for path in (("data", "result", "data"), ("result", "data"), ("data",)):
        node: Any = run_result
        for key in path[:-1]:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, dict) and isinstance(node.get(path[-1]), list):
            node[path[-1]] = rows
            return


def _compact_preview(rows: list[dict], preview_rows: int) -> list[dict]:
    """预览行截断：只取前 N 行，超长字符串截断防撑爆调用方上下文。

    与 skill run_query.py:_compact_preview（:531-541）等价迁入，字段截断长度
    （_PREVIEW_STRING_TRUNC_LEN=80）与源实现一致，原样照抄不做改动。
    """
    preview = []
    for row in rows[:preview_rows]:
        preview.append(
            {
                key: (
                    value[:_PREVIEW_STRING_TRUNC_LEN] + "…"
                    if isinstance(value, str) and len(value) > _PREVIEW_STRING_TRUNC_LEN
                    else value
                )
                for key, value in row.items()
            }
        )
    return preview


def _apply_order_fallback(
    qm: QueryManager,
    template: dict,
    rows: list[dict],
    order_by: list[dict],
    total: int | None,
    limit: object,
) -> tuple[list[dict], dict | None]:
    """orderBy 未生效时的本地兜底（已知服务端缺陷的过渡方案）。

    与 skill run_query.py:_apply_order_fallback（:415-476）等价迁入：
    - 无 limit：手上就是全量，单调即可证明服务端排序生效，否则本地重排；
    - 有 limit：单调**不能**作为判据——服务端整段忽略 orderBy 时返回的是自然序
      切片，而常量序列（如整片都是同一个值）天然单调，判据会静默放过；因此有
      limit 时一律按总行数取全量后本地排序取前 N。
    重查用内核既有的 qm.run_query_template（对应 skill 版对 _run_opscli 的二次
    调用），不涉及 skill 版 intent_code/selection_source 透传（kernel 执行通道
    本就不支持该归因参数，非本次迁移范围）。

    Args:
        limit: 判断"是否存在真实分页约束"的显式依据，调用方必须传入——不可让本
            函数自行读 template.get("limit")：run_flow 的服务端默认分页补齐
            （auto-complete）会就地把 template["limit"] 改写成"取全量"的内部
            放大值，那不是用户/规划器的真实 TopN 约束；调用方在
            auto_complete_applied 时必须传 None，让本函数按"无 limit"语义走
            本地重排，避免误判成 TopN 场景、多发一次未声明的加量重查（复现场景
            见 tests/query/planner/test_entry.py 的审查回归用例）。
    返回 (修正后的行, 兜底披露信息或 None)。
    """
    primary = order_by[0]
    field = primary.get("field")
    desc = bool(primary.get("desc"))
    direction = "DESC" if desc else "ASC"  # 仅用于披露文案，口径与 skill 版一致
    if not limit and _is_monotonic(rows, field, desc):
        return rows, None
    note: dict[str, Any] = {
        "order_fallback_applied": True,
        "order_field": field,
        "direction": direction,
    }
    if not limit:
        rows = sorted(rows, key=lambda row: _sort_value(row.get(field)), reverse=desc)
        note["strategy"] = "local_resort"
        return rows, note
    # 有 limit：放大固定倍数仍是在错误的行里挑，必须按服务端报告的总行数取全量。
    # total 不可用时退回倍数放大，并在 strategy 里如实标注为尽力而为。
    try:
        span = int(total) if total is not None else 0
    except (TypeError, ValueError):
        span = 0
    exact = span > 0
    if not exact:
        span = int(limit) * _ORDER_REQUERY_MULTIPLIER
    requery_limit = min(span, _ORDER_REQUERY_LIMIT_CAP)
    requery_template = {**template, "limit": requery_limit}
    requery_result = qm.run_query_template({"query_template": requery_template})
    wide_rows, _wide_total = _extract_result_page(requery_result)
    wide_rows = sorted(wide_rows, key=lambda row: _sort_value(row.get(field)), reverse=desc)
    corrected = wide_rows[: int(limit)]
    # 核对之后才能下结论：重查是为了「验证」而不是「假定」服务端排序失效。
    # 首查结果与本地算出的 Top N 一致时说明服务端排序本就生效，
    # 此时报 order_fallback_applied 会让 Agent 向用户披露一个并不存在的兜底。
    if corrected == rows:
        return rows, None
    note["strategy"] = f"requery_limit_{requery_limit}_then_local_sort"
    # 取样口径必须可审计：未按全量重查时结论不能自称精确 Top N
    note["covers_full_result"] = bool(exact and span <= _ORDER_REQUERY_LIMIT_CAP)
    return corrected, note


def _make_callbacks(qm: QueryManager, user_email: str, base_dir: Path | None):
    """构造注入规划器的 refresh_fn / enum_fn 回调。

    - refresh_fn：失效用户级元数据缓存并重取全量 payload（替代 subprocess skills upgrade）。
    - enum_fn：对组件表执行一次 simple 查询并抽取字段枚举值（替代 subprocess query simple）。
      实时枚举异常（网络/超时/服务端错误）时先尝试本地磁盘缓存降级（TTL 24h，
      与 Skill 版同址），命中则返回陈旧值并把年龄（小时）记入 stale_hits 供
      run_plan 统一披露；缓存也未命中则把异常继续抛给 query_plan，维持
      现行 fail-closed 行为（行为不回归）。

    Returns:
        (refresh_fn, enum_fn, stale_hits)：stale_hits 是本次调用过程中命中缓存
        降级的年龄列表（小时），run_plan 据此拼装"来自缓存"的中文披露。
    """
    stale_hits: list[float] = []

    def refresh_fn() -> dict:
        # 元数据未就绪：失效缓存后重取一次全量元数据
        invalidate_metadata_cache(base_dir=base_dir, user_email=user_email)
        return qm.metadata_all(user_email=user_email, base_dir=base_dir).payload

    def enum_fn(table_id: Any, field_name: str, *, limit: int) -> list[str]:
        # 权限枚举：复用内核 simple 查询取组件表某字段的可选值
        try:
            run = qm.build_simple_and_run(
                table_id=int(table_id),
                dimensions=[{"field": field_name, "alias": field_name}],
                limit=limit,
            )
            values = _extract_enum_values(run.get("result"), field_name)
        except Exception:  # noqa: BLE001 实时枚举失败先尝试缓存降级，缓存也无则原样抛出
            cached = enum_cache.get(table_id, field_name, base_dir=base_dir)
            if cached is None:
                raise
            age_hours = enum_cache.get_age_hours(table_id, field_name, base_dir=base_dir)
            stale_hits.append(age_hours if age_hours is not None else 0.0)
            return cached
        if values:
            # 实时枚举成功：写入本地缓存供下次超时/失败时降级兜底（TTL 24h）
            enum_cache.put(table_id, field_name, values, base_dir=base_dir)
        return values

    return refresh_fn, enum_fn, stale_hits


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
    refresh_fn, enum_fn, stale_hits = _make_callbacks(qm, user_email, base_dir)
    adapter = MetadataAdapter(
        qm.metadata_all(user_email=user_email, base_dir=base_dir).payload
    )
    kwargs: dict[str, Any] = {}
    if top_n is not None:
        kwargs["top_n"] = top_n
    contract = query_plan.build_model_query_plan(
        adapter,
        request,
        requested_fields=requested_fields,
        refresh_fn=refresh_fn,
        enum_fn=enum_fn,
        **kwargs,
    )
    if stale_hits:
        # 本次调用中至少有一次权限枚举走了本地缓存降级：如实披露，
        # 避免 Agent 把降级值当实时数据转述给用户（取最旧的一次年龄，最保守）
        model_view = contract.get("model_view")
        if isinstance(model_view, dict):
            model_view.setdefault("component_filter_disclosures_zh", []).append(
                f"部分权限枚举值来自约 {max(stale_hits):.1f} 小时前本地缓存"
                "（实时枚举失败后的降级兜底），非实时数据。"
            )
    return contract


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
    """一体化规划并执行；多币种请求只规划一次、逐币种独立取数。

    非 planned（clarify/blocked/chart_uuid 等）合同原样返回交调用方处置。
    单币种按 query_template 执行；多币种按 query_templates 顺序逐项执行，禁止
    使用本地或外部汇率生成其他币种结果。

    Args:
        limit: 返回行数上限；不传时自动补齐服务端默认页（最多 5000 行）。
        order_by: 排序，形态 [{"field": "<结果字段>", "desc": bool}]（与 query_simple 一致）。
        offset: 分页偏移；不传则后端默认 0。
        result_dir: 传入时把全量结果落盘到该目录（文件名 query_result_<秒级时间戳>.json），
            返回的 result 只保留前 _RESULT_PREVIEW_ROWS 行预览，result_disclosures 附带
            full_result_file 指向落盘文件（落盘失败则为 None + full_result_file_error）；
            不传该参数时行为与之前完全一致（result 为完整服务端结果，不落盘）。
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
    templates = execution_ref.get("query_templates")
    if not isinstance(templates, list) or len(templates) < 2:
        return _execute_planned_contract(
            contract,
            query_manager=qm,
            limit=limit,
            order_by=order_by,
            offset=offset,
            result_dir=result_dir,
        )

    # 多币种列表已经纳入规划摘要；拆分执行前先校验，防止任一币种或范围被改写。
    if not plan_integrity.verify(contract):
        raise ValueError("多币种规划完整性校验失败，请重新运行规划器")
    currency_results: list[dict[str, Any]] = []
    for template in templates:
        if not isinstance(template, dict):
            raise ValueError("多币种规划包含无效查询模板")
        requested_currency = str(template.get("globalCurrency") or "").upper()
        if not requested_currency:
            raise ValueError("多币种规划模板缺少 globalCurrency")

        # 子合同只保留当前币种模板并重新封存摘要，使单币种执行链的字段、分页、
        # 排序、落盘与证据合同能力可以原样复用，不产生第二次规划。
        child_contract = deepcopy(contract)
        child_execution = child_contract["execution_ref"]
        child_execution["query_template"] = deepcopy(template)
        child_execution.pop("query_templates", None)
        plan_integrity.attach(child_contract)
        child_result_dir = (
            result_dir / f"currency_{requested_currency.lower()}"
            if result_dir is not None
            else None
        )
        child_result = _execute_planned_contract(
            child_contract,
            query_manager=qm,
            limit=limit,
            order_by=order_by,
            offset=offset,
            result_dir=child_result_dir,
        )
        returned_currency = (child_result.get("result_disclosures") or {}).get("currency")
        currency_results.append(
            {
                "requested_currency": requested_currency,
                "returned_currency": returned_currency,
                "currency_matches_request": returned_currency == requested_currency,
                "result": child_result,
            }
        )

    currency_validation_passed = all(
        item["currency_matches_request"] for item in currency_results
    )
    return {
        **contract,
        "multi_currency": True,
        "requested_global_currencies": [
            str(item.get("globalCurrency") or "").upper() for item in templates
        ],
        "currency_results": currency_results,
        "comparison_contract": {
            "service_queries_complete": len(currency_results) == len(templates),
            "currency_validation_passed": currency_validation_passed,
            "comparison_ready": False,
            "alignment_validation_required": currency_validation_passed,
            "rules_zh": [
                "实际币种只认各结果 result_disclosures.currency；与请求不一致时停止金额对比并披露差异。",
                "读取各 full_result_file 后，先确认共同维度键和非金额指标一致，再按共同维度关联。",
                "金额只使用对应币种的服务端查询结果；禁止外部汇率、模型汇率或本地换算。",
            ],
        },
    }


def _execute_planned_contract(
    contract: dict,
    *,
    query_manager: QueryManager,
    limit: int | None = None,
    order_by: list[dict] | None = None,
    offset: int | None = None,
    result_dir: Path | None = None,
) -> dict:
    """执行一个已规划的单币种合同，并附加分页、排序、证据与落盘披露。"""
    qm = query_manager
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
    # 原始 limit 披露：必须在服务端默认分页补齐（auto-complete）就地改写
    # template["limit"] 之前捕获，否则披露值会变成 auto-complete 算出的内部放大值
    # （详见下方 auto_complete_applied 分支），而非用户/规划器的真实分页口径——
    # 与 skill run_query.py 的 disclosures["limit"] = payload.get("limit")
    # （run_query.py:675）语义等价：skill 侧 _complete_server_paged_rows 用
    # dict(payload) 拷贝重查、不回写原 payload，本就恒为用户输入值。
    original_limit = template.get("limit") if isinstance(template, dict) else None
    run_result = qm.run_query_template(execution_ref)
    rows, total = _extract_result_page(run_result)
    auto_complete_applied = False
    if (
        limit is None
        and offset in (None, 0)
        and total is not None
        and total > len(rows)
        and isinstance(template, dict)
        # 规划器把 NL 解析出的 TopN/排序行数限制（如"前3名"）直接写入了
        # template["limit"]；此时 run_flow 形参 limit 虽为 None（Agent 未显式传
        # --limit），但模板已有的 limit 是用户意图的一部分，必须与显式 limit
        # 同等尊重——否则 auto-complete 会把它当成"服务端默认分页"就地放大，
        # 返回全量而不是用户要的前 N 条。只有模板本身也未下发 limit 时才允许
        # auto-complete 介入补齐服务端默认分页。
        and template.get("limit") is None
    ):
        template["limit"] = min(total, _AUTO_COMPLETE_LIMIT_CAP)
        plan_integrity.attach(contract)
        run_result = qm.run_query_template(execution_ref)
        rows, total = _extract_result_page(run_result)
        auto_complete_applied = True
    result_disclosures: dict[str, Any] = {
        "row_count_returned": len(rows),
        "total_count": total,
        "truncated": total is not None and len(rows) < total,
        "auto_complete_applied": auto_complete_applied,
        "limit": original_limit,
    }
    # 币种披露：meta.currency 是服务端本次生效币种的唯一权威来源。有值必须让模型
    # 原样声明；没有值时明确要求「只能说未声明」，堵住按字段名后缀或经验猜币种的
    # 路径——与 skill run_query.py:681-690 逐字照抄迁入（文案不改一字）。取值用
    # 最终 run_result（已含 auto-complete 补齐，若触发过），与 K3 证据合同
    # 「单通道、读最终态」的既定架构决策一致（源实现用首查陈旧快照，币种字段
    # 不随分页变化，两者取值结果等价，仅快照新旧不同，非行为回归）。
    currency = _extract_currency(run_result)
    result_disclosures["currency"] = currency
    result_disclosures["currency_disclosure_zh"] = (
        f"本次金额币种为 {currency}：结论首句、结果表头和导出口径页必须写明该币种；"
        "禁止参考外部汇率折算或跨币种相加，需要其他币种时重新发起带币种意图的查询"
        if currency
        else "本次返回未声明币种：只能如实说明未声明，禁止按字段名后缀、数据集习惯或历史会话推断具体货币"
    )
    # orderBy 本地兜底：effective_order_by 取模板最终生效值（而非 run_flow 的
    # order_by 形参），与 skill run_query.py 读 payload.get("orderBy") 的口径一致，
    # 覆盖「排序来自规划器 NL 解析、未经 run_flow 显式传参」的场景。
    effective_order_by = template.get("orderBy") if isinstance(template, dict) else None
    order_note: dict[str, Any] | None = None
    if effective_order_by and rows:
        # auto-complete 已把 template["limit"] 就地改写成取全量的内部放大值
        # （见上方 auto_complete_applied 分支），此时不代表真实分页约束，必须
        # 按「无 limit」语义传给 _apply_order_fallback，否则会被误判成 TopN
        # 场景、对已经取到的全量结果再多发一次未声明的加量重查（审查员实证复现：
        # limit/offset 未传 + orderBy 已下发 + 触发 auto-complete 时，
        # template.get("limit") 会被污染成 auto-complete 算出的放大值）。
        effective_limit = (
            None if auto_complete_applied
            else (template.get("limit") if isinstance(template, dict) else None)
        )
        rows, order_note = _apply_order_fallback(
            qm, template, rows, effective_order_by, total, effective_limit
        )
        if order_note:
            _write_result_rows(run_result, rows)
            result_disclosures["order_fallback"] = order_note
            # 重查窗口未覆盖全量时结论不能自称精确 Top N，必须把口径差异一并交代
            partial = "requery" in order_note["strategy"] and not order_note.get(
                "covers_full_result"
            )
            result_disclosures["order_disclosure_zh"] = (
                "服务端排序未生效（已知缺陷），本执行器已"
                + (
                    "按总行数取全量后本地排序取前N"
                    if "requery" in order_note["strategy"]
                    else "本地重排"
                )
                + "，结论中必须披露该兜底行为"
                + (
                    "；本次重查窗口未覆盖全部结果，前N可能不精确，必须如实声明"
                    if partial
                    else ""
                )
            )
            # 本地重排后行数已按 limit 切片，披露口径必须同步刷新
            result_disclosures["row_count_returned"] = len(rows)
    if effective_order_by and not order_note:
        result_disclosures["order_disclosure_zh"] = (
            f"排序已生效：按 {effective_order_by[0]['field']} "
            f"{'DESC' if effective_order_by[0].get('desc') else 'ASC'}"
        )
    # 证据合同（K3 内核化）：与 skill run_query.py 内嵌证据合同的接入位置一致——
    # 排在排序兜底修正之后、落盘/预览限幅之前，此时 run_result 已是"最终"行状态
    # （auto-complete 补齐 + 排序兜底回写均已生效）。与源实现的差异：源实现用
    # 首查得到的原始 response（从不随 auto-complete/排序兜底重查而更新，见任务
    # K3 报告差异对照表）；kernel 沿用 K1/K2 已确立的"单通道、读最终态"架构，
    # 直接喂最终 run_result，证据更完整而非源实现的陈旧快照。构建失败不阻断
    # 查询结果，仅记录 evidence_contract_error（与源实现 try/except 语义一致）。
    model_view = contract.get("model_view")
    dataset_name_zh = (
        str(model_view.get("dataset_name_zh", "")) if isinstance(model_view, dict) else ""
    )
    contract_evidence: dict[str, Any] | None = None
    evidence_contract_error: str | None = None
    try:
        contract_evidence = evidence_contract.build_evidence_contract(
            run_result, dataset_name_zh=dataset_name_zh
        )
    except Exception as error:  # noqa: BLE001 —— 证据合同失败不阻断查询结果
        evidence_contract_error = str(error)[:120]
    if result_dir is not None:
        # 全量结果落盘 + 预览限幅（K2 内核化，与 skill run_query.py:734-747/531-541 等价迁入）：
        # 此时 run_result 的嵌套行容器已与排序兜底修正后的 rows 一致（见上方
        # _write_result_rows 调用，未触发兜底时两者本就同步），落盘内容用这份最终 rows；
        # 返回给调用方的 result 只保留预览行，避免大结果集撑爆上下文。写盘失败（OSError，
        # 如目录不可写）不阻断查询，只在披露中如实说明，不静默吞掉也不中断整次查询。
        result_path = result_dir / f"query_result_{int(time.time())}.json"
        try:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(
                    {**run_result, "rows_after_auto_complete": rows},
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
            result_disclosures["full_result_file"] = str(result_path)
        except OSError as error:
            result_disclosures["full_result_file"] = None
            result_disclosures["full_result_file_error"] = str(error)[:160]
        _write_result_rows(run_result, _compact_preview(rows, _RESULT_PREVIEW_ROWS))
    elif len(rows) > _RESULT_PREVIEW_ROWS:
        # 未传 result_dir 时不做任何截断：调用方若忘记传 --result-dir，行数较大的
        # 结果会原样（最多 5000 行）塞进返回体却没有任何提示。这里加一条醒目披露，
        # 把"忘传参数导致静默过量"变成 Agent 可感知的信号（K5 修复轮：审查发现
        # SKILL.md/cli.md 只能在文档层面要求"必须传 --result-dir"，无法从代码层面
        # 兜底，遂在此补一条运行时警告）。
        result_disclosures["large_result_warning_zh"] = (
            f"本次返回 {len(rows)} 行且未传 --result-dir，全量行已进入返回体；"
            "行数较大时建议携带 --result-dir 落盘并只读预览。"
        )
    out = {
        **contract,
        "result": run_result,
        "result_disclosures": result_disclosures,
    }
    if contract_evidence is not None:
        out["evidence_contract"] = contract_evidence
    else:
        out["evidence_contract_error"] = evidence_contract_error
    return out
