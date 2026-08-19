"""query CLI 子命令定义。"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import typer

from opscli.query.domain.exceptions import InvalidPayloadError, QueryError
from opscli.query.services.manager import QueryManager
from opscli.query.services.planner import run_flow, run_plan

app = typer.Typer(help="数据查询入口，统一转发远端查询请求")

# 结果落盘后 stdout 保留的预览行数，避免大结果集撑爆 AI 上下文
RESULT_PREVIEW_ROWS = 10


def _emit(payload: dict, pretty: bool) -> None:
    """统一输出 JSON。"""
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _extract_result_rows(data: dict) -> tuple[list, int | None, int | None]:
    """从查询结果 data 中提取行列表、本次返回行数与服务端总行数。

    兼容三种返回形态：
    - cli_query（run / build --run）：行在 rows，行数在 meta.rowCount
    - cli_simple_query（simple --run）：行在 result.data，行数在 result.meta.rowCount，
      总数在 result.meta.totalCount（分页场景总数会大于返回行数，两者必须区分披露）
    - chart --run：合并行在 merged.rows

    返回 (行列表, 返回行数, 总行数)；提不到行时返回 ([], None, None)，如 dry_run 场景。
    """
    if not isinstance(data, dict):
        return [], None, None

    def _get_path(node: dict, path: tuple[str, ...]):
        """按路径逐层取值，任一层缺失返回 None。"""
        current: object = node
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    # 嵌套路径必须优先于顶层键：run 的顶层 data 是 dict（manager 结果），
    # 若先查顶层 ("data",) 会误命中非行数据
    row_paths: tuple[tuple[str, ...], ...] = (
        ("merged", "rows"),
        ("result", "rows"),
        ("result", "data"),
        ("rows",),
        ("data",),
    )
    rows: list = []
    for path in row_paths:
        candidate = _get_path(data, path)
        # 只有命中 list 才采纳，避免同名 dict 字段误判
        if isinstance(candidate, list):
            rows = candidate
            break

    # 返回行数取各层 meta.rowCount（服务端口径的本次返回行数），回退实际行数；
    # 总行数取各层 meta.totalCount（分页场景为匹配总数，可能大于返回行数），两者分开披露
    row_count_paths: tuple[tuple[str, ...], ...] = (
        ("merged", "meta", "rowCount"),
        ("result", "meta", "rowCount"),
        ("meta", "rowCount"),
    )
    total_count_paths: tuple[tuple[str, ...], ...] = (
        ("merged", "meta", "totalCount"),
        ("result", "meta", "totalCount"),
        ("meta", "totalCount"),
    )
    row_count: int | None = None
    for path in row_count_paths:
        candidate = _get_path(data, path)
        if isinstance(candidate, int):
            row_count = candidate
            break
    if row_count is None and rows:
        row_count = len(rows)
    total_count: int | None = None
    for path in total_count_paths:
        candidate = _get_path(data, path)
        if isinstance(candidate, int):
            total_count = candidate
            break
    return rows, row_count, total_count


def _maybe_save_result(payload: dict, *, result_file: str | None, save_result: bool) -> dict:
    """按需将查询结果落盘为 JSON 文件，并返回瘦身后的输出包裹体。

    两个开关均未启用时原样返回（保持既有 stdout 行为不变）；
    --result-file 优先于 --save-result 的默认临时路径。
    写文件失败（OSError）时异常向上抛出，走统一错误输出，不静默降级。
    """
    if not result_file and not save_result:
        return payload

    if result_file:
        target = Path(result_file).expanduser()
    else:
        # 默认临时路径：系统临时目录下 opscli 专属子目录，文件名带微秒时间戳避免覆盖
        target = (
            Path(tempfile.gettempdir())
            / "opscli"
            / "query_results"
            / f"query_result_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # 落盘完整的标准输出包裹体，文件自包含
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    rows, row_count, total_count = _extract_result_rows(payload.get("data") or {})
    return {
        "success": payload.get("success"),
        "command": payload.get("command"),
        "data": {
            "result_file": str(target),
            "row_count": row_count,
            "total_count": total_count,
            "preview_rows": rows[:RESULT_PREVIEW_ROWS],
            "hint": (
                f"完整结果已保存到 result_file，preview_rows 仅为前 {RESULT_PREVIEW_ROWS} 行预览；"
                "row_count 为本次返回并落盘的行数，total_count 为服务端匹配总行数（分页场景可能大于 row_count）"
            ),
        },
        "error": payload.get("error"),
    }


def _error_payload(command: str, exc: Exception) -> dict:
    """将异常统一映射为标准错误输出。"""
    if isinstance(exc, QueryError):
        error = exc.to_dict()
    else:
        error = {
            "code": "QUERY_ERROR",
            "message": str(exc),
        }
    return {
        "success": False,
        "command": command,
        "data": None,
        "error": error,
    }


def _current_email() -> str:
    """读取当前登录账号邮箱（规划器缓存隔离维度）；未登录时抛出可读错误。"""
    from opscli.auth.storage.credential_store import CredentialStore

    data = CredentialStore().load()
    email = (data or {}).get("email")
    if not email:
        raise QueryError("未检测到登录账号，请先执行 opscli auth login 登录后重试")
    return str(email)


def _resolve_request(request: str, query_file: str | None) -> str:
    """解析查询原文：优先读 --query-file（含特殊字符时用），否则用位置参数。"""
    if query_file:
        # utf-8-sig：PowerShell 的 Out-File / > 默认写 UTF-8 with BOM，
        # 用 utf-8 读会把 BOM 当成正文首字符，请求原文因此带上不可见前缀
        text = Path(query_file).expanduser().read_text(encoding="utf-8-sig").strip()
    else:
        text = (request or "").strip()
    if not text:
        raise InvalidPayloadError("缺少查询原文：作为位置参数传入，或用 --query-file <文件> 传入")
    return text


@app.command("plan")
def plan(
    request: str = typer.Argument("", help="自然语言查询原文"),
    query_file: str | None = typer.Option(None, "--query-file", help="从 UTF-8 文件读取查询原文（含特殊字符时用）"),
    field: list[str] | None = typer.Option(None, "--field", help="补充点名字段，可重复"),
    top_n: int | None = typer.Option(None, "--top-n", help="选表候选上限"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """自然语言请求 → 规划合同（只规划不执行，输出 query_plan_model_contract_v2）。"""
    try:
        text = _resolve_request(request, query_file)
        email = _current_email()
        contract = run_plan(
            text, user_email=email, requested_fields=field or [], top_n=top_n
        )
        payload = {
            "success": True,
            "command": "query plan",
            "data": contract,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query plan", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


def _parse_flow_order_by(order_by: list[str]) -> list[dict]:
    """解析 --order-by "<结果字段>[:asc|desc]" → [{"field": <字段>, "desc": bool}]。

    与后端 SimpleQueryBuilder.buildOrderBy 期望的 {field, desc} 形态一致。
    字段即 query_template 的结果列 alias（默认等于 field_name）。
    """
    result: list[dict] = []
    for item in order_by or []:
        parts = str(item).split(":", 1)
        field = parts[0].strip()
        if not field:
            raise InvalidPayloadError("--order-by 缺少字段名，格式：<结果字段>[:asc|desc]")
        desc = False
        if len(parts) == 2:
            direction = parts[1].strip().lower()
            if direction not in ("asc", "desc"):
                raise InvalidPayloadError(f"--order-by 方向只能是 asc|desc，收到 {parts[1]!r}")
            desc = direction == "desc"
        result.append({"field": field, "desc": desc})
    return result


@app.command("flow")
def flow(
    request: str = typer.Argument("", help="自然语言查询原文"),
    query_file: str | None = typer.Option(None, "--query-file", help="从 UTF-8 文件读取查询原文（含特殊字符时用）"),
    field: list[str] | None = typer.Option(None, "--field", help="补充点名字段，可重复"),
    limit: int | None = typer.Option(None, "--limit", help="返回行数上限（不传则自动补齐默认页，最多 5000 行）"),
    order_by: list[str] | None = typer.Option(None, "--order-by", help="排序：<结果字段>[:asc|desc]，可重复"),
    offset: int | None = typer.Option(None, "--offset", help="分页偏移（不传则后端默认 0）"),
    result_dir: str | None = typer.Option(None, "--result-dir", help="结果落盘目录，传入后全量结果写入该目录（query_result_<时间戳>.json），返回结果仅含预览行"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """一体化：规划 + planned 时执行一次取数（输出合同 + 结果）。"""
    try:
        text = _resolve_request(request, query_file)
        email = _current_email()
        contract = run_flow(
            text,
            user_email=email,
            requested_fields=field or [],
            limit=limit,
            order_by=_parse_flow_order_by(order_by or []),
            offset=offset,
            result_dir=Path(result_dir).expanduser() if result_dir else None,
        )
        payload = {
            "success": True,
            "command": "query flow",
            "data": contract,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query flow", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("preferences")
def preferences(
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """查询当前用户的图表字段偏好设置（维度/指标）。"""
    manager = QueryManager()
    try:
        result = manager.user_preferences()
        payload = {
            "success": True,
            "command": "query preferences",
            "data": result,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query preferences", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("metadata")
def metadata(
    dataset: str | None = typer.Option(None, "--dataset", help="dataset_alias"),
    table_id: int | None = typer.Option(None, "--table-id", help="table_id"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 目录"),
    all_fields: bool = typer.Option(
        False, "--all-fields",
        help="拉取全部数据集全部字段（全量元数据 include_all_fields，经用户级缓存；忽略 --dataset/--table-id）",
    ),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """读取指定数据集的 query metadata，不传任何参数时默认获取所有数据集"""
    manager = QueryManager()
    try:
        # 全量元数据：一次返回全部授权数据集的全部字段（诊断后端 include_all_fields 支持）
        if all_fields:
            email = _current_email()
            result = manager.metadata_all(user_email=email)
            datasets = result.payload.get("datasets") or []
            fields = result.payload.get("fields") or []
            payload = {
                "success": True,
                "command": "query metadata --all-fields",
                "data": {
                    "datasets": datasets,
                    "fields": fields,
                    "dataset_count": len(datasets),
                    "field_count": len(fields),
                    "stale": result.stale,
                    "from_cache": result.from_cache,
                },
                "error": None,
            }
            if not fields:
                payload["hint"] = "field_count=0：当前后端未返回全量字段，可能是取数后端未上线 include_all_fields（Phase 0）"
            _emit(payload, pretty)
            return
        result = manager.metadata(dataset_alias=dataset, table_id=table_id, skills_dir=skills_dir)
        payload = {
            "success": True,
            "command": "query metadata",
            "data": result.to_dict(),
            "error": None,
        }
        # 未指定数据集时，提示如何获取具体数据集的字段信息
        if not dataset and table_id is None:
            if result.source == "remote":
                payload["hint"] = "以上为远端最新数据集列表。如需查看特定数据集的最新字段信息，请使用 --dataset <alias> 或 --table-id <id> 指定数据集"
            else:
                payload["hint"] = "远端获取失败，已回退到本地缓存的数据集列表。如需更新本地数据，请执行 opscli skills upgrade ops-dataset-query"
        elif result.source == "local":
            payload["hint"] = "远端获取失败，已回退到本地缓存数据。如需更新本地数据，请执行 opscli skills upgrade ops-dataset-query"
    except Exception as exc:
        _emit(_error_payload("query metadata", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("catalog")
def catalog(
    source: str = typer.Option("remote", "--source", help="数据来源: remote 或 local"),
    fallback_local: bool = typer.Option(True, "--fallback-local/--no-fallback-local", help="远端失败时回退本地缓存"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """读取数据集业务语义索引（dataset catalog）。默认远端优先。"""
    manager = QueryManager()
    try:
        result = manager.catalog(
            skills_dir=skills_dir,
            source=source,
            fallback_local=fallback_local,
        )
        payload = {
            "success": True,
            "command": "query catalog",
            "data": result,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query catalog", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("intent")
def intent(
    query: str = typer.Option(..., "--query", "-q", help="自然语言查询需求"),
    source: str = typer.Option("remote", "--source", help="数据来源: remote 或 local"),
    fallback_local: bool = typer.Option(True, "--fallback-local/--no-fallback-local", help="远端失败时回退本地缓存"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """将自然语言需求匹配到 dataset catalog intents。"""
    manager = QueryManager()
    try:
        result = manager.intent_match(
            query=query,
            skills_dir=skills_dir,
            source=source,
            fallback_local=fallback_local,
        )
        payload = {
            "success": True,
            "command": "query intent",
            "data": result,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query intent", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("run")
def run(
    payload_path: str = typer.Option(..., "--payload", help="查询 JSON 文件路径"),
    timeout: int | None = typer.Option(None, "--timeout", help="查询 HTTP 超时秒数，默认 120"),
    result_file: str | None = typer.Option(None, "--result-file", help="将查询结果保存到指定 JSON 文件，stdout 仅输出预览"),
    save_result: bool = typer.Option(False, "--save-result", help="将查询结果保存到默认临时路径，stdout 仅输出预览"),
    intent_code: str | None = typer.Option(None, "--intent-code", help="意图归因编码（意图路由选表时透传）"),
    selection_source: str | None = typer.Option(None, "--selection-source", help="选表来源：planner/intent_route/local_fallback/user_specified"),
    match_record_id: int | None = typer.Option(None, "--match-record-id", help="意图匹配记录ID（query intent 返回的 match_record_id）"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """执行查询并转发到服务端 cli-query。"""
    manager = QueryManager(timeout=timeout)
    try:
        result = manager.run(
            payload_path=payload_path,
            intent_code=intent_code,
            selection_source=selection_source,
            match_record_id=match_record_id,
        )
        payload = {
            "success": True,
            "command": "query run",
            "data": result,
            "error": None,
        }
        payload = _maybe_save_result(payload, result_file=result_file, save_result=save_result)
    except Exception as exc:
        _emit(_error_payload("query run", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("chart")
def chart(
    uuid: str = typer.Option(..., "--uuid", help="图表 UUID（chart_uuid）"),
    run: bool = typer.Option(False, "--run", help="获取后立即执行所有查询并合并输出"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅生成 SQL，不执行查询"),
    timeout: int | None = typer.Option(None, "--timeout", help="查询 HTTP 超时秒数，默认 120"),
    result_file: str | None = typer.Option(None, "--result-file", help="将查询结果保存到指定 JSON 文件，仅与 --run 同用生效"),
    save_result: bool = typer.Option(False, "--save-result", help="将查询结果保存到默认临时路径，仅与 --run 同用生效"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """通过 chart_uuid 获取图表查询结构，可选立即执行。"""
    manager = QueryManager(timeout=timeout)
    try:
        if run or dry_run:
            result = manager.run_chart_queries(chart_uuid=uuid, dry_run=dry_run)
            payload = {
                "success": True,
                "command": "query chart-run",
                "data": result,
                "error": None,
            }
            payload = _maybe_save_result(payload, result_file=result_file, save_result=save_result)
        else:
            chart_bundle = manager.fetch_chart_bundle(uuid)
            payload = {
                "success": True,
                "command": "query chart",
                "data": chart_bundle,
                "error": None,
            }
    except Exception as exc:
        _emit(_error_payload("query chart", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("chart-doc")
def chart_doc(
    uuid: str = typer.Option(..., "--uuid", help="图表 UUID（chart_uuid）"),
    output: str | None = typer.Option(None, "--output", help="将 Markdown 文档写入指定文件路径"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出 JSON 包装体"),
):
    """通过 chart_uuid 生成图表 API 调用 Markdown 文档。"""
    manager = QueryManager()
    try:
        result = manager.generate_chart_doc(chart_uuid=uuid)

        # 如果指定了输出文件，将 Markdown 写入文件
        if output:
            from pathlib import Path
            output_path = Path(output).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result["markdown"], encoding="utf-8")
            result["output_path"] = str(output_path)

        payload = {
            "success": True,
            "command": "query chart-doc",
            "data": result,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query chart-doc", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("build")
def build(
    dataset: str | None = typer.Option(None, "--dataset", help="dataset_alias"),
    table_id: int | None = typer.Option(None, "--table-id", help="table_id"),
    dimension: list[str] | None = typer.Option(
        None,
        "--dimension",
        help="维度定义：field_name|global_alias|verbose_name[:alias]；alias 仅支持英文/数字/下划线，省略时默认优先使用 global_alias",
    ),
    metric: list[str] | None = typer.Option(
        None,
        "--metric",
        help="指标定义：field_name|global_alias|verbose_name:aggregation[:alias]；alias 仅支持英文/数字/下划线，省略时默认优先使用 global_alias",
    ),
    where: list[str] | None = typer.Option(None, "--where", help="筛选条件：field|operator|value_json，可重复"),
    where_json: str | None = typer.Option(None, "--where-json", help="where JSON 字符串"),
    where_file: str | None = typer.Option(None, "--where-file", help="where JSON 文件路径"),
    having: list[str] | None = typer.Option(None, "--having", help="having 条件：expr|operator|value_json，可重复"),
    order_by: list[str] | None = typer.Option(None, "--order-by", help="排序定义：expr[:asc|desc]"),
    limit: int = typer.Option(20, "--limit", help="limit，默认 20"),
    offset: int = typer.Option(0, "--offset", help="offset，默认 0"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅生成 SQL，不执行查询"),
    output: str | None = typer.Option(None, "--output", help="将 payload 写入指定文件"),
    data_comparison: str | None = typer.Option(
        None, "--data-comparison",
        help="数据对比：field,start_date,end_date（例: date_id,2026-03-01,2026-03-22）",
    ),
    global_currency: str | None = typer.Option(
        None, "--global-currency",
        help="全局币种（仅支持 USD/GBP/CAD/EUR/JPY/CNY），按该币种换算展示金额；不传则由服务端回退用户默认配置",
    ),
    run: bool = typer.Option(False, "--run", help="构造后立即执行查询"),
    timeout: int | None = typer.Option(None, "--timeout", help="查询 HTTP 超时秒数，默认 120"),
    result_file: str | None = typer.Option(None, "--result-file", help="将查询结果保存到指定 JSON 文件，仅与 --run 同用生效"),
    save_result: bool = typer.Option(False, "--save-result", help="将查询结果保存到默认临时路径，仅与 --run 同用生效"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """基于简化参数构造标准 query payload。"""
    manager = QueryManager(timeout=timeout)
    try:
        common_kwargs = {
            "dataset_alias": dataset,
            "table_id": table_id,
            "dimensions": dimension,
            "metrics": metric,
            "where_conditions": where,
            "where_json": where_json,
            "where_file": where_file,
            "having_conditions": having,
            "order_by": order_by,
            "limit": limit,
            "offset": offset,
            "dry_run": dry_run,
            "output_path": output,
            "data_comparison": data_comparison,
            "global_currency": global_currency,
            "skills_dir": skills_dir,
        }
        result = manager.build_and_run(**common_kwargs) if run else manager.build(**common_kwargs)
        payload = {
            "success": True,
            "command": "query build-and-run" if run else "query build",
            "data": result,
            "error": None,
        }
        # 仅执行查询时才有结果可落盘，纯构造 payload 时忽略保存参数
        if run:
            payload = _maybe_save_result(payload, result_file=result_file, save_result=save_result)
    except Exception as exc:
        _emit(_error_payload("query build-and-run" if run else "query build", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


def _inner_result_error(result: object) -> dict | None:
    """提取取数服务内层的失败信息（HTTP 200 + 外层 code=200 但内层 success=false）。

    为什么必须单独处理：服务端有两层错误信封。外层 Laravel 信封的字段级原因在
    error_details 里（已由 shared.http 透传），但取数引擎自己的校验失败是包在
    成功的外层信封里返回的——`data.result.success=false`，真正的字段级原因埋在
    `data.result.error.details.errors[]`。此前 CLI 对这种情况照样输出 success=true，
    调用方看到「命令成功」却拿不到数据，只能自己去翻嵌套结构。
    实测形态：limit 超上限时返回
    `{"code":"VALIDATION_ERROR","message":"请求参数验证失败",
      "details":{"errors":[{"field":"body.query.limit",
                            "message":"Input should be less than or equal to 500000"}]}}`
    """
    if not isinstance(result, dict):
        return None
    inner = result.get("result")
    if not isinstance(inner, dict) or inner.get("success") is not False:
        return None
    error = inner.get("error")
    if not isinstance(error, dict):
        error = {}
    message = str(error.get("message") or "取数服务返回失败但未说明原因").strip()
    reasons = _field_level_reasons(error.get("details"))
    return {
        "code": str(error.get("code") or "QUERY_SERVICE_ERROR"),
        "message": f"{message}（{reasons}）" if reasons else message,
        "details": error.get("details"),
    }


def _field_level_reasons(details: object) -> str:
    """把取数引擎的 details.errors[] 压成一行可读原因。"""
    if not isinstance(details, dict):
        return ""
    errors = details.get("errors")
    if not isinstance(errors, (list, tuple)):
        return ""
    parts = []
    for item in errors[:6]:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        text = str(item.get("message") or "").strip()
        if field and text:
            parts.append(f"{field}: {text}")
        elif text:
            parts.append(text)
    return "；".join(parts)


def _inline_json_hint(raw: str) -> str:
    """内联 JSON 解析失败时给出可直接照做的替代命令。

    为什么每次失败都要给替代方案：线上 3987 条取数反馈里有 447 条（11.2%、涉及 98 人、
    近 30 天日均从 5.3 涨到 9.0）是内联 --json 在 PowerShell 下被引号与转义规则改写，
    服务端收到的已不是合法 JSON。此前的提示只在「单引号开头」或「含双反斜杠且 win32」
    两种窄条件下才出现，绝大多数用户看到的只有一句 JSON 语法错误位置，
    完全不知道换一种传参方式就能绕开——于是同一个人反复踩、反复提反馈。
    """
    hints = []
    if raw.lstrip().startswith("{'"):
        hints.append("检测到单引号包裹的 JSON，JSON 规范只接受双引号")
    if "\\\\" in raw:
        hints.append("检测到双反斜杠，通常是 Shell 二次转义的痕迹")
    prefix = ("\n  可能原因: " + "；".join(hints)) if hints else ""
    return (
        f"{prefix}"
        "\n  建议改用文件或管道传参，可完全绕开 Shell 的引号与转义重写："
        "\n    opscli query simple --table-id <ID> --payload payload.json --run"
        "\n    Get-Content payload.json -Raw | opscli query simple --table-id <ID> --payload - --run"
        "\n  payload.json 请存为 UTF-8（BOM 头已自动兼容）"
    )


@app.command("simple")
def simple(
    table_id: int = typer.Option(..., "--table-id", help="数据集 ID"),
    dataset: str | None = typer.Option(None, "--dataset", help="dataset_alias 或 dataset_name，用于字段校验"),
    payload_file: str | None = typer.Option(
        None, "--payload",
        help="简化查询 JSON 文件路径，传 - 表示从 stdin 读取（与 --json 二选一）；"
             "Windows PowerShell 下请优先用本参数，内联 --json 会被引号转义破坏",
    ),
    payload_json: str | None = typer.Option(None, "--json", help="简化查询 JSON 字符串（与 --payload 二选一）"),
    output: str | None = typer.Option(None, "--output", help="将 payload 写入指定文件"),
    global_currency: str | None = typer.Option(
        None, "--global-currency",
        help="全局币种（仅支持 USD/GBP/CAD/EUR/JPY/CNY）；优先级高于 payload 内的 globalCurrency；不传则由服务端回退用户默认配置",
    ),
    run: bool = typer.Option(False, "--run", help="构造后立即执行查询"),
    timeout: int | None = typer.Option(None, "--timeout", help="查询 HTTP 超时秒数，默认 120"),
    result_file: str | None = typer.Option(None, "--result-file", help="将查询结果保存到指定 JSON 文件，仅与 --run 同用生效"),
    save_result: bool = typer.Option(False, "--save-result", help="将查询结果保存到默认临时路径，仅与 --run 同用生效"),
    intent_code: str | None = typer.Option(None, "--intent-code", help="意图归因编码（意图路由选表时透传）"),
    selection_source: str | None = typer.Option(None, "--selection-source", help="选表来源：planner/intent_route/local_fallback/user_specified"),
    match_record_id: int | None = typer.Option(None, "--match-record-id", help="意图匹配记录ID（query intent 返回的 match_record_id）"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """基于简化参数构造 simple query payload 并可选执行。"""
    manager = QueryManager(timeout=timeout)
    try:
        if payload_file and payload_json:
            raise InvalidPayloadError("--payload 和 --json 只能使用一种")

        simple_params: dict = {}
        if payload_file:
            # "-" 走 stdin：PowerShell 下 `$payload | opscli query simple --payload -`
            # 比内联 --json 稳，管道不经历引号与转义重写
            if payload_file.strip() == "-":
                raw = sys.stdin.read()
                try:
                    simple_params = json.loads(raw.lstrip("﻿"))
                except json.JSONDecodeError as exc:
                    raise InvalidPayloadError(
                        f"stdin 读入的 JSON 解析失败: {exc}\n"
                        f"  提示: 确认管道内容是完整的 UTF-8 JSON 对象"
                    ) from exc
            else:
                pf = Path(payload_file).expanduser()
                if not pf.exists():
                    raise InvalidPayloadError(f"payload 文件不存在: {pf}")
                try:
                    simple_params = json.loads(pf.read_text(encoding="utf-8-sig"))
                except json.JSONDecodeError as exc:
                    raise InvalidPayloadError(
                        f"payload 文件 JSON 解析失败: {pf}\n"
                        f"  错误: {exc}\n"
                        f"  提示: 检查文件是否为有效 UTF-8 JSON，BOM 头已自动兼容"
                    ) from exc
        elif payload_json:
            try:
                simple_params = json.loads(payload_json)
            except json.JSONDecodeError as exc:
                raise InvalidPayloadError(
                    f"JSON 字符串解析失败: {exc}{_inline_json_hint(payload_json)}"
                ) from exc

        kwargs: dict[str, object] = {"table_id": table_id, "dataset_alias": dataset}

        key_map = {
            "dimensions": "dimensions",
            "metrics": "metrics",
            "filters": "filters",
            "dataComparison": "data_comparison",
            "orderBy": "order_by",
            "globalCurrency": "global_currency",
        }
        for key, kwarg_key in key_map.items():
            if key in simple_params:
                kwargs[kwarg_key] = simple_params[key]

        # --global-currency 命令行选项优先级高于 payload 内的 globalCurrency
        if global_currency:
            kwargs["global_currency"] = global_currency

        # payload 中 limit/offset 为 null 时视为"未指定"，跳过不透传：
        # 规划器模板可能带 "limit": null，若原样透传，None 会落入 build_simple 的
        # int 参数——编译版（Cython）会抛 "expected int, got NoneType"，此处剔除后沿用后端默认。
        if simple_params.get("limit") is not None:
            kwargs["limit"] = simple_params["limit"]
        if simple_params.get("offset") is not None:
            kwargs["offset"] = simple_params["offset"]
        if "dryRun" in simple_params:
            kwargs["dry_run"] = simple_params["dryRun"]
        if output:
            kwargs["output_path"] = output
        kwargs["validate_fields"] = True

        result = (
            manager.build_simple_and_run(
                intent_code=intent_code,
                selection_source=selection_source,
                match_record_id=match_record_id,
                **kwargs,
            )
            if run
            else manager.build_simple(**kwargs)
        )
        command_name = "query simple-run" if run else "query simple"
        # 取数服务会在 HTTP 200 + 外层 code=200 的信封里返回失败，真正的字段级原因埋在
        # data.result.error.details.errors[]。此前 CLI 对这种情况照样报 success=true，
        # 调用方看到「命令成功」却拿不到数据。此处提取为顶层 error 并以非零码退出。
        # 注意：不能在 try 内 emit 后 raise typer.Exit——typer.Exit 继承自 RuntimeError，
        # 会被下面的 except Exception 接住而重复输出一遍。
        inner_error = _inner_result_error(result) if run else None
        payload = {
            "success": not inner_error,
            "command": command_name,
            "data": result,
            "error": inner_error,
        }
        # 仅执行查询时才有结果可落盘，纯构造 payload 时忽略保存参数
        if run:
            payload = _maybe_save_result(payload, result_file=result_file, save_result=save_result)
    except Exception as exc:
        _emit(_error_payload("query simple-run" if run else "query simple", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)
    if payload.get("error"):
        raise typer.Exit(1)
