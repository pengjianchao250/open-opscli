"""query 场景 REST 路由：取数模块全量 CLI 指令的 HTTP 形态。

与 CLI（opscli.query.commands.cli）/ MCP（opscli.mcp.tools.query）共用
QueryManager 与规划器内核，本层只做 HTTP 合同转换：
- 文件传参（--payload/--query-file/stdin）→ JSON 请求体
- 结果落盘（--result-file/--save-result/--output）→ 全量 JSON 响应，
  大结果集由调用方用 limit/offset 分页
- skills_dir / result_dir 等服务端本地路径不对外暴露
- CLI 的信封字段 command 与退出码 → HTTP 状态码 + success/data/error 信封

同步业务内核统一放 run_in_threadpool 执行，避免阻塞事件循环。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from opscli.api.deps import (
    build_query_manager,
    get_credential_dir,
    require_authenticated_user,
)
from opscli.api.errors import query_exception_response, success_response
from opscli.api.schemas.query import (
    ChartRunRequest,
    QueryBuildRequest,
    QueryFlowRequest,
    QueryIntentMatchRequest,
    QueryPlanRequest,
    QueryRunRequest,
    QuerySimpleRequest,
)
from opscli.query.services.result_errors import extract_inner_result_error

router = APIRouter(
    prefix="/api/v1",
    tags=["query"],
    dependencies=[Depends(require_authenticated_user)],
)


# ── 同步业务调用（模块级函数，便于测试按端点打桩）──────────────────────


def _query_plan(payload: QueryPlanRequest, *, user_email: str) -> dict[str, Any]:
    """规划器内核化入口：自然语言 → query_plan_model_contract_v2。"""
    from opscli.query.services.planner import run_plan

    return run_plan(
        payload.request,
        user_email=user_email,
        base_dir=get_credential_dir(),
        requested_fields=payload.requested_fields,
        top_n=payload.top_n,
        query_manager=build_query_manager(),
    )


def _query_flow(payload: QueryFlowRequest, *, user_email: str) -> dict[str, Any]:
    """一体化取数：只规划一次；单币种执行一次，多币种逐项取数。"""
    from opscli.query.services.planner import run_flow

    order_by = [item.model_dump() for item in payload.order_by] if payload.order_by else None
    return run_flow(
        payload.request,
        user_email=user_email,
        base_dir=get_credential_dir(),
        requested_fields=payload.requested_fields,
        limit=payload.limit,
        order_by=order_by,
        offset=payload.offset,
        query_manager=build_query_manager(),
    )


def _query_preferences() -> list[dict]:
    """当前用户的图表字段偏好设置。"""
    return build_query_manager().user_preferences()


def _query_metadata(
    *,
    dataset: str | None,
    table_id: int | None,
    all_fields: bool,
    user_email: str,
) -> dict[str, Any]:
    """数据集 metadata；all_fields 时返回全量授权数据集全部字段（经用户级缓存）。"""
    manager = build_query_manager()
    if all_fields:
        result = manager.metadata_all(user_email=user_email, base_dir=get_credential_dir())
        datasets = result.payload.get("datasets") or []
        fields = result.payload.get("fields") or []
        data: dict[str, Any] = {
            "datasets": datasets,
            "fields": fields,
            "dataset_count": len(datasets),
            "field_count": len(fields),
            "stale": result.stale,
            "from_cache": result.from_cache,
        }
        if not fields:
            data["hint"] = "field_count=0：当前后端未返回全量字段，可能是取数后端未上线 include_all_fields（Phase 0）"
        return data
    return manager.metadata(dataset_alias=dataset, table_id=table_id).to_dict()


def _query_catalog(*, source: str, fallback_local: bool) -> dict[str, Any]:
    """数据集业务语义索引（dataset catalog）。"""
    return build_query_manager().catalog(source=source, fallback_local=fallback_local)


def _query_intent_match(payload: QueryIntentMatchRequest) -> dict[str, Any]:
    """自然语言需求匹配 dataset catalog intents。"""
    return build_query_manager().intent_match(
        query=payload.query,
        source=payload.source,
        fallback_local=payload.fallback_local,
    )


def _query_run(payload: QueryRunRequest) -> dict[str, Any]:
    """执行已构造完整的 query payload。"""
    return build_query_manager(timeout=payload.timeout).run_payload(
        payload.payload,
        intent_code=payload.intent_code,
        selection_source=payload.selection_source,
        match_record_id=payload.match_record_id,
    )


def _query_build(payload: QueryBuildRequest) -> dict[str, Any]:
    """基于简化参数构造标准 query payload，run=true 时立即执行。"""
    manager = build_query_manager(timeout=payload.timeout)
    kwargs: dict[str, Any] = {
        "dataset_alias": payload.dataset,
        "table_id": payload.table_id,
        "dimensions": payload.dimensions,
        "metrics": payload.metrics,
        # REST 合同用结构化 where（list[dict]），构造层以 where_json 字符串承接
        "where_json": json.dumps(payload.where, ensure_ascii=False) if payload.where is not None else None,
        "having_conditions": payload.having,
        "order_by": payload.order_by,
        "limit": payload.limit,
        "offset": payload.offset,
        "dry_run": payload.dry_run,
        "data_comparison": payload.data_comparison,
        "global_currency": payload.global_currency,
    }
    if payload.run:
        return manager.build_and_run(**kwargs)
    return manager.build(**kwargs)


def _query_simple(payload: QuerySimpleRequest) -> tuple[dict[str, Any], dict | None]:
    """构造 simple query payload 并可选执行；返回 (结果, 内层失败信息)。"""
    manager = build_query_manager(timeout=payload.timeout)
    spec = payload.payload
    kwargs: dict[str, Any] = {
        "table_id": payload.table_id,
        "dataset_alias": payload.dataset,
        "dimensions": spec.dimensions,
        "metrics": spec.metrics,
        "filters": spec.filters,
        "data_comparison": spec.data_comparison,
        "order_by": spec.order_by,
        "limit": spec.limit,
        "offset": spec.offset,
        "dry_run": spec.dry_run,
        # CLI 语义：显式入参优先于 payload 内的 globalCurrency
        "global_currency": payload.global_currency or spec.global_currency,
        "validate_fields": True,
    }
    if payload.run:
        result = manager.build_simple_and_run(
            intent_code=payload.intent_code,
            selection_source=payload.selection_source,
            match_record_id=payload.match_record_id,
            **kwargs,
        )
        return result, extract_inner_result_error(result)
    return manager.build_simple(**kwargs), None


def _chart_bundle(chart_uuid: str) -> dict[str, Any]:
    """图表查询结构（不执行）。"""
    return build_query_manager().fetch_chart_bundle(chart_uuid)


def _chart_run(chart_uuid: str, payload: ChartRunRequest) -> dict[str, Any]:
    """执行图表全部子查询并合并输出。"""
    return build_query_manager(timeout=payload.timeout).run_chart_queries(
        chart_uuid, dry_run=payload.dry_run
    )


def _chart_doc(chart_uuid: str) -> dict[str, Any]:
    """图表 API 调用 Markdown 文档（markdown 字段随响应返回，不写服务端文件）。"""
    return build_query_manager().generate_chart_doc(chart_uuid)


# ── 端点 ────────────────────────────────────────────────────────────


@router.post("/query/plan")
async def query_plan(
    payload: QueryPlanRequest,
    user_email: str = Depends(require_authenticated_user),
) -> JSONResponse:
    """自然语言请求 → 规划合同（只规划不执行）。"""
    try:
        result = await run_in_threadpool(_query_plan, payload, user_email=user_email)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.post("/query/flow")
async def query_flow(
    payload: QueryFlowRequest,
    user_email: str = Depends(require_authenticated_user),
) -> JSONResponse:
    """执行一次自然语言取数规划，并在可执行时返回查询结果。"""
    try:
        result = await run_in_threadpool(_query_flow, payload, user_email=user_email)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.get("/query/preferences")
async def query_preferences() -> JSONResponse:
    """查询当前用户的图表字段偏好设置（维度/指标）。"""
    try:
        result = await run_in_threadpool(_query_preferences)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.get("/query/metadata")
async def query_metadata(
    dataset: str | None = Query(default=None, max_length=128),
    table_id: int | None = Query(default=None, ge=1),
    all_fields: bool = Query(default=False),
    user_email: str = Depends(require_authenticated_user),
) -> JSONResponse:
    """读取数据集 metadata；all_fields=true 返回全量授权数据集全部字段。"""
    try:
        data = await run_in_threadpool(
            _query_metadata,
            dataset=dataset,
            table_id=table_id,
            all_fields=all_fields,
            user_email=user_email,
        )
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(data)


@router.get("/query/catalog")
async def query_catalog(
    source: Literal["remote", "local"] = Query(default="remote"),
    fallback_local: bool = Query(default=True),
) -> JSONResponse:
    """读取数据集业务语义索引（dataset catalog），默认远端优先。"""
    try:
        result = await run_in_threadpool(
            _query_catalog, source=source, fallback_local=fallback_local
        )
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.post("/query/intents/match")
async def query_intent_match(payload: QueryIntentMatchRequest) -> JSONResponse:
    """将自然语言需求匹配到 dataset catalog intents。"""
    try:
        result = await run_in_threadpool(_query_intent_match, payload)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.post("/query/run")
async def query_run(payload: QueryRunRequest) -> JSONResponse:
    """执行完整 query payload 并转发到服务端 cli-query。"""
    try:
        result = await run_in_threadpool(_query_run, payload)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.post("/query/build")
async def query_build(payload: QueryBuildRequest) -> JSONResponse:
    """基于简化参数构造标准 query payload，run=true 时构造后立即执行。"""
    try:
        result = await run_in_threadpool(_query_build, payload)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.post("/query/simple")
async def query_simple(payload: QuerySimpleRequest) -> JSONResponse:
    """构造 simple query payload 并可选执行（run=true 时默认带字段校验）。

    取数服务可能在 HTTP 200 信封内返回执行失败（内层 success=false），
    此时外层响应保持 200 但 success=false，错误明细在 error 字段——
    与 CLI 的输出语义一致，调用方必须检查 success 字段。
    """
    try:
        result, inner_error = await run_in_threadpool(_query_simple, payload)
    except Exception as exc:
        return query_exception_response(exc)
    if inner_error:
        return JSONResponse(
            {
                "success": False,
                "data": result,
                "error": inner_error,
            }
        )
    return success_response(result)


@router.get("/charts/{chart_uuid}")
async def query_chart(chart_uuid: str) -> JSONResponse:
    """通过 chart_uuid 获取图表查询结构（不执行）。"""
    try:
        result = await run_in_threadpool(_chart_bundle, chart_uuid)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.post("/charts/{chart_uuid}/run")
async def query_chart_run(chart_uuid: str, payload: ChartRunRequest) -> JSONResponse:
    """执行图表全部子查询并合并输出；dry_run=true 时仅生成 SQL。"""
    try:
        result = await run_in_threadpool(_chart_run, chart_uuid, payload)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)


@router.get("/charts/{chart_uuid}/doc")
async def query_chart_doc(chart_uuid: str) -> JSONResponse:
    """通过 chart_uuid 生成图表 API 调用 Markdown 文档。"""
    try:
        result = await run_in_threadpool(_chart_doc, chart_uuid)
    except Exception as exc:
        return query_exception_response(exc)
    return success_response(result)
