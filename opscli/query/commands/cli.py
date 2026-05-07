"""query CLI 子命令定义。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opscli.query.domain.exceptions import InvalidPayloadError, QueryError
from opscli.query.services.manager import QueryManager

app = typer.Typer(help="数据查询入口，统一转发远端查询请求")


def _emit(payload: dict, pretty: bool) -> None:
    """统一输出 JSON。"""
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


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


@app.command("metadata")
def metadata(
    dataset: str | None = typer.Option(None, "--dataset", help="dataset_alias"),
    table_id: int | None = typer.Option(None, "--table-id", help="table_id"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """读取指定数据集的 query metadata。"""
    manager = QueryManager()
    try:
        result = manager.metadata(dataset_alias=dataset, table_id=table_id, skills_dir=skills_dir)
        payload = {
            "success": True,
            "command": "query metadata",
            "data": result.to_dict(),
            "error": None,
        }
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


@app.command("run")
def run(
    payload_path: str = typer.Option(..., "--payload", help="查询 JSON 文件路径"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """执行查询并转发到服务端 cli-query。"""
    manager = QueryManager()
    try:
        result = manager.run(payload_path=payload_path)
        payload = {
            "success": True,
            "command": "query run",
            "data": result,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query run", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("chart")
def chart(
    uuid: str = typer.Option(..., "--uuid", help="图表 UUID（chart_uuid）"),
    run: bool = typer.Option(False, "--run", help="获取后立即执行所有查询并合并输出"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅生成 SQL，不执行查询"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """通过 chart_uuid 获取图表查询结构，可选立即执行。"""
    manager = QueryManager()
    try:
        if run or dry_run:
            result = manager.run_chart_queries(chart_uuid=uuid, dry_run=dry_run)
            payload = {
                "success": True,
                "command": "query chart-run",
                "data": result,
                "error": None,
            }
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
    run: bool = typer.Option(False, "--run", help="构造后立即执行查询"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """基于简化参数构造标准 query payload。"""
    manager = QueryManager()
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
            "skills_dir": skills_dir,
        }
        result = manager.build_and_run(**common_kwargs) if run else manager.build(**common_kwargs)
        payload = {
            "success": True,
            "command": "query build-and-run" if run else "query build",
            "data": result,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query build-and-run" if run else "query build", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("simple")
def simple(
    table_id: int = typer.Option(..., "--table-id", help="数据集 ID"),
    payload_file: str | None = typer.Option(None, "--payload", help="简化查询 JSON 文件路径（与 --json 二选一）"),
    payload_json: str | None = typer.Option(None, "--json", help="简化查询 JSON 字符串（与 --payload 二选一）"),
    output: str | None = typer.Option(None, "--output", help="将 payload 写入指定文件"),
    run: bool = typer.Option(False, "--run", help="构造后立即执行查询"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """基于简化参数构造 simple query payload 并可选执行。"""
    manager = QueryManager()
    try:
        if payload_file and payload_json:
            raise InvalidPayloadError("--payload 和 --json 只能使用一种")

        simple_params: dict = {}
        if payload_file:
            pf = Path(payload_file).expanduser()
            if not pf.exists():
                raise InvalidPayloadError(f"payload 文件不存在: {pf}")
            simple_params = json.loads(pf.read_text(encoding="utf-8"))
        elif payload_json:
            simple_params = json.loads(payload_json)

        kwargs: dict[str, object] = {"table_id": table_id}

        key_map = {
            "dimensions": "dimensions",
            "metrics": "metrics",
            "filters": "filters",
            "dataComparison": "data_comparison",
            "orderBy": "order_by",
        }
        for key, kwarg_key in key_map.items():
            if key in simple_params:
                kwargs[kwarg_key] = simple_params[key]

        if "limit" in simple_params:
            kwargs["limit"] = simple_params["limit"]
        if "offset" in simple_params:
            kwargs["offset"] = simple_params["offset"]
        if "dryRun" in simple_params:
            kwargs["dry_run"] = simple_params["dryRun"]
        if output:
            kwargs["output_path"] = output

        result = manager.build_simple_and_run(**kwargs) if run else manager.build_simple(**kwargs)
        payload = {
            "success": True,
            "command": "query simple-run" if run else "query simple",
            "data": result,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("query simple-run" if run else "query simple", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)
