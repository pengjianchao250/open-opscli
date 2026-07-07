"""query CLI 子命令定义。"""

from __future__ import annotations

import json
import sys
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
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """读取指定数据集的 query metadata，不传任何参数时默认获取所有数据集"""
    manager = QueryManager()
    try:
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


# 【临时屏蔽】catalog 命令暂停对外暴露，恢复时取消下一行注释即可
# @app.command("catalog")
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


# 【临时屏蔽】intent 命令暂停对外暴露，恢复时取消下一行注释即可
# @app.command("intent")
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
    dataset: str | None = typer.Option(None, "--dataset", help="dataset_alias 或 dataset_name，用于字段校验"),
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
                hint = ""
                if payload_json.startswith("{'"):
                    hint = "\n  提示: 检测到单引号包裹的 JSON，请改用双引号"
                elif "\\\\" in payload_json and sys.platform == "win32":
                    hint = (
                        "\n  提示: Windows PowerShell 中 --json 内联传参容易因引号转义导致 JSON 被破坏"
                        "\n  建议改用 --payload <文件路径> 传参，并使用 UTF-8 无 BOM 编码保存")
                raise InvalidPayloadError(
                    f"JSON 字符串解析失败: {exc}{hint}"
                ) from exc

        kwargs: dict[str, object] = {"table_id": table_id, "dataset_alias": dataset}

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
        kwargs["validate_fields"] = True

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
