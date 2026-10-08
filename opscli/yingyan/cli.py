"""鹰眼 PND 远端 MCP 正式 CLI。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opscli.yingyan.remote_adapter import YingyanRemoteAdapter


app = typer.Typer(help="鹰眼 PND 远端 MCP 正式命令面。")


@app.command("datasets")
def datasets() -> None:
    """读取当前用户可访问的鹰眼数据集目录。"""
    _emit(YingyanRemoteAdapter().list_available_datasets())


@app.command("execute-sql")
def execute_sql(
    sql: str | None = typer.Option(None, "--sql", help="单条只读 SQL"),
    sql_file: Path | None = typer.Option(
        None,
        "--sql-file",
        help="UTF-8 SQL 文件路径，避免命令行转义问题",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """执行一条经过鹰眼目录约束的只读 SQL。"""
    query = _read_sql(sql=sql, sql_file=sql_file)
    _emit(YingyanRemoteAdapter().execute_readonly_sql(query))


@app.command("search-similar-terms")
def search_similar_terms(
    search_term: str = typer.Argument(..., help="单个明确的种子搜索词"),
    site: str | None = typer.Option("US", "--site", help="Amazon 站点，如 US、JP、DE"),
    top: int = typer.Option(20, "--top", min=1, max=1100, help="返回词数量，范围 1-1100"),
) -> None:
    """查询鹰眼相似搜索词。"""
    _emit(
        YingyanRemoteAdapter().search_similar_terms(
            search_term=search_term,
            site=site,
            top=top,
        )
    )


@app.command("report-task-status")
def report_task_status(task_id: str = typer.Argument(..., help="已有报告任务 ID")) -> None:
    """查询已有鹰眼报告任务状态。"""
    _emit(YingyanRemoteAdapter().report_task_status(task_id))


def _read_sql(*, sql: str | None, sql_file: Path | None) -> str:
    """从参数或 UTF-8 文件读取 SQL，且强制二选一。"""
    if bool(sql and sql.strip()) == bool(sql_file):
        raise typer.BadParameter("必须且只能提供 --sql 或 --sql-file 其中一个")

    if sql_file is not None:
        query = sql_file.read_text(encoding="utf-8-sig")
    else:
        query = sql or ""

    query = query.strip()
    if not query:
        raise typer.BadParameter("SQL 不能为空")
    return query


def _emit(payload: dict) -> None:
    """以稳定 JSON 结构输出远端响应。"""
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
