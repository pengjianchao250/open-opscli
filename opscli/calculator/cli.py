"""新品计算器 CLI 命令。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import typer
from rich.console import Console
from rich.table import Table

from opscli.calculator.client import CalculatorClient
from opscli.calculator.draft import (
    DRAFT_CSV_FILENAME,
    DRAFT_JSON_FILENAME,
    WEB_CALCULATOR_URL,
    build_field_options,
    build_summary_text,
    create_draft_package,
    load_draft_data,
    prepare_submit_payload,
    read_options_cache,
    validate_draft_data,
    write_options_cache,
)
from opscli.calculator.models import build_query_payload, read_json_file

app = typer.Typer(help="新品计算器")
console = Console()

TRIAL_RESULT_PLANS = ("mfn", "fba", "wfs")
CALCULATOR_TMP_DIR = Path("tmp-validation") / "calculator"
DEFAULT_DRAFT_OUT = CALCULATOR_TMP_DIR / "calculator-draft"
DEFAULT_COPY_OUT = CALCULATOR_TMP_DIR / "calculator-draft-copy"

TRIAL_RESULT_PLAN_LABELS = {
    "mfn": "自发货",
    "fba": "FBA",
    "wfs": "WFS",
}
TRIAL_RESULT_ROW_DEFS = [
    {"label": "售价", "field": "sales_price", "range_field": "sales_price_range"},
    {"label": "毛利", "field": "gross_profit", "range_field": "gross_profit_range"},
    {"label": "毛利率", "field": "gross_profit_percent", "range_field": "gross_profit_percent_range", "is_percent": True},
    {"label": "非税采购价", "field": "purchase_cost", "percent_field": "purchase_cost_percent"},
    {"label": "头程费用", "field": "first_leg", "percent_field": "first_leg_percent"},
    {"label": "仓库费用", "field": "storage_fees", "percent_field": "storage_fees_percent"},
    {"label": "尾程费用", "field": "freight", "percent_field": "freight_percent"},
    {"label": "站内广告", "field": "advertising_fee", "percent_field": "advertising_fee_percent"},
    {"label": "站外促销", "field": "marketing_fee", "percent_field": "marketing_fee_percent"},
    {"label": "平台佣金", "field": "fee", "percent_field": "fee_percent"},
    {"label": "退款费", "field": "refund", "percent_field": "refund_percent"},
    {"label": "固定成本", "field": "fixed_cost", "percent_field": "fixed_cost_percent"},
    {"label": "备注", "remark": True},
]


@app.callback()
def main() -> None:
    """新品计算器命令组入口。"""


def _exit_with_error(message: str) -> None:
    """输出错误并以失败状态退出。"""
    typer.echo(message)
    raise typer.Exit(1)


def _extract_response_data(response: dict, action: str) -> dict:
    """提取后端成功响应中的 data。"""
    if response.get("code") != 200:
        message = response.get("message") or "未知错误"
        _exit_with_error(f"{action}失败：{message}")
    data = response.get("data") or {}
    if not isinstance(data, dict):
        _exit_with_error(f"{action}失败：后端 data 不是对象。")
    return data


def _calculator_request_timestamp() -> int:
    """生成 Polaris 新品计算器请求时间戳。"""
    return int(time.time())


def _calculator_detail_url(task_code: str, sudo: str | None = None) -> str:
    """生成 Polaris Web 新品试算详情页 URL。"""
    base_url = os.environ.get("OPSCLI_CALCULATOR_DETAIL_URL", "https://bi.xenkee.com/#/calculatorDatail")
    query = {"task_code": task_code}
    if sudo:
        query["sudo"] = sudo
    return f"{base_url}?{urlencode(query)}"


def _string_value(value: object) -> str | None:
    """将非空值转换为字符串。"""
    if value is None or value == "":
        return None
    return str(value)


def _display_value(value: object) -> str:
    """转换为用户可读展示值。"""
    text = _string_value(value)
    return text if text is not None else "未填写"


def _dict_value(data: dict, key: str) -> dict:
    """安全读取嵌套对象字段。"""
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _task_code_from(data: dict, fallback: str | None = None) -> str | None:
    """从后端数据中提取任务编号。"""
    return _string_value(data.get("task_code") or data.get("taskCode") or data.get("task_id") or data.get("taskId") or fallback)


def _sudo_from(data: dict, fallback: str | None = None) -> str | None:
    """从后端数据中提取代查标识。"""
    return _string_value(data.get("sudo") or fallback)


def _detail_command_text(task_code: str, sudo: str | None = None, json_output: bool = False) -> str:
    """生成详情查询命令文本。"""
    command = f"opscli calculator detail --task-code {task_code}"
    if sudo:
        command += f" --sudo {sudo}"
    if json_output:
        command += " --json"
    return command


def _echo_web_detail_hint(task_code: str, sudo: str | None = None) -> None:
    """输出 Web 详情页和原始 JSON 提示。"""
    typer.echo("完整结果：")
    typer.echo("- Web 页面包含基本信息、产品信息、成本费用、备货设置、试算结果、当前方案和方案切换。")
    typer.echo(f"- Web详情页：{_calculator_detail_url(task_code, sudo)}")
    typer.echo(f"- 原始JSON：{_detail_command_text(task_code, sudo, json_output=True)}")


def _echo_draft_fill_hint(package_dir: Path) -> None:
    """输出草稿包推荐填写方式，避免用户直接替换 JSON。"""
    typer.echo("推荐填写方式：")
    typer.echo(f"1. 打开 {package_dir / DRAFT_CSV_FILENAME}")
    typer.echo("2. 只填写“请填写”这一列")
    typer.echo(f"3. 保存后运行：opscli calculator validate {package_dir}")
    typer.echo("")
    typer.echo("如果你不想本地填写，也可以使用网页端新品计算器：")
    typer.echo(WEB_CALCULATOR_URL)
    typer.echo("")
    typer.echo("高级用户仍可查看 draft.json，但不建议手动替换整个 JSON。")


def _echo_csv_sync_hint(synced: bool) -> None:
    """目录模式读取 CSV 后给出同步提示。"""
    if synced:
        typer.echo(f"已读取 {DRAFT_CSV_FILENAME} 的“请填写”列，并同步到 draft.json。")
        typer.echo("")


def _option_cache_country(data: dict | None = None, fallback: str | None = None) -> str:
    """提取下拉缓存所需站点，默认使用 US。"""
    value = (data or {}).get("country_code") or fallback or "US"
    return str(value)


def _response_data_or_raise(response: dict, action: str) -> dict:
    """提取下拉响应 data，失败时抛 RuntimeError 以便缓存兜底。"""
    if response.get("code") != 200:
        raise RuntimeError(f"{action}失败：{response.get('message') or '未知错误'}")
    data = response.get("data") or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{action}失败：后端 data 不是对象。")
    return data


def _fetch_option_cache(client: CalculatorClient, country: str) -> dict:
    """实时获取公共下拉和站点分区仓库下拉数据。"""
    dropdown = _response_data_or_raise(client.dropdown_list(), "获取下拉数据")
    zones = _response_data_or_raise(client.zones_warehouse_list(country), "获取仓库分区")
    return {"dropdown_list": dropdown, "zones_warehouse_list": zones}


def _load_option_cache_for_directory(package_dir: Path, data: dict) -> dict | None:
    """目录模式优先取实时下拉，失败时回退草稿包内快照。"""
    try:
        option_cache = _fetch_option_cache(CalculatorClient(), _option_cache_country(data))
    except RuntimeError:
        return read_options_cache(package_dir)
    write_options_cache(package_dir, option_cache)
    return option_cache


def _load_draft_or_exit(draft_path: Path, sync_csv: bool = False) -> tuple[Path, dict, bool]:
    """读取草稿数据，CSV 或 JSON 格式错误时输出中文错误。"""
    try:
        if sync_csv and draft_path.is_dir():
            draft_json_path = draft_path / DRAFT_JSON_FILENAME
            data = read_json_file(draft_json_path)
            option_cache = _load_option_cache_for_directory(draft_path, data)
            return load_draft_data(draft_path, sync_csv=sync_csv, field_options=build_field_options(option_cache))
        return load_draft_data(draft_path, sync_csv=sync_csv)
    except (OSError, ValueError, RuntimeError) as exc:
        _exit_with_error(str(exc))


def _handle_remote_error(action: str, exc: RuntimeError, task_code: str | None = None) -> None:
    """将远程调用异常转换为面向用户的错误提示。"""
    message = str(exc)
    tips: list[str] = []
    if "timed out" in message.lower() or "超时" in message:
        tips.append("接口响应超时，请稍后重试。")
        if task_code:
            tips.append(f"可先查询列表状态：opscli calculator list --task-code {task_code} --json")
    detail = f"{action}失败：{message}"
    if tips:
        detail += "\n" + "\n".join(tips)
    _exit_with_error(detail)


def _trial_result_channels(trial_result: dict) -> list[str]:
    """提取前端试算结果表格可展示的方案列。"""
    return [name for name in TRIAL_RESULT_PLANS if isinstance(trial_result.get(name), dict)]


def _format_decimal(value: object, bit: int = 2) -> str:
    """按前端 keepDecimal 风格展示数值。"""
    if value is None or value == "":
        return "未填写"
    if isinstance(value, bool):
        return str(value)
    try:
        return f"{float(value):.{bit}f}"
    except (TypeError, ValueError):
        return str(value)


def _format_range(value: object, is_percent: bool = False) -> str | None:
    """格式化前端试算结果 range 第二行。"""
    if not isinstance(value, list | tuple) or len(value) < 2:
        return None
    first = _format_decimal(value[0])
    second = _format_decimal(value[1])
    if is_percent:
        return f"({first}%~{second}%)"
    return f"({first}~{second})"


def _format_percent_line(value: object) -> str | None:
    """格式化前端费用占比第二行。"""
    if value is None or value == "":
        return None
    return f"({_format_decimal(value)}%)"


def _format_trial_value(plan_data: dict, row_def: dict) -> str:
    """格式化试算结果单元格，匹配前端 trial-result-teble。"""
    if row_def.get("remark"):
        return _format_trial_remark(plan_data)

    field = str(row_def["field"])
    is_percent = bool(row_def.get("is_percent"))
    value = _format_decimal(plan_data.get(field))
    if is_percent and value != "未填写":
        value += "%"

    lines = [value]
    range_line = _format_range(plan_data.get(str(row_def.get("range_field"))), is_percent) if row_def.get("range_field") else None
    percent_line = _format_percent_line(plan_data.get(str(row_def.get("percent_field")))) if row_def.get("percent_field") else None
    if range_line:
        lines.append(range_line)
    if percent_line:
        lines.append(percent_line)
    return "\n".join(lines)


def _format_trial_remark(plan_data: dict) -> str:
    """格式化试算结果备注行。"""
    warehouses = plan_data.get("warehouses")
    if isinstance(warehouses, list):
        areas = [_string_value(item.get("area")) for item in warehouses if isinstance(item, dict)]
        areas = [area for area in areas if area]
        if areas:
            return "备货仓库：" + "、".join(areas)

    remark = plan_data.get("remark")
    if isinstance(remark, dict):
        parts = []
        size = _string_value(remark.get("size"))
        first = _string_value(remark.get("first"))
        if size:
            parts.append(f"尺寸等级：{size}")
        if first:
            parts.append(f"头程路线：{first}")
        if parts:
            return "; ".join(parts)
    return "未填写"


def _cost_summary_from(cost: object) -> dict:
    """兼容前端列表结构和 CLI 测试中的对象结构读取成本摘要。"""
    if isinstance(cost, dict):
        return cost
    if isinstance(cost, list) and cost and isinstance(cost[0], dict):
        return cost[0]
    return {}


def _calc_method_from(cost: object) -> str | None:
    """兼容前端列表结构和 CLI 测试中的对象结构读取试算方式。"""
    return _string_value(_cost_summary_from(cost).get("calc_method"))


def _ordered_trial_result_rows(calc_method: str | None) -> list[dict]:
    """按前端规则调整试算结果行顺序。"""
    rows = list(TRIAL_RESULT_ROW_DEFS)
    if calc_method == "GROSS_PROFIT" and len(rows) >= 3:
        first = rows.pop(0)
        rows.insert(2, first)
    return rows


def _render_trial_result_table(trial_result: dict, base: dict, cost: object) -> bool:
    """渲染前端 trial-result-teble 对应的“试算结果”表格。"""
    channels = _trial_result_channels(trial_result)
    if not channels:
        return False

    currency = _string_value(base.get("currency")) or "USD"
    winner = _string_value(trial_result.get("winner"))
    winner_lower = winner.lower() if winner else None
    table = Table(title="试算结果", show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("费用", style="cyan")
    for channel in channels:
        label = f"{TRIAL_RESULT_PLAN_LABELS[channel]}({currency})"
        if winner_lower and channel == winner_lower:
            label += " 推荐"
        table.add_column(label, justify="right")

    for row_def in _ordered_trial_result_rows(_calc_method_from(cost)):
        values = [_format_trial_value(trial_result[channel], row_def) for channel in channels]
        table.add_row(str(row_def["label"]), *values)

    console.print(table)
    return True


@app.command("search-category")
def search_category_command(
    keyword: str = typer.Argument(..., help="海关类目关键词，如 数据线"),
    limit: int = typer.Option(20, "--limit", help="最多显示数量"),
    json_output: bool = typer.Option(False, "--json", help="输出原始匹配 JSON"),
) -> None:
    """按关键词搜索海关类目。"""
    response = CalculatorClient().dropdown_list()
    data = _extract_response_data(response, "搜索海关类目")
    categories = data.get("customs_category") or []
    keyword_lower = keyword.lower()
    matches = [item for item in categories if keyword_lower in str(item.get("value", "")).lower()]
    matches = matches[:limit]
    if json_output:
        typer.echo(json.dumps(matches, ensure_ascii=False, indent=2))
        return
    typer.echo(f"海关类目搜索结果：{keyword}")
    if not matches:
        typer.echo("- 未找到匹配类目，请换一个关键词。")
        return
    for item in matches:
        typer.echo(f"- {item.get('key')}: {item.get('value')}")


@app.command("recommend")
def recommend_command() -> None:
    """输出第一轮真实联调推荐参数。"""
    typer.echo("推荐第一轮烟测参数")
    typer.echo("")
    typer.echo("试算站点：US（美国）")
    typer.echo("试算平台：1 + 7（亚马逊 + 沃尔玛）")
    typer.echo("海关类目：4（8544421100-USB数据线）")
    typer.echo("")
    typer.echo("生成草稿包命令：")
    typer.echo(f"opscli calculator draft --country US --platform 1 --platform 7 --hs-code-id 4 --out {CALCULATOR_TMP_DIR / 'calculator-draft-test'}")


@app.command("draft")
def draft_command(
    country: str | None = typer.Option(None, "--country", help="试算站点，如 US"),
    platform: list[int] | None = typer.Option(None, "--platform", help="试算平台，可重复传入"),
    hs_code_id: int | None = typer.Option(None, "--hs-code-id", help="海关类目 ID"),
    department: str | None = typer.Option(None, "--department", help="部门 ID"),
    reference: str = typer.Option("NONE", "--reference", help="试算参考类型"),
    reference_value: str | None = typer.Option(None, "--reference-value", help="试算参考值"),
    payload: Path | None = typer.Option(None, "--payload", help="第一阶段参数 JSON 文件"),
    out: Path = typer.Option(DEFAULT_DRAFT_OUT, "--out", help="草稿包输出目录，默认写入 tmp-validation/calculator"),
) -> None:
    """根据第一阶段参数生成试算草稿包。"""
    payload_data = read_json_file(payload) if payload else None
    query_payload = build_query_payload(
        country=country,
        platforms=platform,
        hs_code_id=hs_code_id,
        department=department,
        reference=reference,
        reference_value=reference_value,
        payload=payload_data,
    )
    client = CalculatorClient()
    response = client.query_cost(query_payload)
    data = {**query_payload, **_extract_response_data(response, "生成草稿")}
    option_cache = _fetch_option_cache(client, _option_cache_country(data, country))
    draft_path = create_draft_package(data, out, option_cache=option_cache)
    package_dir = draft_path.parent
    typer.echo(f"已生成试算草稿包：{package_dir}")
    typer.echo("")
    typer.echo(build_summary_text(read_json_file(draft_path)))
    typer.echo("")
    _echo_draft_fill_hint(package_dir)


@app.command("show")
def show_command(draft_path: Path = typer.Argument(..., help="草稿目录或 draft.json 路径")) -> None:
    """查看草稿中文摘要。"""
    _, data, _ = _load_draft_or_exit(draft_path)
    typer.echo(build_summary_text(data))


@app.command("validate")
def validate_command(draft_path: Path = typer.Argument(..., help="草稿目录或 draft.json 路径")) -> None:
    """校验试算草稿。"""
    resolved_path, data, synced = _load_draft_or_exit(draft_path, sync_csv=True)
    _echo_csv_sync_hint(synced)
    issues = validate_draft_data(data)
    if issues:
        typer.echo("校验失败，需要处理以下问题：")
        typer.echo("")
        for issue in issues:
            typer.echo(f"- {issue.message}")
        raise typer.Exit(1)
    typer.echo("校验通过，可以提交试算。")
    typer.echo(f"提交命令：opscli calculator submit {resolved_path.parent}")


@app.command("submit")
def submit_command(draft_path: Path = typer.Argument(..., help="草稿目录或 draft.json 路径")) -> None:
    """提交试算任务。"""
    _, data, synced = _load_draft_or_exit(draft_path, sync_csv=True)
    _echo_csv_sync_hint(synced)
    issues = validate_draft_data(data)
    if issues:
        typer.echo("校验失败，未提交试算：")
        typer.echo("")
        for issue in issues:
            typer.echo(f"- {issue.message}")
        raise typer.Exit(1)

    response = CalculatorClient().do_calc(prepare_submit_payload(data))
    if response.get("code") != 200 or response.get("message") not in (None, "success"):
        _exit_with_error(f"提交失败：{response.get('message') or '未知错误'}")
    result_data = response.get("data") if isinstance(response.get("data"), dict) else {}
    task_code = _task_code_from(result_data)
    sudo = _sudo_from(result_data)
    typer.echo("提交成功，试算任务已创建。")
    typer.echo("")
    if task_code:
        typer.echo(f"任务编号：{task_code}")
        if sudo:
            typer.echo(f"代查标识：{sudo}")
        typer.echo("说明：试算过程数据量较大，结果可能需要稍后生成。")
        typer.echo("")
        typer.echo(f"查看列表：opscli calculator list --task-code {task_code}")
        typer.echo(f"查看详情：{_detail_command_text(task_code, sudo)}")
        typer.echo(f"Web详情页：{_calculator_detail_url(task_code, sudo)}")
    else:
        typer.echo("后端未返回任务编号，请稍后通过列表查询最近任务。")
        typer.echo("查看列表：opscli calculator list")
        typer.echo("从列表中复制 task_code 与 sudo 后查看详情：")
        typer.echo("opscli calculator detail --task-code <TASK_CODE> --sudo <SUDO>")
        typer.echo("Web详情页格式：https://bi.xenkee.com/#/calculatorDatail?task_code=<TASK_CODE>&sudo=<SUDO>")


@app.command("dropdown-list")
def dropdown_list_command(json_output: bool = typer.Option(False, "--json", help="输出原始 JSON")) -> None:
    """获取公共下拉数据。"""
    response = CalculatorClient().dropdown_list()
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False, indent=2))
        return
    data = _extract_response_data(response, "获取下拉数据")
    typer.echo("已获取新品计算器下拉数据。")
    typer.echo(f"字段：{', '.join(data.keys())}")


@app.command("zones")
def zones_command(
    country: str = typer.Option(..., "--country", help="试算站点，如 US"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
) -> None:
    """获取站点仓库与分区数据。"""
    response = CalculatorClient().zones_warehouse_list(country)
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False, indent=2))
        return
    data = _extract_response_data(response, "获取仓库分区")
    warehouses = data.get("by_warehouses") or data.get("warehouses") or []
    typer.echo(f"站点 {country} 仓库分区数据：")
    if not warehouses:
        typer.echo("- 暂无仓库数据")
        return
    for warehouse in warehouses:
        if isinstance(warehouse, dict):
            key = warehouse.get("key", warehouse.get("id", "-"))
            value = warehouse.get("value", warehouse.get("name", "-"))
            typer.echo(f"- {key}: {value}")


@app.command("list")
def list_command(
    task_code: str | None = typer.Option(None, "--task-code", help="任务编号"),
    page: int = typer.Option(1, "--page", help="页码"),
    limit: int = typer.Option(20, "--limit", help="每页数量"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
) -> None:
    """查询新品试算任务列表。"""
    payload = {"page": page, "limit": limit}
    if task_code:
        payload["task_code"] = task_code
    response = CalculatorClient().forecast_list(payload)
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False, indent=2))
        return
    data = _extract_response_data(response, "查询任务列表")
    rows = data.get("list") or data.get("records") or []
    typer.echo("试算任务列表")
    typer.echo(f"总数：{data.get('total', len(rows))}")
    for row in rows:
        if isinstance(row, dict):
            code = _task_code_from(row) or "-"
            country = row.get("country_code") or row.get("countryCode") or "-"
            sudo_value = _sudo_from(row)
            line = f"- {code} / {country}"
            if sudo_value:
                line += f" / sudo={sudo_value}"
            typer.echo(line)
            if code != "-":
                typer.echo(f"  详情：{_detail_command_text(code, sudo_value)}")
                typer.echo(f"  Web：{_calculator_detail_url(code, sudo_value)}")


@app.command("detail")
def detail_command(
    task_code: str = typer.Option(..., "--task-code", help="任务编号"),
    sudo: str | None = typer.Option(None, "--sudo", help="代查标识，复制网页链接时可带入"),
    json_output: bool = typer.Option(False, "--json", help="输出原始 JSON"),
) -> None:
    """查询新品试算任务详情。"""
    payload = {"task_code": task_code, "_t": _calculator_request_timestamp()}
    if sudo:
        payload["sudo"] = sudo
    try:
        response = CalculatorClient().task_details(payload)
    except RuntimeError as exc:
        _handle_remote_error("查询任务详情", exc, task_code)
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False, indent=2))
        return
    data = _extract_response_data(response, "查询任务详情")
    resolved_task_code = _task_code_from(data, task_code) or task_code
    resolved_sudo = _sudo_from(data, sudo)
    base = _dict_value(data, "base")
    raw_cost = data.get("cost")
    cost = _cost_summary_from(raw_cost)
    trial_result = _dict_value(data, "trial_result")

    typer.echo("任务详情")
    typer.echo(f"任务编号：{resolved_task_code}")
    typer.echo(f"任务名称：{_display_value(data.get('task_name'))}")
    typer.echo(f"任务状态：{_display_value(data.get('task_status_text') or data.get('task_status'))}")
    typer.echo(f"数据生成于：{_display_value(data.get('calc_date'))}")
    typer.echo("")
    typer.echo("基本信息")
    typer.echo(f"- 试算站点：{_display_value(base.get('country') or data.get('country_code'))}")
    typer.echo(f"- 海关类目：{_display_value(base.get('hs_name') or data.get('hs_name'))}")
    typer.echo(f"- 试算平台：{_display_value(base.get('platforms') or data.get('platforms'))}")
    typer.echo(f"- 试算参考：{_display_value(base.get('trial_refer') or data.get('trial_refer'))}")
    typer.echo("")
    typer.echo("成本摘要")
    typer.echo(f"- 商品售价：{_display_value(cost.get('product_price') or data.get('product_price'))}")
    typer.echo(f"- 商品毛利：{_display_value(cost.get('gross_profit_percent') or data.get('gross_profit_percent'))}")
    typer.echo(f"- 含税采购价：{_display_value(cost.get('purchase_cost_with_tax') or data.get('purchase_cost_with_tax'))}")
    typer.echo("")
    if trial_result:
        winner = _display_value(trial_result.get("winner"))
        available = [name.upper() for name in TRIAL_RESULT_PLANS if trial_result.get(name)]
        typer.echo("试算结果摘要")
        typer.echo(f"- 可用方案：{', '.join(available) if available else '未返回'}")
        typer.echo(f"- 推荐方案：{winner}")
        typer.echo("")
        if _render_trial_result_table(trial_result, base, cost):
            typer.echo("")
        else:
            typer.echo("试算结果表格字段未返回，请使用原始JSON查看完整详情。")
            typer.echo("")
    _echo_web_detail_hint(resolved_task_code, resolved_sudo)


@app.command("copy")
def copy_command(
    task_code: str = typer.Option(..., "--task-code", help="任务编号"),
    sudo: str | None = typer.Option(None, "--sudo", help="代查标识，复制网页链接时可带入"),
    out: Path = typer.Option(DEFAULT_COPY_OUT, "--out", help="草稿包输出目录，默认写入 tmp-validation/calculator"),
) -> None:
    """复制历史试算任务为本地草稿包。"""
    payload = {"task_code": task_code, "_t": _calculator_request_timestamp()}
    if sudo:
        payload["sudo"] = sudo
    client = CalculatorClient()
    try:
        response = client.copy_task(payload)
    except RuntimeError as exc:
        _handle_remote_error("复制任务", exc, task_code)
    data = _extract_response_data(response, "复制任务")
    option_cache = _fetch_option_cache(client, _option_cache_country(data))
    draft_path = create_draft_package(data, out, option_cache=option_cache)
    package_dir = draft_path.parent
    typer.echo(f"已复制试算任务为草稿包：{package_dir}")
    typer.echo("")
    typer.echo(build_summary_text(read_json_file(draft_path)))
    typer.echo("")
    _echo_draft_fill_hint(package_dir)
