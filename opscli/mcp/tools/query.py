"""Query 工具模块。

将 opscli query 子模块的核心能力暴露为 MCP 工具：
- query_metadata        — 查询数据集 metadata（维度/指标字段）
- query_build           — 构造标准 query payload（不执行）
- query_run             — 读取本地 payload 文件并执行查询
- query_build_and_run   — 构造 payload 并立即执行，一步返回结果
- query_chart           — 通过 chart_uuid 获取/执行图表查询

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

from .helpers import _err, _ok, _query_manager


async def query_metadata(
    dataset: str | None = None,
    table_id: int | None = None,
    skills_dir: str | None = None,
) -> dict:
    """查询指定数据集的 metadata（维度/指标字段列表）。不需要认证。

    Args:
        dataset:    数据集别名（与 table_id 二选一）
        table_id:   数据表 ID（与 dataset 二选一）
        skills_dir: 可选，自定义 Skills 目录（用于读取本地缓存 metadata）
    """
    try:
        result = _query_manager().metadata(
            dataset_alias=dataset,
            table_id=table_id,
            skills_dir=skills_dir,
        )
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(exc)


async def query_build(
    dataset: str | None = None,
    table_id: int | None = None,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
    where_conditions: list[str] | None = None,
    where_json: str | None = None,
    order_by: list[str] | None = None,
    having_conditions: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    dry_run: bool = False,
    data_comparison: str | None = None,
    output_path: str | None = None,
    skills_dir: str | None = None,
) -> dict:
    """基于简化参数构造标准 query payload（不执行查询）。不需要认证。

    Args:
        dataset:           数据集别名
        table_id:          数据表 ID
        dimensions:        维度字段列表
        metrics:           指标字段列表
        where_conditions:  过滤条件列表（字符串格式）
        where_json:        过滤条件 JSON 字符串（与 where_conditions 二选一）
        order_by:          排序字段列表
        having_conditions: HAVING 过滤条件列表
        limit:             返回行数限制（默认 20）
        offset:            分页偏移（默认 0）
        dry_run:           是否仅验证不执行
        data_comparison:   数据对比类型
        output_path:       可选，将 payload 写入指定文件路径
        skills_dir:        可选，自定义 Skills 目录
    """
    try:
        result = _query_manager().build(
            dataset_alias=dataset,
            table_id=table_id,
            dimensions=dimensions,
            metrics=metrics,
            where_conditions=where_conditions,
            where_json=where_json,
            order_by=order_by,
            having_conditions=having_conditions,
            limit=limit,
            offset=offset,
            dry_run=dry_run,
            data_comparison=data_comparison,
            output_path=output_path,
            skills_dir=skills_dir,
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def query_run(
    payload_path: str,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """读取本地 payload JSON 文件并转发至服务端执行查询。

    如果未提供 session_id / jwt，会自动尝试从本地加载已保存的凭据。

    Args:
        payload_path: 本地 payload JSON 文件路径
        session_id:   可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:          可选，已有 JWT 可直接使用（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    try:
        result = _query_manager(jwt=jw, session_id=sid).run(
            payload_path=payload_path
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def query_build_and_run(
    dataset: str | None = None,
    table_id: int | None = None,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
    where_conditions: list[str] | None = None,
    where_json: str | None = None,
    order_by: list[str] | None = None,
    having_conditions: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    dry_run: bool = False,
    data_comparison: str | None = None,
    skills_dir: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """构造 query payload 并立即执行，一步返回数据结果。

    如果未提供 session_id / jwt，会自动尝试从本地加载已保存的凭据。

    Args:
        dataset:           数据集别名
        table_id:          数据表 ID
        dimensions:        维度字段列表
        metrics:           指标字段列表
        where_conditions:  过滤条件列表
        where_json:        过滤条件 JSON 字符串
        order_by:          排序字段列表
        having_conditions: HAVING 过滤条件列表
        limit:             返回行数限制（默认 20）
        offset:            分页偏移（默认 0）
        dry_run:           是否仅验证不执行
        data_comparison:   数据对比类型
        skills_dir:        可选，自定义 Skills 目录
        session_id:        可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:               可选，已有 JWT（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    try:
        result = _query_manager(jwt=jw, session_id=sid).build_and_run(
            dataset_alias=dataset,
            table_id=table_id,
            dimensions=dimensions,
            metrics=metrics,
            where_conditions=where_conditions,
            where_json=where_json,
            order_by=order_by,
            having_conditions=having_conditions,
            limit=limit,
            offset=offset,
            dry_run=dry_run,
            data_comparison=data_comparison,
            skills_dir=skills_dir,
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def query_chart(
    chart_uuid: str,
    run: bool = False,
    dry_run: bool = False,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 chart_uuid 获取图表查询结构，可选立即执行所有查询。

    如果未提供 session_id / jwt，会自动尝试从本地加载已保存的凭据。

    Args:
        chart_uuid: 图表唯一标识
        run:        是否立即执行所有子查询（默认 False）
        dry_run:    是否仅验证不实际执行（默认 False）
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:        可选，已有 JWT（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    manager = _query_manager(jwt=jw, session_id=sid)
    try:
        if run or dry_run:
            # 执行所有子查询并返回完整结果
            result = manager.run_chart_queries(chart_uuid=chart_uuid, dry_run=dry_run)
            return _ok(result)
        else:
            # 仅获取图表查询结构，不执行
            chart_items = manager.fetch_chart_queries(chart_uuid)
            return _ok({"chart_uuid": chart_uuid, "queries": chart_items})
    except Exception as exc:
        return _err(exc)


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS = [
    query_metadata,
    query_build,
    query_run,
    query_build_and_run,
    query_chart,
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 query_* 工具。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
