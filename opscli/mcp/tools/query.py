"""Query 工具模块。

将 opscli query 子模块的核心能力暴露为 MCP 工具：
- query_spec_must_read  — ！！！【重要】读取查询规范文档（先检测 Skill 状态，未安装或已禁用时必须调用）
- query_metadata        — 查询数据集 metadata（维度/指标字段）
- query_catalog         — 读取数据集业务语义索引（自然语言匹配数据集）
- query_build           — 构造标准 query payload（不执行）
- query_run             — 读取本地 payload 文件并执行查询
- query_build_and_run   — 构造 payload 并立即执行，一步返回结果
- query_simple          — 基于简化参数直接执行查询（推荐优先使用）
- query_chart           — 通过 chart_uuid 获取/执行图表查询
- query_chart_doc       — 通过 chart_uuid 生成图表 API 调用 Markdown 文档

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

from .helpers import _err, _ok, _query_manager


async def query_spec_must_read() -> dict:
    """读取 ops-dataset-query 查询规范文档（QUERY_SPEC.md）。

    【调用前必须完成的检测步骤】
    1. 调用 skills_list MCP 工具，确认 ops-dataset-query Skill 是否存在且启用（disable != true）
    2. 如果 Skill 存在且启用 → 优先加载 Skill 目录内的 SKILL.md（文档更完整，含 17+ 规范文件）
    3. 如果 Skill 不存在 或 disable=true → 必须调用本工具，不可跳过

    【跳过规范的已知风险】
    - 库存字段误用 SUM 聚合（数据膨胀 2-10 倍）
    - 公式字段（ACOS/ROAS）二次聚合导致指标失真
    - dataComparison 缺少主周期导致 QS-EXE-005 报错
    - innerWhere 数据集误用 query_run 导致查询异常
    - 字段歧义未澄清导致错误维度/指标

    规范内容包括：
    - 10 条核心铁律（认证、优先级、innerWhere、公式字段、dataComparison 等）
    - 各查询工具（query_simple / query_build_and_run / query_run / query_chart）的参数规范与示例
    - 字段歧义澄清规则（数据集选择、公式字段、币种、人员歧义等）
    - 常见错误处理速查
    - 典型工作流（直接查询 / 意图匹配 / 图表分析 / 数据更新）

    【完整工作流说明】
    每次查询的标准流程：检测 Skill 状态 → 读取规范 → 执行查询 → 调用 feedback_submit 提交结果反馈。

    Returns:
        {"success": true, "data": {"spec": "<Markdown 文档内容>", "source": "<文件路径>"}}
        或 {"success": false, "error": "<错误原因>"}
    """
    from pathlib import Path

    # 规范文档内嵌在 opscli 包的模板目录中
    # Path(__file__) = opscli/mcp/tools/query.py
    # parents[2]     = opscli/（包根目录）
    spec_path = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "templates"
        / "ops-dataset-query"
        / "QUERY_SPEC.md"
    )

    if not spec_path.exists():
        return _err(
            FileNotFoundError(
                f"规范文档不存在：{spec_path}。请检查 opscli 安装是否完整。"
            )
        )

    try:
        content = spec_path.read_text(encoding="utf-8")
        return _ok({"spec": content, "source": str(spec_path)})
    except Exception as exc:
        return _err(exc)


async def query_metadata(
    dataset: str | None = None,
    table_id: int | None = None,
    skills_dir: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """查询指定数据集的 metadata（维度/指标字段列表）。

    指定 dataset 或 table_id 时，优先从远端拉取最新字段信息；
    远端失败则回退到本地缓存。未指定任何参数时返回本地数据集列表。
    远端查询需要认证，未提供 session_id/jwt 时自动从本地加载。

    Args:
        dataset:    数据集别名（与 table_id 二选一）
        table_id:   数据表 ID（与 dataset 二选一）
        skills_dir: 可选，自定义 Skills 目录（用于读取本地缓存 metadata）
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:        可选，已有 JWT（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    try:
        result = _query_manager(jwt=jw, session_id=sid).metadata(
            dataset_alias=dataset,
            table_id=table_id,
            skills_dir=skills_dir,
        )
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(exc)


async def query_catalog(
    skills_dir: str | None = None,
    source: str = "remote",
    fallback_local: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """读取数据集业务语义索引（dataset catalog）。默认远端优先。

    返回完整的 catalog JSON 结构，包含 version、intent_count、intents 数组和 query_strategy。
    用于自然语言需求匹配 intents 后选出候选数据集。

    Args:
        skills_dir: 可选，自定义 Skills 目录（用于读取本地缓存 catalog）
        source: 数据来源，remote（默认）或 local
        fallback_local: source=remote 时，远端失败是否回退本地缓存
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt: 可选，已有 JWT（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    try:
        result = _query_manager(jwt=jw, session_id=sid).catalog(
            skills_dir=skills_dir,
            source=source,
            fallback_local=fallback_local,
        )
        return _ok(result)
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
        dataset:           数据集别名（与 table_id 二选一）
        table_id:          数据表 ID（与 dataset 二选一）
        dimensions:        维度字段列表，格式 field_name[:alias]，如 ["date_id", "country_id:country"]
        metrics:           指标字段列表，格式 field_name:aggregation[:alias]，如 ["price:SUM:f_price"]
        where_conditions:  过滤条件列表，格式 field|operator|value_json（管道符分隔），如：
                           - ["platform_name|=|\"Amazon\""]
                           - ["date_id|>=|\"2026-01-01\"", "date_id|<=|\"2026-01-31\""]
                           操作符支持: =, !=, >, >=, <, <=, in, not in
                           value 部分为 JSON 编码值（字符串需转义引号，数组用 [...]）
        where_json:        过滤条件 JSON 字符串（与 where_conditions 二选一）
        order_by:          排序字段列表，格式 expr[:asc|desc]，如 ["f_price:desc"]
        having_conditions: HAVING 过滤条件列表，格式同 where_conditions
        limit:             返回行数限制（默认 20）
        offset:            分页偏移（默认 0）
        dry_run:           是否仅验证不执行
        data_comparison:   数据对比，格式 field,start_date,end_date，如 "date_id,2026-03-01,2026-03-22"
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


def _normalize_dimension(item: str | dict) -> dict:
    """将字符串或 dict 格式的维度统一转为 dict。

    字符串格式：field_name[:alias]
    如 "dept_name" → {"field": "dept_name"}
       "dept_name:f_dept" → {"field": "dept_name", "alias": "f_dept"}
    """
    if isinstance(item, dict):
        return item
    parts = item.split(":", 1)
    if len(parts) == 2:
        return {"field": parts[0], "alias": parts[1]}
    return {"field": parts[0]}


def _normalize_metric(item: str | dict) -> dict:
    """将字符串或 dict 格式的指标统一转为 dict。

    字符串格式：field_name:aggregation[:alias]
    如 "amount:SUM" → {"field": "amount", "aggregation": "SUM"}
       "price:SUM:f_price" → {"field": "price", "aggregation": "SUM", "alias": "f_price"}
    """
    if isinstance(item, dict):
        return item
    parts = item.split(":", 2)
    result: dict[str, str] = {"field": parts[0]}
    if len(parts) >= 2:
        result["aggregation"] = parts[1]
    if len(parts) >= 3:
        result["alias"] = parts[2]
    return result


async def query_simple(
    table_id: int,
    dimensions: list[str | dict] | None = None,
    metrics: list[str | dict] | None = None,
    filters: list[dict] | None = None,
    data_comparison: dict | None = None,
    order_by: list[dict] | None = None,
    limit: int = 20,
    offset: int = 0,
    dry_run: bool = False,
    skills_dir: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """基于简化参数直接执行查询。服务端自动处理 innerWhere、translate、MOY 展开等技术细节。

    【首次使用提示】首次执行查询前，请先调用 query_spec_must_read() 阅读完整查询规范，
    了解铁律、公式字段处理、innerWhere 限制、dataComparison 用法等关键规则。

    推荐优先使用本工具替代 query_build_and_run，无需理解 innerWhere、translate、
    cacl_type 等复杂概念，仅需 7 个纯业务参数即可完成聚合、对比、趋势分析。

    dimensions 和 metrics 支持两种传入格式：
    - 字符串格式（兼容 query_build 习惯）：
      dimensions: ["dept_name", "date_id:f_date"]
      metrics:    ["amount:SUM", "price:SUM:f_price"]
    - Dict 格式（结构化）：
      dimensions: [{"field": "ds_xxx.dept_name", "alias": "f_dept"}]
      metrics:    [{"field": "ds_xxx.price", "aggregation": "SUM", "alias": "f_price"}]

    Args:
        table_id:        数据集 ID（必填）
        dimensions:      维度列表
        metrics:         指标列表
        filters:         过滤条件，如 [{"field": "ds_xxx.platform_name", "operator": "in", "value": ["Amazon"]}]
        data_comparison: 数据对比，如 {"field": "ds_xxx.date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"}
        order_by:        排序规则，如 [{"field": "f_price", "desc": True}]
        limit:           返回行数限制（默认 20）
        offset:          分页偏移（默认 0）
        dry_run:         是否仅验证不执行
        skills_dir:      可选，自定义 Skills 目录
        session_id:      可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:             可选，已有 JWT（为空则自动加载本地缓存的）

    【查询完成后必须执行】
    每次查询执行完成后（无论成功或失败），必须调用 feedback_submit MCP 工具提交执行结果反馈。
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    try:
        # 自动归一化：将字符串格式转为 dict 格式
        norm_dimensions = [_normalize_dimension(d) for d in dimensions] if dimensions else None
        norm_metrics = [_normalize_metric(m) for m in metrics] if metrics else None

        # 注意：build_simple() 不接受 skills_dir，simple 查询由服务端处理，无需本地 metadata
        result = _query_manager(jwt=jw, session_id=sid).build_simple_and_run(
            table_id=table_id,
            dimensions=norm_dimensions,
            metrics=norm_metrics,
            filters=filters,
            data_comparison=data_comparison,
            order_by=order_by,
            limit=limit,
            offset=offset,
            dry_run=dry_run,
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

    【首次使用提示】首次执行查询前，请先调用 query_spec_must_read() 阅读完整查询规范，
    了解手写 payload 的必填字段（expr + alias）以及 innerWhere 数据集的禁用限制。

    如果未提供 session_id / jwt，会自动尝试从本地加载已保存的凭据。

    Args:
        payload_path: 本地 payload JSON 文件路径
        session_id:   可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:          可选，已有 JWT 可直接使用（为空则自动加载本地缓存的）

    【查询完成后必须执行】
    每次查询执行完成后（无论成功或失败），必须调用 feedback_submit MCP 工具提交执行结果反馈。
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

    【首次使用提示】首次执行查询前，请先调用 query_spec_must_read() 阅读完整查询规范。

    如果未提供 session_id / jwt，会自动尝试从本地加载已保存的凭据。

    Args:
        dataset:           数据集别名（与 table_id 二选一）
        table_id:          数据表 ID（与 dataset 二选一）
        dimensions:        维度字段列表，格式 field_name[:alias]，如 ["date_id", "country_id:country"]
        metrics:           指标字段列表，格式 field_name:aggregation[:alias]，如 ["price:SUM:f_price"]
        where_conditions:  过滤条件列表，格式 field|operator|value_json（管道符分隔），如：
                           - ["platform_name|=|\"Amazon\""]
                           - ["date_id|>=|\"2026-01-01\"", "date_id|<=|\"2026-01-31\""]
                           操作符支持: =, !=, >, >=, <, <=, in, not in
                           value 部分为 JSON 编码值（字符串需转义引号，数组用 [...]）
        where_json:        过滤条件 JSON 字符串（与 where_conditions 二选一）
        order_by:          排序字段列表，格式 expr[:asc|desc]，如 ["f_price:desc"]
        having_conditions: HAVING 过滤条件列表，格式同 where_conditions
        limit:             返回行数限制（默认 20）
        offset:            分页偏移（默认 0）
        dry_run:           是否仅验证不执行
        data_comparison:   数据对比，格式 field,start_date,end_date，如 "date_id,2026-03-01,2026-03-22"
        skills_dir:        可选，自定义 Skills 目录
        session_id:        可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:               可选，已有 JWT（为空则自动加载本地缓存的）

    【查询完成后必须执行】
    每次查询执行完成后（无论成功或失败），必须调用 feedback_submit MCP 工具提交执行结果反馈。
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

    【查询完成后必须执行】
    每次查询执行完成后（无论成功或失败），必须调用 feedback_submit MCP 工具提交执行结果反馈。
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
            chart_bundle = manager.fetch_chart_bundle(chart_uuid)
            return _ok(chart_bundle)
    except Exception as exc:
        return _err(exc)


async def query_chart_doc(
    chart_uuid: str,
    output_path: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 chart_uuid 生成图表 API 调用 Markdown 文档，包含查询结构、字段映射、过滤规则与样例。

    生成的文档包含七大章节：使用方式、关键术语、图表概览、API 调用流程、
    字段明细表、过滤规则、查询拆解与样例。适合 Skill / AI Agent 消费。

    如果未提供 session_id / jwt，会自动尝试从本地加载已保存的凭据。

    Args:
        chart_uuid:  图表唯一标识
        output_path: 可选，将 Markdown 写入指定文件路径
        session_id:  可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:         可选，已有 JWT（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    manager = _query_manager(jwt=jw, session_id=sid)
    try:
        result = manager.generate_chart_doc(chart_uuid=chart_uuid)
        if output_path:
            from pathlib import Path

            p = Path(output_path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(result["markdown"], encoding="utf-8")
            result["output_path"] = str(p)
        return _ok(result)
    except Exception as exc:
        return _err(exc)


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS = [
    query_spec_must_read,
    query_metadata,
    query_catalog,
    query_simple,
    query_build,
    query_run,
    query_build_and_run,
    query_chart,
    query_chart_doc,
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 query_* 工具。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
