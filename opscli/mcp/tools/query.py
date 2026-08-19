"""Query 工具模块。

将 opscli query 子模块的核心能力暴露为 MCP 工具：

规范入口：
- query_spec_must_read  — ！！！【重要】读取 MCP 取数规范（未安装或已禁用 Skill 时必须先调用）

规划器路线（自然语言取数首选，需传输层已验证账号）：
- query_plan            — 自然语言请求 → 规划合同（只规划不执行）
- query_flow            — 一体化：规划 + planned 时按 query_template 执行一次并回传结果

手工构造路线（先取元数据再查）：
- query_metadata        — 查询数据集 metadata（维度/指标字段、select_columns、filter_configs）
- query_preferences     — 查询当前用户的图表字段偏好
- query_simple          — 基于简化参数直接执行查询
- query_build           — 构造标准 query payload（不执行，无需凭证）
- query_run             — 读取本地 payload 文件并执行查询
- query_build_and_run   — 构造 payload 并立即执行，一步返回结果

图表路线：
- query_chart           — 通过 chart_uuid 获取/执行图表查询
- query_chart_doc       — 通过 chart_uuid 生成图表 API 调用 Markdown 文档

catalog / intent 路线：query_catalog — 读取数据集业务语义索引；query_intent_match — 自然语言匹配 catalog intents。

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

from opscli.query.services.planner import run_flow, run_plan

from .helpers import _err, _ok, _parse_json_arg, _query_manager


async def query_spec_must_read() -> dict:
    """读取 MCP 取数规范（QUERY_SPEC.md）——未安装 Skill 时的完整取数指南。

    【调用前必须完成的检测步骤】
    1. 调用 skills_list MCP 工具，确认 ops-dataset-query Skill 是否存在且启用（disable != true）
    2. 如果 Skill 存在且启用 → 优先加载 Skill 目录内的 SKILL.md，不必调用本工具
    3. 如果 Skill 不存在 或 disable=true → 必须调用本工具，不可跳过

    【跳过规范的已知风险】
    - 公式字段（ACOS/ROAS/毛利率）被套 SUM 二次聚合，指标失真
    - 库存等快照类指标跨日累加，数值膨胀数倍
    - data_comparison 缺少主周期 filters，报 QS-EXE-005
    - 字段标识误用 global_alias、或凭记忆猜字段名，报"字段不存在"后换名盲重试
    - 筛选值未过 select_columns 权限枚举，把无权限值当成查询条件
    - 客户端重复注入服务端 filter_configs 默认条件，结果恒 0 行
    - 未传 limit 时沿用后端默认 20 行，把截断结果当成全量

    规范内容包括：
    - 14 条核心铁律（鉴权、规划器优先、元数据唯一来源、字段标识、公式字段、对比周期、
      快照指标、默认筛选、权限枚举、歧义澄清、输出与证据、反馈边界等）
    - 两条取数路线：query_plan / query_flow 规划器路线，query_metadata + query_simple 手工路线
    - 各查询工具的参数规范与调用示例（普通聚合 / 环比对比 / MOY 趋势 / 公式字段）
    - 查询组件权限枚举校验、字段与数据集歧义澄清规则、时间口径规范
    - 常见错误处理速查、查询前自检清单、结果证据合同、反馈边界

    【完整工作流说明】
    标准流程：检测 Skill 状态 → 读取本规范 → 按规范取数 → 仅在意外失败时提交一次 feedback_submit
    （0 行、需要澄清、认证未就绪、用户取消都不是反馈事件，成功查询不自动提交反馈）。

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
    include_all_fields: bool = False,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """查询指定数据集的 metadata（维度/指标字段列表、select_columns、filter_configs）。

    【鉴权：两条等价路径，登录不是前置必需】
    - 显式凭证：直接传 session_id / jwt 即可，无需先调用 auth_is_authenticated 或 auth_mcp_login
    - 隐式登录态：两者留空时自动加载平台注入或本地已保存的凭证
    本工具无 session_id 非空校验，单传 jwt 也可用。

    指定 dataset 或 table_id 时，优先从远端拉取最新字段信息；
    远端失败则回退到本地缓存。未指定任何参数时返回本地数据集列表。

    `include_all_fields=True` 时改走**全量元数据**（一次返回全部授权数据集的全部字段，
    经用户级缓存，忽略 dataset/table_id/skills_dir）——用于批量索引/诊断后端是否支持
    include_all_fields（Phase 0）：返回 `field_count` 非 0 表示后端已支持，为 0 表示未上线。

    【典型工作流】
    1. 不传任何参数 → 返回本地全部数据集列表，找到目标数据集名称或 table_id
    2. 传入 dataset 或 table_id → 返回该数据集的完整维度/指标字段列表
    3. 根据返回的字段信息，再调用 query_simple 执行实际查询

    Args:
        dataset:            数据集别名（与 table_id 二选一）
        table_id:           数据表 ID（与 dataset 二选一）
        skills_dir:         可选，自定义 Skills 目录（用于读取本地缓存 metadata）
        include_all_fields: 为 True 时返回全部数据集全部字段（全量元数据，经缓存）
        session_id:         可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:                可选，已有 JWT（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import (
        _get_auth_pair,
        _get_authenticated_user_email,
        _get_credential_dir,
    )

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    try:
        if include_all_fields:
            # 全量元数据需已验证账号（缓存隔离维度）与隔离目录，同 query_plan 身份解析
            email = _get_authenticated_user_email()
            if not email:
                return _err(
                    ValueError(
                        "include_all_fields 需已验证账号：请先 auth_mcp_login 登录，或传入有效凭证"
                    )
                )
            result = _query_manager(jwt=jw, session_id=sid).metadata_all(
                user_email=email, base_dir=_get_credential_dir()
            )
            datasets = result.payload.get("datasets") or []
            fields = result.payload.get("fields") or []
            return _ok(
                {
                    "datasets": datasets,
                    "fields": fields,
                    "dataset_count": len(datasets),
                    "field_count": len(fields),
                    "stale": result.stale,
                    "from_cache": result.from_cache,
                }
            )
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


async def query_intent_match(
    query: str,
    skills_dir: str | None = None,
    source: str = "remote",
    fallback_local: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """根据自然语言需求匹配 dataset catalog intents。

    当用户未显式指定 dataset/table_id 时，应先调用本工具。返回的
    intent_constraints 包含 scenario_description、default_filters、
    comparison_strategy、recommended_dimensions、recommended_metrics 等业务约束；
    后续构造查询时必须优先遵循这些约束，再进行字段存在性校验。

    返回体额外含 match_record_id（本次匹配的服务端归因记录 ID，上报失败时为
    None）；命中候选并执行查询时，应将其与候选的 intent_code 一并透传给
    query_run / query_build_and_run 的 match_record_id / intent_code 参数，
    用于闭环归因统计。

    Args:
        query: 自然语言查询需求
        skills_dir: 可选，自定义 Skills 目录（用于读取本地缓存 catalog）
        source: 数据来源，remote（默认）或 local
        fallback_local: source=remote 时，远端失败是否回退本地缓存
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt: 可选，已有 JWT（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    try:
        result = _query_manager(jwt=jw, session_id=sid).intent_match(
            query=query,
            skills_dir=skills_dir,
            source=source,
            fallback_local=fallback_local,
            # MCP 路径需显式声明上报来源为 mcp_intent，
            # 否则会沿用 QueryManager.intent_match 的默认值 "cli_intent"，
            # 导致服务端归因统计里 MCP 调用被误记为 CLI 调用。
            report_source="mcp_intent",
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def query_build(
    dataset: str | None = None,
    table_id: int | None = None,
    dimensions: list[str] | str | None = None,
    metrics: list[str] | str | None = None,
    where_conditions: list[str] | str | None = None,
    where_json: str | None = None,
    order_by: list[str] | str | None = None,
    having_conditions: list[str] | str | None = None,
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
    # 容错：AI 有时将 list 参数以 JSON 字符串形式传入，统一解析
    try:
        dimensions = _parse_json_arg(dimensions, list)
        metrics = _parse_json_arg(metrics, list)
        where_conditions = _parse_json_arg(where_conditions, list)
        order_by = _parse_json_arg(order_by, list)
        having_conditions = _parse_json_arg(having_conditions, list)
    except ValueError as exc:
        return _err(exc)

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
    dimensions: list[str | dict] | str | None = None,
    metrics: list[str | dict] | str | None = None,
    filters: list[dict] | str | None = None,
    data_comparison: dict | str | None = None,
    order_by: list[dict] | str | None = None,
    limit: int = 20,
    offset: int = 0,
    dry_run: bool = False,
    skills_dir: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """基于简化参数直接执行查询。服务端自动处理 innerWhere、translate、MOY 展开等技术细节。

    【前置条件 - 硬门禁，缺任一步禁止发起查询】
    1. 已读 query_spec_must_read() 返回的取数规范（未安装 ops-dataset-query Skill 时）
    2. 调用 query_metadata（传入 dataset 或 table_id）拿到该数据集的**真实字段清单**，
       dimensions / metrics / filters 中每个 field 都必须逐字出现在该响应里
    3. 凭证就绪：显式传 session_id（+可选 jwt），或使用已保存的登录态；
       本工具有 session_id 非空硬校验，只传 jwt 会报"无 session_id"

    凭记忆拼字段名会报"字段不存在"；此时禁止换一个自己想的名字重试，必须回到 query_metadata
    重新核对。字段标识一律用 field_name，不要用 global_alias（后端不接受）。

    【规划器路线更省事】自然语言取数可直接用 query_flow 一次完成规划与执行（需传输层已验证账号）；
    本工具用于规划器不可用、需要精确控制 payload、组件权限枚举查询等场景。

    推荐优先使用本工具替代 query_build_and_run，无需理解 innerWhere、translate、
    cacl_type 等复杂概念，仅需 7 个纯业务参数即可完成聚合、对比、趋势分析。

    【常见错误】
    - 公式字段（含 summary_expression / formula_config）不传 aggregation，改传 expr
    - 用 data_comparison 时 filters 必须同时含主周期日期，否则报 QS-EXE-005
    - 服务端 filter_configs 默认条件由服务端强制应用，客户端重复注入会导致恒 0 行
    - 不传 limit 时沿用后端默认 20 行，需要全量时显式传更大的 limit

    dimensions 和 metrics 支持两种传入格式：
    - 字符串格式（兼容 query_build 习惯）：
      dimensions: ["dept_name", "date_id:f_date"]
      metrics:    ["amount:SUM", "price:SUM:f_price"]
    - Dict 格式（结构化）：
      dimensions: [{"field": "ds_xxx.dept_name", "alias": "f_dept"}]
      metrics:    [{"field": "ds_xxx.price", "aggregation": "SUM", "alias": "f_price"}]

    Args:
        table_id:        数据集 ID（必填，须从 query_metadata 返回结果中获取）
        dimensions:      维度列表（字段名须从 query_metadata 返回的字段列表中选取）
        metrics:         指标列表（字段名须从 query_metadata 返回的字段列表中选取）
        filters:         过滤条件，如 [{"field": "ds_xxx.platform_name", "operator": "in", "value": ["Amazon"]}]
        data_comparison: 数据对比，如 {"field": "ds_xxx.date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"}
        order_by:        排序规则，如 [{"field": "f_price", "desc": True}]
        limit:           返回行数限制（默认 20）
        offset:          分页偏移（默认 0）
        dry_run:         是否仅验证不执行
        skills_dir:      可选，自定义 Skills 目录
        session_id:      可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:             可选，已有 JWT（为空则自动加载本地缓存的）

    【反馈边界】仅当本工具**意外失败**（抛异常、success=false、超时或无法解释的服务错误）时，
    在同一请求内提交一次 feedback_submit；同一失败 30 分钟内去重。0 行、需要澄清、
    预期内的认证未就绪和用户取消都不是反馈事件，成功查询不自动提交反馈。
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))

    # 容错：AI 有时将 list/dict 参数以 JSON 字符串形式传入，统一解析
    try:
        dimensions = _parse_json_arg(dimensions, list)
        metrics = _parse_json_arg(metrics, list)
        filters = _parse_json_arg(filters, list)
        data_comparison = _parse_json_arg(data_comparison, dict)
        order_by = _parse_json_arg(order_by, list)
    except ValueError as exc:
        return _err(exc)

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
            validate_fields=True,
            skills_dir=skills_dir,
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def query_run(
    payload_path: str,
    session_id: str | None = None,
    jwt: str | None = None,
    intent_code: str | None = None,
    selection_source: str | None = None,
    match_record_id: int | None = None,
) -> dict:
    """读取本地 payload JSON 文件并转发至服务端执行查询。

    【前置条件】先调用 query_spec_must_read() 阅读取数规范（未安装 Skill 时），
    了解手写 payload 的必填字段（expr + alias）与字段标识规则。

    【禁止手写的字段】userEmail、query.from.table、query.from.permission、query.from.database
    由构造层根据数据集 metadata 自动生成（涉及用户隐私、子查询 SQL 与权限占位符），手写必错。
    需要这些字段时改用 query_build / query_build_and_run / query_simple 生成。

    显式传 session_id（+可选 jwt）即可执行，无需前置登录调用；两者留空时自动加载本地凭据。
    本工具有 session_id 非空硬校验。

    Args:
        payload_path: 本地 payload JSON 文件路径
        session_id:   可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:          可选，已有 JWT 可直接使用（为空则自动加载本地缓存的）
        intent_code:       可选，意图归因编码，以请求头形式透传（意图路由选表时填写）
        selection_source:  可选，选表来源：planner/intent_route/local_fallback/user_specified
        match_record_id:   可选，意图匹配记录ID，取自 query_intent_match 返回值的 match_record_id 字段

    【反馈边界】仅当本工具**意外失败**（抛异常、success=false、超时或无法解释的服务错误）时，
    在同一请求内提交一次 feedback_submit；同一失败 30 分钟内去重。0 行、需要澄清、
    预期内的认证未就绪和用户取消都不是反馈事件，成功查询不自动提交反馈。
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    try:
        result = _query_manager(jwt=jw, session_id=sid).run(
            payload_path=payload_path,
            intent_code=intent_code,
            selection_source=selection_source,
            match_record_id=match_record_id,
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def query_build_and_run(
    dataset: str | None = None,
    table_id: int | None = None,
    dimensions: list[str] | str | None = None,
    metrics: list[str] | str | None = None,
    where_conditions: list[str] | str | None = None,
    where_json: str | None = None,
    order_by: list[str] | str | None = None,
    having_conditions: list[str] | str | None = None,
    limit: int = 20,
    offset: int = 0,
    dry_run: bool = False,
    data_comparison: str | None = None,
    skills_dir: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
    intent_code: str | None = None,
    selection_source: str | None = None,
    match_record_id: int | None = None,
) -> dict:
    """构造 query payload 并立即执行，一步返回数据结果（CLI 风格字符串参数）。

    【前置条件 - 硬门禁】① 先读 query_spec_must_read() 返回的取数规范（未安装 Skill 时）；
    ② 先用 query_metadata 拿到目标数据集的真实字段清单，dimensions / metrics /
    where_conditions 中的字段名必须逐字来自该响应，不得凭记忆拼写或报错后换名重试。

    一般优先使用 query_simple（dict 参数，语义更清晰）；本工具适用于已习惯 CLI 字符串格式的场景。

    显式传 session_id（+可选 jwt）即可执行，无需前置登录调用；两者留空时自动加载本地凭据。
    本工具有 session_id 非空硬校验。

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
        intent_code:       可选，意图归因编码，以请求头形式透传（意图路由选表时填写）
        selection_source:  可选，选表来源：planner/intent_route/local_fallback/user_specified
        match_record_id:   可选，意图匹配记录ID，取自 query_intent_match 返回值的 match_record_id 字段

    【反馈边界】仅当本工具**意外失败**（抛异常、success=false、超时或无法解释的服务错误）时，
    在同一请求内提交一次 feedback_submit；同一失败 30 分钟内去重。0 行、需要澄清、
    预期内的认证未就绪和用户取消都不是反馈事件，成功查询不自动提交反馈。
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))

    # 容错：AI 有时将 list 参数以 JSON 字符串形式传入，统一解析
    try:
        dimensions = _parse_json_arg(dimensions, list)
        metrics = _parse_json_arg(metrics, list)
        where_conditions = _parse_json_arg(where_conditions, list)
        order_by = _parse_json_arg(order_by, list)
        having_conditions = _parse_json_arg(having_conditions, list)
    except ValueError as exc:
        return _err(exc)

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
            intent_code=intent_code,
            selection_source=selection_source,
            match_record_id=match_record_id,
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

    【反馈边界】仅当本工具**意外失败**（抛异常、success=false、超时或无法解释的服务错误）时，
    在同一请求内提交一次 feedback_submit；同一失败 30 分钟内去重。0 行、需要澄清、
    预期内的认证未就绪和用户取消都不是反馈事件，成功查询不自动提交反馈。
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


async def query_plan(
    request: str,
    requested_fields: list[str] | str | None = None,
    top_n: int | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """自然语言取数请求 → 规划合同（只规划不执行，输出 query_plan_model_contract_v2）。

    规划器内核化入口：读取当前账号可见的全量授权元数据（经用户级缓存），完成选表、
    字段/权限指导、时间口径解析与平台/组件权限枚举，产出模型可见的规划合同。
    合同 status=planned 时可用 query_flow 一步执行，或据 execution_ref.query_template
    自行填充后走 query_simple；status=clarify_required/blocked 时按 model_view 澄清。

    【前置条件 - 身份要求与其他 query_* 工具不同】本工具用当前账号邮箱做元数据缓存隔离，
    身份**只来自传输层已验证账号**（remote 模式的 transport 邮箱 / fixed 模式的隔离凭证缓存 /
    stdio 默认 CredentialStore），**不读显式传入的 session_id 与 jwt**——只持有显式凭证的调用方
    在此会失败，需改走 auth_mcp_login() 登录，或改用 query_metadata + query_simple 手工路线。
    session_id/jwt 仅用于后续查询执行，留空时自动加载本地凭证。

    Args:
        request:          用户查询原文（自然语言）。
        requested_fields: 可选，用户点名字段列表（可传 JSON 字符串）。
        top_n:            可选，选表候选上限。
        session_id:       可选，OAuth 授权后的 Session ID（为空则自动加载）。
        jwt:              可选，已有 JWT（为空则自动加载）。
    """
    from opscli.mcp.tools.helpers import (
        _get_auth_pair,
        _get_authenticated_user_email,
        _get_credential_dir,
    )

    email = _get_authenticated_user_email()
    if not email:
        return _err(ValueError("无法确认当前登录账号：请先 auth_mcp_login 登录，或传入有效凭证"))
    try:
        fields = _parse_json_arg(requested_fields, list) or []
    except ValueError as exc:
        return _err(exc)
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    base_dir = _get_credential_dir()
    try:
        contract = run_plan(
            request,
            user_email=email,
            base_dir=base_dir,
            requested_fields=fields,
            top_n=top_n,
            query_manager=_query_manager(jwt=jw, session_id=sid),
        )
        return _ok(contract)
    except Exception as exc:
        return _err(exc)


async def query_flow(
    request: str,
    requested_fields: list[str] | str | None = None,
    limit: int | None = None,
    order_by: list[dict] | str | None = None,
    offset: int | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """一体化取数：规划 + planned 数据集查询时按 query_template 执行一次并回传结果。

    非 planned（需澄清/被阻断/图表 UUID 等）合同原样返回，交调用方按 model_view 处置。
    planned 时把 limit/order_by/offset 填入 query_template 再执行；不传 limit 且
    服务端默认页少于 totalCount 时会自动补齐一次（最多 5000 行）。返回体的
    result_disclosures 除实际行数/总数/截断状态（row_count_returned/total_count/truncated/
    auto_complete_applied）外，还带 limit（原始请求的分页上限，不受自动补齐影响）与
    currency/currency_disclosure_zh（本次实际生效币种，取自服务端 meta.currency；为
    null 时只能声明未声明，禁止推断）；传了 order_by 且检测到服务端排序未生效（已知缺陷）
    时会额外出现 order_fallback/order_disclosure_zh，说明已本地重排或加量重查后本地排序，
    结论中必须披露该兜底行为，排序正常生效或未传 order_by 时不会出现 order_fallback。
    返回体还内嵌 evidence_contract（构建失败时为 evidence_contract_error，与合同其余字段
    同级），组织结论时优先使用其 required_evidence/required_disclosures_zh/
    forbidden_inferences_zh。

    【前置条件】同 query_plan：身份只来自传输层已验证账号，不读显式传入的 session_id / jwt。

    【非 planned 时的处置】status=clarify_required 按 model_view.clarification_messages_zh 提问，
    确认后把明确口径写回 request 原文重新调用；status=blocked 且 recovery_state=refresh_in_progress
    时等待约 25 秒后用相同参数原样重调（合同里的 recovery_command 是 CLI 形态，MCP 场景取其语义即可，
    不要执行该命令，也不要自行升级），连续 3 次仍未就绪才提交反馈并停止。

    【结果被截断时】先看 result_disclosures：truncated=false 才可按全量陈述；
    truncated=true 表示总数超过自动补齐上限或服务端仍未返回完整结果，此时显式传更大
    limit 重新调用，拿到全量前必须声明当前仅为部分结果。

    【反馈边界】仅在本工具意外失败时提交一次 feedback_submit；0 行、需要澄清、
    认证未就绪和用户取消都不是反馈事件，成功查询不自动提交反馈。

    Args:
        request:          用户查询原文（自然语言）。
        requested_fields: 可选，用户点名字段列表（可传 JSON 字符串）。
        limit:            可选，返回行数上限；不传时自动补齐默认页，最多 5000 行。
        order_by:         可选，排序 [{"field": "<结果字段>", "desc": true}]（可传 JSON 字符串）；
                          只认 desc 布尔值，写成 {"direction": "DESC"} 会被后端忽略并恒按升序返回。
        offset:           可选，分页偏移；不传则后端默认 0。
        session_id:       可选，OAuth 授权后的 Session ID（为空则自动加载）。
        jwt:              可选，已有 JWT（为空则自动加载）。
    """
    from opscli.mcp.tools.helpers import (
        _get_auth_pair,
        _get_authenticated_user_email,
        _get_credential_dir,
    )

    email = _get_authenticated_user_email()
    if not email:
        return _err(ValueError("无法确认当前登录账号：请先 auth_mcp_login 登录，或传入有效凭证"))
    try:
        fields = _parse_json_arg(requested_fields, list) or []
        norm_order_by = _parse_json_arg(order_by, list)
    except ValueError as exc:
        return _err(exc)
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    base_dir = _get_credential_dir()
    try:
        result = run_flow(
            request,
            user_email=email,
            base_dir=base_dir,
            requested_fields=fields,
            limit=limit,
            order_by=norm_order_by,
            offset=offset,
            query_manager=_query_manager(jwt=jw, session_id=sid),
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def query_preferences(
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """查询当前用户的图表字段偏好设置。

    返回当前登录用户已保存的所有图表字段偏好，包含每个数据集的维度和指标列表。

    【字段选择优先级】
    1. 优先调用本工具获取用户偏好（最高优先级）
    2. 远端 metadata（query_metadata）
    3. 本地缓存（最低优先级）

    若偏好数据存在，必须优先使用偏好中的字段，无需再走远端/本地查询。

    Args:
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:        可选，已有 JWT（为空则自动加载本地缓存的）

    Returns:
        {"success": true, "data": [{"table_id": 15, "dataset_alias": "ds_xxx",
          "dataset_name": "xxx", "description": "xxx",
          "dimensions": [{"field_name": "...", "verbose_name": "..."}],
          "metrics": [{"field_name": "...", "verbose_name": "...", "aggregation": {...}}]}]}
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("ops", session_id, jwt)
    try:
        result = _query_manager(jwt=jw, session_id=sid).user_preferences()
        return _ok(result)
    except Exception as exc:
        return _err(exc)


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS = [
    query_spec_must_read,
    query_metadata,
    query_catalog,
    query_intent_match,
    query_simple,
    query_build,
    query_run,
    query_build_and_run,
    query_chart,
    query_chart_doc,
    query_plan,
    query_flow,
    query_preferences,
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 query_* 工具。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
