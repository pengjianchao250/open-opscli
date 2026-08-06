"""生成内部反馈 Markdown 日报并可选推送企业微信群机器人。

脚本默认统计 Asia/Shanghai 时区的完整昨日，自动翻页读取反馈列表，
仅使用非敏感列表字段生成报告和群消息。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

import httpx

from opscli.config import CONFIG_DIR
from opscli.feedback.services.insight import INSIGHT_PROMPT_HASH, INSIGHT_PROMPT_VERSION

# Skill 脚本不是 Python 包，将同目录加入导入路径以复用已有查询客户端。
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from query_feedbacks import (  # noqa: E402
    CREDENTIALS_PATH,
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    FeedbackQueryClient,
    FeedbackQueryError,
    load_api_key,
    resolve_output_path,
)


# 日报默认使用上海时区，确保“昨日”符合内部工作日口径。
SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
# Skill 通过正式 opscli 命令发送通知，避免直接访问反馈接口以外的远端服务。
NOTIFY_COMMAND_TIMEOUT = 15.0
# 洞察子进程按批次数计算兜底上限，覆盖每批两次 300 秒模型读取和启动收尾余量。
INSIGHT_BATCH_TIMEOUT_BUDGET = 600.0
INSIGHT_COMMAND_TIMEOUT_MARGIN = 60.0
INSIGHT_COMMAND_TIMEOUT_MAX = 3600.0
DEFAULT_INSIGHT_BATCH_SIZE = 100
# 结构化中间产物版本供后续周报、月报选择兼容的运行快照。
RUN_ARTIFACT_SCHEMA_VERSION = "1.0"
# 与 `opscli feedback insight` 使用同一默认配置路径，确保批次数预算一致。
DEFAULT_INSIGHT_CONFIG = CONFIG_DIR / "feedback_insight.json"
# 企业微信 markdown_v2.content 官方上限为 4096 字节。
WECOM_CONTENT_BYTES = 4096
FEEDBACK_DETAIL_URL = "https://ops.xenkee.com/dashboard/share/3e2W4spQ"
# 列表标题可能由用户或 Agent 生成，统一清理常见个人信息和凭据形态。
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
WINDOWS_USER_PATH_PATTERN = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+\\[^\s|]*")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
URL_PATTERN = re.compile(r"https?://[^\s|]+", re.IGNORECASE)
SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|token|cookie|authorization|webhook)\b\s*[:=]\s*[^\s|]+"
)
AUTHORIZATION_PATTERN = re.compile(
    r"(?i)\bauthorization\b\s*[:=]\s*(?:bearer\s+)?[^\s|]+"
)
# HTML 注释标记只供本地浏览器组合双列布局，其他 Markdown 查看器会自然忽略。
DISTRIBUTION_GRID_START = "<!-- feedback-distribution-grid:start -->"
DISTRIBUTION_GRID_END = "<!-- feedback-distribution-grid:end -->"
DISTRIBUTION_PANEL_START = "<!-- feedback-distribution-panel:start -->"
DISTRIBUTION_PANEL_END = "<!-- feedback-distribution-panel:end -->"
# 以下成对标记界定问题分布双列表格，供本地渲染器安全组合布局。
PROBLEM_DISTRIBUTION_GRID_START = "<!-- feedback-problem-distribution-grid:start -->"
PROBLEM_DISTRIBUTION_GRID_END = "<!-- feedback-problem-distribution-grid:end -->"
PROBLEM_DISTRIBUTION_PANEL_START = "<!-- feedback-problem-distribution-panel:start -->"
PROBLEM_DISTRIBUTION_PANEL_END = "<!-- feedback-problem-distribution-panel:end -->"


class DailyReportError(Exception):
    """表示日报参数、响应、文件或企业微信推送失败。"""


class ReportWindow(NamedTuple):
    """反馈日报查询时间窗口。"""

    date_from: str
    date_to: str
    label: str


class RunContext(NamedTuple):
    """日报单次尝试的稳定身份和产物目录。"""

    run_id: str
    run_key: str
    period_key: str
    generated_at: datetime
    window: ReportWindow
    directory: Path


class RunOutcome(NamedTuple):
    """日报分析、归档和通知完成后的结构化结果。"""

    comparison_window: ReportWindow | None
    base_metrics: dict[str, Any]
    source_snapshots: dict[str, str | None]
    insight: dict[str, Any] | None
    insight_requested: bool
    insight_error: dict[str, str] | None
    insight_runtime: dict[str, Any]
    published_report_path: Path
    archived_report_path: Path
    notification: dict[str, Any]
    timings_ms: dict[str, float]


def _parse_datetime(value: str, label: str) -> datetime:
    """解析日报命令的本地日期时间。"""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise DailyReportError(f"{label} 必须使用 YYYY-MM-DD HH:MM:SS 格式") from exc


def resolve_report_window(
    date_from: str | None,
    date_to: str | None,
    *,
    now: datetime | None = None,
) -> ReportWindow:
    """解析显式时间范围，未传时返回上海时区的完整昨日。

    Args:
        date_from: 可选查询起点。
        date_to: 可选查询终点。
        now: 测试或调用方指定的当前时间。

    Returns:
        查询参数和报告标题使用的时间窗口。

    Raises:
        DailyReportError: 仅传一端、格式错误或起点晚于终点。
    """
    if date_from is None and date_to is None:
        current = now or datetime.now(SHANGHAI_TIMEZONE)
        if current.tzinfo is None:
            current = current.replace(tzinfo=SHANGHAI_TIMEZONE)
        else:
            current = current.astimezone(SHANGHAI_TIMEZONE)
        yesterday = current.date() - timedelta(days=1)
        label = yesterday.isoformat()
        return ReportWindow(f"{label} 00:00:00", f"{label} 23:59:59", label)

    if date_from is None or date_to is None:
        raise DailyReportError("--date-from 和 --date-to 必须同时传入")

    start = _parse_datetime(date_from, "--date-from")
    end = _parse_datetime(date_to, "--date-to")
    if start > end:
        raise DailyReportError("--date-from 不能晚于 --date-to")
    label = start.date().isoformat()
    if start.date() != end.date():
        label = f"{start.date().isoformat()} 至 {end.date().isoformat()}"
    return ReportWindow(date_from, date_to, label)


def resolve_comparison_window(window: ReportWindow) -> ReportWindow:
    """返回与当前报告等长且紧邻的上一周期。"""
    start = _parse_datetime(window.date_from, "--date-from")
    end = _parse_datetime(window.date_to, "--date-to")
    previous_end = start - timedelta(seconds=1)
    previous_start = previous_end - (end - start)
    start_text = previous_start.strftime("%Y-%m-%d %H:%M:%S")
    end_text = previous_end.strftime("%Y-%m-%d %H:%M:%S")
    label = previous_start.date().isoformat()
    if previous_start.date() != previous_end.date():
        label = f"{previous_start.date().isoformat()} 至 {previous_end.date().isoformat()}"
    return ReportWindow(start_text, end_text, label)


def _per_page(value: str) -> int:
    """解析 1 到 100 的日报分页大小。"""
    parsed = int(value)
    if parsed < 1 or parsed > 100:
        raise argparse.ArgumentTypeError("必须在 1 到 100 之间")
    return parsed


def _positive_float(value: str) -> float:
    """解析大于 0 的超时秒数。"""
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """构造反馈 Markdown 日报命令参数。"""
    parser = argparse.ArgumentParser(description="生成反馈 Markdown 日报并可选推送企业微信")
    parser.add_argument("--date-from", help="查询起点，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--date-to", help="查询终点，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--per-page", type=_per_page, default=100, help="每页数量，默认 100")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="ops 服务根地址，不含 /api")
    parser.add_argument("--timeout", type=_positive_float, default=DEFAULT_TIMEOUT, help="查询超时秒数")
    parser.add_argument("--output", type=Path, help="Markdown 输出文件，仅允许 output/feedback-query/")
    parser.add_argument("--send", action="store_true", help="生成报告后发送企业微信 Markdown 摘要")
    parser.add_argument("--insight", action="store_true", help="调用大模型生成模块问题洞察和周期对比")
    parser.add_argument(
        "--insight-config",
        type=Path,
        help="反馈洞察模型配置文件；默认由 opscli 从用户配置目录读取",
    )
    return parser


def fetch_feedbacks(
    client: FeedbackQueryClient,
    window: ReportWindow,
    *,
    per_page: int,
) -> list[dict[str, Any]]:
    """自动翻页查询时间窗口内的反馈并按 UUID 去重。"""
    feedbacks: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        payload = client.list_feedbacks(
            {
                "feedback_type": "all",
                "date_from": window.date_from,
                "date_to": window.date_to,
                "sort_by": "created_at",
                "sort_direction": "asc",
                "page": page,
                "per_page": per_page,
            }
        )
        data = payload.get("data")
        rows = data.get("list") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise DailyReportError("反馈列表接口缺少 data.list 数组")

        for row in rows:
            if not isinstance(row, dict):
                raise DailyReportError("反馈列表包含非对象记录")
            feedback_uuid = row.get("feedback_uuid")
            if not isinstance(feedback_uuid, str) or not feedback_uuid.strip():
                raise DailyReportError("反馈列表记录缺少 feedback_uuid")
            feedbacks.setdefault(feedback_uuid, row)

        # 满页时继续请求下一页；空页或不足一页表示服务端已返回完毕。
        if len(rows) < per_page:
            break
        page += 1
    return list(feedbacks.values())


def fetch_feedback_details(
    client: FeedbackQueryClient,
    feedbacks: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """按 100 条一批读取问题反馈详情，并按 UUID 建立索引。"""
    uuids = [
        str(item["feedback_uuid"])
        for item in feedbacks
        if item.get("feedback_type") != "query_result"
    ]
    details: dict[str, dict[str, Any]] = {}
    for start in range(0, len(uuids), 100):
        payload = client.batch_detail(uuids[start : start + 100], "all")
        data = payload.get("data")
        rows = data.get("list") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise DailyReportError("反馈批量详情接口缺少 data 数组")
        for row in rows:
            if not isinstance(row, dict):
                raise DailyReportError("反馈批量详情包含非对象记录")
            feedback_uuid = str(row.get("feedback_uuid") or "").strip()
            if not feedback_uuid:
                raise DailyReportError("反馈批量详情记录缺少 feedback_uuid")
            details[feedback_uuid] = row
    return details


def _safe_insight_text(value: Any, maximum: int = 1000) -> str:
    """脱敏发送给本地 insight 命令的自由文本。"""
    text = " ".join(str(value or "").split())
    text = EMAIL_PATTERN.sub("[邮箱已脱敏]", text)
    text = WINDOWS_USER_PATH_PATTERN.sub("[本地路径已脱敏]", text)
    text = AUTHORIZATION_PATTERN.sub("Authorization=[凭据已脱敏]", text)
    text = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[凭据已脱敏]", text)
    text = URL_PATTERN.sub("[链接已脱敏]", text)
    return text[:maximum]


def _user_key(item: dict[str, Any]) -> str | None:
    """将用户标识哈希后仅用于影响人数计算。"""
    value = item.get("user_id") or item.get("user_email")
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def build_insight_feedbacks(
    feedbacks: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """构造不含 payload、context、附件和原始用户标识的洞察输入。"""
    result: list[dict[str, Any]] = []
    for item in feedbacks:
        if item.get("feedback_type") == "query_result":
            continue
        feedback_uuid = str(item["feedback_uuid"])
        detail = details.get(feedback_uuid, {})
        row: dict[str, Any] = {"feedback_uuid": feedback_uuid}
        for key in (
            "feedback_type",
            "severity",
            "source",
            "system_alias",
            "skill_name",
            "command_name",
            "mcp_tool_name",
            "app_version",
        ):
            value = detail.get(key, item.get(key))
            if value is not None:
                row[key] = _safe_insight_text(value, 200)
        for key in ("title", "content"):
            value = detail.get(key, item.get(key))
            if value:
                row[key] = _safe_insight_text(value)
        user_key = _user_key(item)
        if user_key:
            row["user_key"] = user_key

        execution_summary = detail.get("execution_summary")
        failed_calls = (
            execution_summary.get("failed_calls") if isinstance(execution_summary, dict) else None
        )
        if isinstance(failed_calls, list) and failed_calls and isinstance(failed_calls[0], dict):
            first_failure = failed_calls[0]
            for key in ("error_message", "reason", "fix_suggestion"):
                if first_failure.get(key):
                    row[key] = _safe_insight_text(first_failure[key])
        result.append(row)
    return result


def run_feedback_insight(
    payload: dict[str, Any],
    config_path: Path | None = None,
) -> dict[str, Any]:
    """通过正式 opscli 命令执行模型分类和聚合。"""
    batch_size = DEFAULT_INSIGHT_BATCH_SIZE
    effective_config_path = config_path or DEFAULT_INSIGHT_CONFIG
    if effective_config_path.exists():
        try:
            config_payload = json.loads(effective_config_path.read_text(encoding="utf-8"))
            configured_batch_size = int(config_payload.get("batch_size", batch_size))
            if 1 <= configured_batch_size <= 100:
                batch_size = configured_batch_size
        except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
            # 配置错误由正式 opscli 命令返回；这里只使用安全默认值计算兜底超时。
            pass
    feedback_count = sum(
        len(items)
        for items in (
            payload.get("current_feedbacks"),
            payload.get("comparison_feedbacks"),
        )
        if isinstance(items, list)
    )
    batch_count = max(1, math.ceil(feedback_count / batch_size))
    command_timeout = min(
        INSIGHT_COMMAND_TIMEOUT_MAX,
        batch_count * INSIGHT_BATCH_TIMEOUT_BUDGET + INSIGHT_COMMAND_TIMEOUT_MARGIN,
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        encoding="utf-8",
        delete=False,
    ) as input_file:
        json.dump(payload, input_file, ensure_ascii=False)
        input_path = Path(input_file.name)
    command = ["opscli", "feedback", "insight", "--input-file", str(input_path)]
    if config_path is not None:
        command.extend(["--config-file", str(config_path)])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=command_timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DailyReportError("未找到 opscli 命令，请先安装当前项目版本") from exc
    except subprocess.TimeoutExpired as exc:
        raise DailyReportError("opscli feedback insight 执行超时") from exc
    finally:
        try:
            input_path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DailyReportError("opscli feedback insight 未返回合法 JSON") from exc
    if result.returncode != 0 or not response.get("success"):
        error = response.get("error") if isinstance(response, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        raise DailyReportError(str(message or "opscli feedback insight 执行失败"))
    data = response.get("data")
    if not isinstance(data, dict):
        raise DailyReportError("opscli feedback insight 响应缺少 data 对象")
    return data


def _safe_text(value: Any, *, maximum: int = 200) -> str:
    """清理用户文本中的敏感信息、链接和 Markdown 控制符。"""
    text = " ".join(str(value or "-").split())
    # 标题虽来自列表接口，仍可能夹带用户主动粘贴的个人信息、路径或凭据。
    text = EMAIL_PATTERN.sub("[邮箱已脱敏]", text)
    text = WINDOWS_USER_PATH_PATTERN.sub("[本地路径已脱敏]", text)
    text = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[凭据已脱敏]", text)
    text = MARKDOWN_LINK_PATTERN.sub(lambda match: match.group(1), text)
    text = URL_PATTERN.sub("[链接已脱敏]", text)
    # 反斜杠和 Markdown 标记统一转义，防止标题改变表格或群消息结构。
    for character in ("\\", "|", "`", "*", "_", "[", "]", "(", ")"):
        text = text.replace(character, f"\\{character}")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    if len(text) > maximum:
        return f"{text[: maximum - 1]}…"
    return text


def _format_created_at(value: Any) -> str:
    """将接口 UTC 时间转换为上海时区展示。"""
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _safe_text(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _ordered_counts(
    counter: Counter[str],
    order: tuple[str, ...],
) -> list[tuple[str, int]]:
    """按固定维度优先、未知维度名称排序返回非零计数。"""
    items = [(name, counter[name]) for name in order if counter[name] > 0]
    known = set(order)
    items.extend(
        (name, count)
        for name, count in sorted(counter.items())
        if name not in known and count > 0
    )
    return items


def _count_rows(counter: Counter[str], order: tuple[str, ...]) -> list[str]:
    """按固定业务顺序生成 Markdown 统计表行。"""
    rows = [f"| {_safe_text(name)} | {count} |" for name, count in _ordered_counts(counter, order)]
    return rows or ["| - | 0 |"]


def _mermaid_pie(
    title: str,
    counter: Counter[str],
    order: tuple[str, ...],
) -> list[str]:
    """生成日报使用的安全 Mermaid 饼图。"""
    items = _ordered_counts(counter, order)
    if not items:
        return []
    rows = ["```mermaid", "pie showData", f"    title {title}"]
    for name, count in items:
        label = _safe_text(name, maximum=40).replace("\\", "").replace('"', "'")
        rows.append(f'    "{label}" : {count}')
    rows.append("```")
    return rows


def render_markdown(
    feedbacks: list[dict[str, Any]],
    window: ReportWindow,
    insight: dict[str, Any] | None = None,
    insight_degraded: bool = False,
    base_metrics: dict[str, Any] | None = None,
) -> str:
    """将反馈列表渲染为不含个人和执行上下文的 Markdown 日报。"""
    problems = [item for item in feedbacks if item.get("feedback_type") != "query_result"]
    severe = [item for item in problems if item.get("severity") in {"critical", "high"}]
    metrics = base_metrics or _build_base_metrics(feedbacks)
    type_counter = Counter(metrics["feedback_types"])
    severity_counter = Counter(metrics["problem_severities"])
    source_counter = Counter(metrics["problem_sources"])
    status_counter = Counter(metrics["problem_statuses"])

    lines = [
        f"# 反馈日报（{window.label}）",
        "",
        f"> 统计范围：{window.date_from} 至 {window.date_to}（Asia/Shanghai）  ",
        "> 隐私说明：报告不包含邮箱、用户 ID、原始 payload、context、附件或凭据。",
        "",
        "## 一、执行摘要",
        "",
        f"- 反馈总数：**{metrics['feedback_count']}**",
        f"- 问题反馈：**{metrics['problem_feedback_count']}**",
        f"- Critical / High：**{len(severe)}**",
        f"- 失败调用：**{metrics['failed_call_count']}**",
    ]
    if insight_degraded:
        lines.extend(["- AI 洞察生成失败，本期已降级为基础日报。"])
    lines.extend(
        [
        "",
        "## 二、分布概览",
        "",
        DISTRIBUTION_GRID_START,
        "",
        DISTRIBUTION_PANEL_START,
        "",
        "### 反馈类型",
        "",
        *_mermaid_pie(
            "反馈类型分布",
            type_counter,
            ("bug", "data_issue", "ux", "docs", "feature", "other", "query_result"),
        ),
        "",
        "<details>",
        "<summary>查看反馈类型数据表</summary>",
        "",
        "| 类型 | 数量 |",
        "|---|---:|",
        *_count_rows(type_counter, ("bug", "data_issue", "ux", "docs", "feature", "other", "query_result")),
        "",
        "</details>",
        "",
        DISTRIBUTION_PANEL_END,
        "",
        DISTRIBUTION_PANEL_START,
        "",
        "### 问题严重度",
        "",
        *_mermaid_pie(
            "问题严重度分布",
            severity_counter,
            ("critical", "high", "medium", "low"),
        ),
        "",
        "<details>",
        "<summary>查看问题严重度数据表</summary>",
        "",
        "| 严重度 | 数量 |",
        "|---|---:|",
        *_count_rows(severity_counter, ("critical", "high", "medium", "low")),
        "",
        "</details>",
        "",
        DISTRIBUTION_PANEL_END,
        "",
        DISTRIBUTION_GRID_END,
        "",
        "## 三、问题分布",
        "",
        PROBLEM_DISTRIBUTION_GRID_START,
        "",
        PROBLEM_DISTRIBUTION_PANEL_START,
        "",
        "### 来源",
        "",
        "| 来源 | 数量 |",
        "|---|---:|",
        *_count_rows(source_counter, ("cli", "mcp", "skill", "api")),
        "",
        PROBLEM_DISTRIBUTION_PANEL_END,
        "",
        PROBLEM_DISTRIBUTION_PANEL_START,
        "",
        "### 状态",
        "",
        "| 状态 | 数量 |",
        "|---|---:|",
        *_count_rows(status_counter, ("new", "triaged", "processing", "resolved", "rejected")),
        "",
        PROBLEM_DISTRIBUTION_PANEL_END,
        "",
        PROBLEM_DISTRIBUTION_GRID_END,
        "",
        ]
    )
    if insight is not None:
        lines.extend(
            [
                "",
                "## 四、模块问题洞察",
                "",
                "| 模块 | 主要问题 | 本周期 | 上一周期 | 变化 | 优先级 | 建议工作 |",
                "|---|---|---:|---:|---:|---|---|",
            ]
        )
        insight_problems = insight.get("problems")
        if isinstance(insight_problems, list) and insight_problems:
            for problem in insight_problems:
                change = problem.get("change_percent")
                change_text = "新增" if change is None else f"{change}%"
                priority_text = str(problem.get("priority") or "-")
                if problem.get("needs_review"):
                    priority_text = f"{priority_text}（待复核）"
                lines.append(
                    "| {module} | {summary} | {current} | {previous} | {change} | {priority} | {work} |".format(
                        module=_safe_text(problem.get("module"), maximum=80),
                        summary=_safe_text(problem.get("problem_summary"), maximum=120),
                        current=int(problem.get("current_count") or 0),
                        previous=int(problem.get("previous_count") or 0),
                        change=_safe_text(change_text, maximum=30),
                        priority=_safe_text(priority_text, maximum=30),
                        work=_safe_text(problem.get("recommended_work"), maximum=200),
                    )
                )
        else:
            lines.append("| - | 本周期无问题洞察 | 0 | 0 | - | - | - |")

    critical_section = "五" if insight is not None else "四"
    all_section = "六" if insight is not None else "五"
    lines.extend(
        [
        "",
        f"## {critical_section}、Critical / High 问题",
        "",
        "| 严重度 | 标题 | 来源 | 状态 | 失败调用 | 反馈 UUID | 创建时间 |",
        "|---|---|---|---|---:|---|---|",
        ]
    )
    if severe:
        for item in severe:
            lines.append(
                "| {severity} | {title} | {source} | {status} | {failed} | `{uuid}` | {created} |".format(
                    severity=_safe_text(item.get("severity")),
                    title=_safe_text(item.get("title")),
                    source=_safe_text(item.get("source")),
                    status=_safe_text(item.get("status")),
                    failed=int(item.get("failed_call_count") or 0),
                    uuid=_safe_text(item.get("feedback_uuid")),
                    created=_format_created_at(item.get("created_at")),
                )
            )
    else:
        lines.append("| - | 本期无 Critical / High 问题 | - | - | 0 | - | - |")

    lines.extend(
        [
            "",
            f"## {all_section}、全部问题反馈",
            "",
            "| 严重度 | 类型 | 标题 | 来源 | 状态 | 失败调用 | 反馈 UUID | 创建时间 |",
            "|---|---|---|---|---|---:|---|---|",
        ]
    )
    if problems:
        for item in problems:
            lines.append(
                "| {severity} | {kind} | {title} | {source} | {status} | {failed} | `{uuid}` | {created} |".format(
                    severity=_safe_text(item.get("severity")),
                    kind=_safe_text(item.get("feedback_type")),
                    title=_safe_text(item.get("title")),
                    source=_safe_text(item.get("source")),
                    status=_safe_text(item.get("status")),
                    failed=int(item.get("failed_call_count") or 0),
                    uuid=_safe_text(item.get("feedback_uuid")),
                    created=_format_created_at(item.get("created_at")),
                )
            )
    else:
        lines.append("| - | - | 本期无问题反馈 | - | - | 0 | - | - |")
    return "\n".join(lines) + "\n"


def render_wecom_summary(
    feedbacks: list[dict[str, Any]],
    window: ReportWindow,
    insight: dict[str, Any] | None = None,
    insight_degraded: bool = False,
) -> str:
    """生成适合企业微信群机器人的精简 Markdown V2 摘要。"""
    problems = [item for item in feedbacks if item.get("feedback_type") != "query_result"]
    severe = [item for item in problems if item.get("severity") in {"critical", "high"}]
    failed_calls = sum(int(item.get("failed_call_count") or 0) for item in feedbacks)
    lines = [
        f"### 反馈日报（{window.label}）",
        f"> 反馈总数：**{len(feedbacks)}**",
        f"> 问题反馈：**{len(problems)}**",
        f"> Critical / High：**{len(severe)}**",
        f"> 失败调用：**{failed_calls}**",
    ]
    insight_problems = insight.get("problems") if isinstance(insight, dict) else None
    urgent_insights = (
        [
            item
            for item in insight_problems
            if isinstance(item, dict) and item.get("priority") in {"P0", "P1"}
        ]
        if isinstance(insight_problems, list)
        else []
    )
    urgent_insights = [item for item in urgent_insights if not item.get("needs_review")]
    if insight_degraded:
        lines.extend(["", "AI 洞察生成失败，本期已降级为基础日报。"])
    if urgent_insights:
        lines.extend(["", "**P0 / P1 模块提醒**"])
        for item in urgent_insights[:3]:
            change = item.get("change_percent")
            if change is None:
                change_text = "上一周期未出现"
            else:
                prefix = "+" if float(change) > 0 else ""
                change_text = f"较上一周期 {prefix}{change}%"
            lines.append(
                "- [{priority}] {module}：{summary}（{count} 次，{change}）".format(
                    priority=_safe_text(item.get("priority"), maximum=20),
                    module=_safe_text(item.get("module"), maximum=40),
                    summary=_safe_text(item.get("problem_summary"), maximum=80),
                    count=int(item.get("current_count") or 0),
                    change=_safe_text(change_text, maximum=40),
                )
            )
            lines.append(
                f"  建议：{_safe_text(item.get('recommended_work'), maximum=120)}"
            )
    if severe:
        lines.extend(["", "**重点问题**"])
        grouped = Counter(
            (str(item.get("severity") or "unknown"), str(item.get("title") or "-"))
            for item in severe
        )
        displayed = list(grouped.items())[:5]
        for (severity, title), count in displayed:
            count_text = f"（{count} 条）" if count > 1 else ""
            lines.append(
                f"- [{_safe_text(severity, maximum=20)}] "
                f"{_safe_text(title, maximum=80)}{count_text}"
            )
        remaining = list(grouped.items())[5:]
        if remaining:
            remaining_count = sum(count for _, count in remaining)
            lines.append(
                f"- 另有 {len(remaining)} 类 Critical / High 问题"
                f"（共 {remaining_count} 条反馈），请查看本地完整报告"
            )
    else:
        lines.extend(["", "本期无 Critical / High 问题。"])
    lines.extend(["", f"[详细文档查看]({FEEDBACK_DETAIL_URL})"])
    return _truncate_utf8("\n".join(lines), WECOM_CONTENT_BYTES)


def _truncate_utf8(text: str, maximum_bytes: int) -> str:
    """按 UTF-8 字节安全截断企业微信消息。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return text
    return encoded[: maximum_bytes - 3].decode("utf-8", errors="ignore") + "..."


def _notify_error_message(stdout: str) -> str:
    """从 opscli notify 的结构化输出提取安全错误消息。"""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return "opscli notify 执行失败"
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return str(message) if message else "opscli notify 执行失败"


def send_wecom_summary(content: str) -> None:
    """通过正式 opscli notify 命令发送企业微信 Markdown 摘要。

    Args:
        content: 已脱敏并限制长度的 Markdown 摘要。

    Raises:
        DailyReportError: 命令不存在、超时或通知命令返回失败。
    """
    # Webhook 仍由 opscli notify 从 Skill 本地凭据文件读取，不进入命令参数或输出。
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        encoding="utf-8",
        delete=False,
    ) as content_file:
        content_file.write(content)
        content_path = Path(content_file.name)
    command = [
        "opscli",
        "notify",
        "wecom-markdown",
        "--credentials-file",
        str(CREDENTIALS_PATH),
        "--content-file",
        str(content_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=NOTIFY_COMMAND_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DailyReportError("未找到 opscli 命令，请先安装当前项目版本") from exc
    except subprocess.TimeoutExpired as exc:
        raise DailyReportError("opscli notify 执行超时") from exc
    finally:
        try:
            content_path.unlink(missing_ok=True)
        except OSError:
            pass
    if result.returncode != 0:
        raise DailyReportError(_notify_error_message(result.stdout))


def _write_text_atomically(content: str, resolved_path: Path) -> None:
    """在目标目录写临时文件后原子替换，避免截断上一成功产物。"""
    temporary_path = None
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved_path.parent,
            prefix=f".{resolved_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(resolved_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_markdown(markdown: str, output_path: Path) -> Path:
    """将 Markdown 日报限制写入项目反馈导出目录。"""
    resolved_path = resolve_output_path(output_path)
    try:
        _write_text_atomically(markdown, resolved_path)
    except OSError as exc:
        raise DailyReportError(f"无法写入反馈 Markdown 日报: {resolved_path}") from exc
    return resolved_path


def _run_context(
    window: ReportWindow,
    generated_at: datetime,
    *,
    insight_requested: bool,
) -> RunContext:
    """生成同周期稳定逻辑键和单次尝试标识。"""
    period = window.date_from[:10]
    profile = "insight" if insight_requested else "base"
    period_hash = hashlib.sha256(
        f"{window.date_from}\0{window.date_to}".encode("utf-8")
    ).hexdigest()[:12]
    period_key = f"daily-{period}-{period_hash}-schema-{RUN_ARTIFACT_SCHEMA_VERSION}"
    run_key = f"daily-{period}-{profile}-{period_hash}-schema-{RUN_ARTIFACT_SCHEMA_VERSION}"
    attempt = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"{run_key}-{attempt}"
    return RunContext(
        run_id,
        run_key,
        period_key,
        generated_at,
        window,
        Path("runs") / run_id,
    )


def _counter_dict(values: list[str]) -> dict[str, int]:
    """把计数器转换为键稳定排序的普通字典。"""
    return dict(sorted(Counter(values).items()))


def _source_snapshot_hash(feedbacks: list[dict[str, Any]]) -> str:
    """哈希报告和基础指标实际使用的反馈列表字段。"""
    keys = (
        "feedback_uuid",
        "feedback_type",
        "severity",
        "source",
        "status",
        "title",
        "failed_call_count",
        "created_at",
    )
    rows = [
        {key: item.get(key) for key in keys}
        for item in sorted(feedbacks, key=lambda item: str(item.get("feedback_uuid") or ""))
    ]
    serialized = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _payload_hash(payload: dict[str, Any]) -> str:
    """哈希已脱敏的模型输入，不持久化输入正文。"""
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _insight_runtime_metadata(config_path: Path | None) -> dict[str, Any]:
    """读取不含密钥的模型调用描述，失败运行也可按配置统计。"""
    model = None
    batch_size = DEFAULT_INSIGHT_BATCH_SIZE
    effective_path = config_path or DEFAULT_INSIGHT_CONFIG
    try:
        payload = json.loads(effective_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            model = str(payload.get("model") or "").strip() or None
            configured_batch_size = int(payload.get("batch_size", batch_size))
            if 1 <= configured_batch_size <= 100:
                batch_size = configured_batch_size
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {
        "provider": "openai_compatible",
        "model": model,
        "batch_size": batch_size,
        "prompt_version": INSIGHT_PROMPT_VERSION,
        "prompt_hash": INSIGHT_PROMPT_HASH,
    }


def _build_base_metrics(feedbacks: list[dict[str, Any]]) -> dict[str, Any]:
    """生成不依赖模型、可供跨周期汇总的基础指标。"""
    problems = [item for item in feedbacks if item.get("feedback_type") != "query_result"]
    return {
        "feedback_count": len(feedbacks),
        "problem_feedback_count": len(problems),
        "failed_call_count": sum(int(item.get("failed_call_count") or 0) for item in feedbacks),
        "feedback_types": _counter_dict(
            [str(item.get("feedback_type") or "unknown") for item in feedbacks]
        ),
        "problem_severities": _counter_dict(
            [str(item.get("severity") or "unknown") for item in problems]
        ),
        "problem_sources": _counter_dict(
            [str(item.get("source") or "unknown") for item in problems]
        ),
        "problem_statuses": _counter_dict(
            [str(item.get("status") or "unknown") for item in problems]
        ),
    }


def _insight_failure(exc: Exception) -> dict[str, str]:
    """将洞察异常转换为可持久化且已脱敏的稳定错误。"""
    if isinstance(exc, FeedbackQueryError):
        payload = exc.payload if isinstance(exc.payload, dict) else {}
        code = str(payload.get("code") or "INSIGHT_QUERY_ERROR")
        message = str(payload.get("msg") or exc)
    elif isinstance(exc, DailyReportError):
        code = "INSIGHT_EXECUTION_ERROR"
        message = str(exc)
    elif isinstance(exc, httpx.TimeoutException):
        code = "INSIGHT_NETWORK_TIMEOUT"
        message = "反馈洞察网络请求超时"
    else:
        code = "INSIGHT_NETWORK_ERROR"
        message = "反馈洞察网络请求失败"
    return {"code": code, "message": _safe_insight_text(message, 500)}


def _execution_failure(exc: Exception) -> dict[str, str]:
    """将日报主链路异常转换为安全错误。"""
    if isinstance(exc, FeedbackQueryError):
        payload = exc.payload if isinstance(exc.payload, dict) else {}
        code = str(payload.get("code") or "FEEDBACK_QUERY_ERROR")
        message = str(payload.get("msg") or exc)
    elif isinstance(exc, DailyReportError):
        code = "DAILY_REPORT_ERROR"
        message = str(exc)
    else:
        code = "NETWORK_ERROR"
        message = "反馈查询接口网络请求失败"
    return {"code": code, "message": _safe_insight_text(message, 500)}


def _write_json_artifact(payload: dict[str, Any], output_path: Path) -> Path:
    """把结构化运行产物限制写入反馈导出目录。"""
    resolved_path = resolve_output_path(output_path)
    try:
        _write_text_atomically(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            resolved_path,
        )
    except OSError as exc:
        raise DailyReportError(f"无法写入反馈日报运行产物: {resolved_path}") from exc
    return resolved_path


def _period_payload(window: ReportWindow) -> dict[str, str]:
    """生成运行产物共用的周期字段。"""
    return {"label": window.label, "date_from": window.date_from, "date_to": window.date_to}


def _start_run_manifest(
    context: RunContext,
    *,
    insight_requested: bool,
    insight_runtime: dict[str, Any],
    notification_requested: bool,
) -> Path:
    """在远端查询前创建运行清单，确保早期失败也可追踪。"""
    return _write_json_artifact(
        {
            "schema_version": RUN_ARTIFACT_SCHEMA_VERSION,
            "run_id": context.run_id,
            "run_key": context.run_key,
            "period_key": context.period_key,
            "report_type": "daily",
            "generated_at": context.generated_at.isoformat().replace("+00:00", "Z"),
            "status": "running",
            "execution_status": "running",
            "stage": "initialized",
            "period": _period_payload(context.window),
            "insight": {
                "requested": insight_requested,
                "status": "pending" if insight_requested else "disabled",
                "error": None,
                "runtime": insight_runtime if insight_requested else None,
            },
            "notification": {
                "requested": notification_requested,
                "status": "pending" if notification_requested else "disabled",
            },
        },
        context.directory / "manifest.json",
    )


def _fail_run_manifest(
    context: RunContext,
    *,
    stage: str,
    exc: Exception,
    elapsed_ms: float,
) -> None:
    """将已创建的运行清单更新为失败终态。"""
    manifest_path = resolve_output_path(context.directory / "manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {
            "schema_version": RUN_ARTIFACT_SCHEMA_VERSION,
            "run_id": context.run_id,
            "run_key": context.run_key,
            "period_key": context.period_key,
            "report_type": "daily",
            "period": _period_payload(context.window),
        }
    failure = {"stage": stage, **_execution_failure(exc)}
    manifest.update(
        {
            "status": "failed",
            "execution_status": "failed",
            "stage": stage,
            "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "duration_ms": round(elapsed_ms, 1),
            "failure": failure,
        }
    )
    if stage == "publish_report":
        manifest["publication"] = {
            "status": "failed",
            "error": {key: value for key, value in failure.items() if key != "stage"},
        }
    elif stage == "finalize_manifest":
        manifest["publication"] = {"status": "success"}
    _write_json_artifact(manifest, context.directory / "manifest.json")


def _record_run_failure(
    context: RunContext | None,
    *,
    stage: str,
    exc: Exception,
    elapsed_ms: float,
) -> None:
    """尽力记录失败，产物目录本身不可写时仍保留原始命令错误。"""
    if context is None:
        return
    try:
        _fail_run_manifest(context, stage=stage, exc=exc, elapsed_ms=elapsed_ms)
    except (FeedbackQueryError, DailyReportError, OSError):
        pass


def _write_run_artifacts(
    *,
    context: RunContext,
    outcome: RunOutcome,
) -> tuple[Path, Path]:
    """写入日报 manifest 和问题簇快照，作为周报、月报的事实来源。"""
    insight_status = (
        "success"
        if outcome.insight is not None
        else "degraded"
        if outcome.insight_requested
        else "disabled"
    )
    analysis_status = "degraded" if insight_status == "degraded" else "success"
    clusters_path = _write_json_artifact(
        {
            "schema_version": RUN_ARTIFACT_SCHEMA_VERSION,
            "run_id": context.run_id,
            "run_key": context.run_key,
            "period_key": context.period_key,
            "report_type": "daily",
            "period": _period_payload(context.window),
            "comparison_period": (
                _period_payload(outcome.comparison_window)
                if outcome.comparison_window
                else None
            ),
            "insight_status": insight_status,
            "source_snapshots": outcome.source_snapshots,
            "base_metrics": outcome.base_metrics,
            "problems": outcome.insight.get("problems", []) if outcome.insight else [],
            "modules": outcome.insight.get("modules", []) if outcome.insight else [],
            "model": (
                outcome.insight.get("model")
                if outcome.insight
                else outcome.insight_runtime
                if outcome.insight_requested
                else None
            ),
        },
        context.directory / "clusters.json",
    )
    export_root = resolve_output_path(Path("artifact-root-placeholder")).parent
    try:
        report_hash = hashlib.sha256(outcome.archived_report_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DailyReportError("无法读取反馈日报归档文件") from exc
    manifest_path = _write_json_artifact(
        {
            "schema_version": RUN_ARTIFACT_SCHEMA_VERSION,
            "run_id": context.run_id,
            "run_key": context.run_key,
            "period_key": context.period_key,
            "report_type": "daily",
            "generated_at": context.generated_at.isoformat().replace("+00:00", "Z"),
            "status": "publishing",
            "analysis_status": analysis_status,
            "execution_status": "running",
            "stage": "publish_report",
            "timings_ms": {
                key: round(value, 1) for key, value in outcome.timings_ms.items()
            },
            "period": _period_payload(context.window),
            "feedback_count": outcome.base_metrics["feedback_count"],
            "source_snapshots": outcome.source_snapshots,
            "insight": {
                "requested": outcome.insight_requested,
                "status": insight_status,
                "error": outcome.insight_error,
                "runtime": outcome.insight_runtime if outcome.insight_requested else None,
            },
            "notification": outcome.notification,
            "publication": {"status": "pending"},
            "artifacts": {
                "report": outcome.archived_report_path.relative_to(export_root).as_posix(),
                "report_sha256": report_hash,
                "published_report": outcome.published_report_path.relative_to(
                    export_root
                ).as_posix(),
                "clusters": clusters_path.relative_to(export_root).as_posix(),
            },
        },
        context.directory / "manifest.json",
    )
    return manifest_path, clusters_path


def _finalize_run_manifest(
    manifest_path: Path,
    *,
    notification: dict[str, Any],
    elapsed_ms: float,
) -> None:
    """在根目录日报原子发布成功后完成运行清单。"""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DailyReportError("无法读取待完成的反馈日报运行清单") from exc
    manifest.update(
        {
            "status": manifest["analysis_status"],
            "execution_status": (
                "failed" if notification["status"] == "failed" else "success"
            ),
            "stage": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "duration_ms": round(elapsed_ms, 1),
            "publication": {"status": "success"},
        }
    )
    _write_json_artifact(manifest, manifest_path)


def _print_json(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    """使用 GBK 安全的 ASCII JSON 输出执行结果。"""
    print(json.dumps(payload, ensure_ascii=True), file=stream)


def main(argv: list[str] | None = None) -> int:
    """查询反馈、生成 Markdown 日报并按需推送企业微信。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    context = None
    stage = "resolve_window"
    started_at = perf_counter()
    timings_ms: dict[str, float] = {}
    try:
        generated_at = datetime.now(timezone.utc)
        window = resolve_report_window(args.date_from, args.date_to)
        insight_runtime = (
            _insight_runtime_metadata(args.insight_config) if args.insight else {}
        )
        context = _run_context(
            window,
            generated_at,
            insight_requested=args.insight,
        )
        _start_run_manifest(
            context,
            insight_requested=args.insight,
            insight_runtime=insight_runtime,
            notification_requested=args.send,
        )
        stage = "load_credentials"
        api_key = load_api_key()
        client = FeedbackQueryClient(api_key, args.base_url, args.timeout)
        stage = "query_current"
        step_started = perf_counter()
        feedbacks = fetch_feedbacks(client, window, per_page=args.per_page)
        timings_ms["query_current"] = (perf_counter() - step_started) * 1000
        base_metrics = _build_base_metrics(feedbacks)
        source_snapshots: dict[str, str | None] = {
            "current": _source_snapshot_hash(feedbacks),
            "comparison": None,
            "model_input": None,
        }
        insight = None
        insight_error = None
        comparison_window = None
        if args.insight:
            stage = "insight"
            insight_started = perf_counter()
            try:
                comparison_window = resolve_comparison_window(window)
                step_started = perf_counter()
                try:
                    comparison_feedbacks = fetch_feedbacks(
                        client, comparison_window, per_page=args.per_page
                    )
                finally:
                    timings_ms["query_comparison"] = (
                        perf_counter() - step_started
                    ) * 1000
                source_snapshots["comparison"] = _source_snapshot_hash(
                    comparison_feedbacks
                )
                step_started = perf_counter()
                try:
                    current_details = fetch_feedback_details(client, feedbacks)
                finally:
                    timings_ms["detail_current"] = (perf_counter() - step_started) * 1000
                step_started = perf_counter()
                try:
                    comparison_details = fetch_feedback_details(
                        client, comparison_feedbacks
                    )
                finally:
                    timings_ms["detail_comparison"] = (
                        perf_counter() - step_started
                    ) * 1000
                insight_payload = {
                    "period": _period_payload(window),
                    "comparison_period": _period_payload(comparison_window),
                    "current_feedbacks": build_insight_feedbacks(
                        feedbacks, current_details
                    ),
                    "comparison_feedbacks": build_insight_feedbacks(
                        comparison_feedbacks, comparison_details
                    ),
                }
                source_snapshots["model_input"] = _payload_hash(insight_payload)
                model_feedback_count = len(insight_payload["current_feedbacks"]) + len(
                    insight_payload["comparison_feedbacks"]
                )
                insight_runtime["batch_count"] = max(
                    1,
                    math.ceil(model_feedback_count / insight_runtime["batch_size"]),
                )
                step_started = perf_counter()
                try:
                    insight = run_feedback_insight(
                        insight_payload,
                        args.insight_config,
                    )
                finally:
                    timings_ms["model"] = (perf_counter() - step_started) * 1000
                if isinstance(insight.get("model"), dict):
                    insight_runtime.update(insight["model"])
            except (FeedbackQueryError, DailyReportError, httpx.HTTPError) as exc:
                # AI 洞察是可选增强；失败时保留基础日报和原有高严重度提醒。
                insight_error = _insight_failure(exc)
            timings_ms["insight_total"] = (perf_counter() - insight_started) * 1000
        insight_degraded = insight_error is not None
        stage = "render_report"
        step_started = perf_counter()
        markdown = render_markdown(
            feedbacks,
            window,
            insight,
            insight_degraded,
            base_metrics,
        )
        timings_ms["render_report"] = (perf_counter() - step_started) * 1000
        default_name = f"反馈日报-{window.label.replace(' 至 ', '_')}.md"
        output_path = resolve_output_path(args.output or Path(default_name))
        stage = "archive_report"
        archived_report_path = write_markdown(markdown, context.directory / "report.md")

        sent = False
        notification: dict[str, Any] = {
            "requested": args.send,
            "status": "pending" if args.send else "disabled",
        }
        notification_error = None
        if args.send:
            stage = "notification"
            step_started = perf_counter()
            try:
                send_wecom_summary(
                    render_wecom_summary(feedbacks, window, insight, insight_degraded)
                )
                sent = True
                notification["status"] = "success"
            except DailyReportError as exc:
                notification["status"] = "failed"
                notification["error"] = {
                    "code": "NOTIFICATION_ERROR",
                    "message": _safe_insight_text(str(exc), 500),
                }
                notification_error = exc
            timings_ms["notification"] = (perf_counter() - step_started) * 1000
        stage = "write_artifacts"
        outcome = RunOutcome(
            comparison_window=comparison_window,
            base_metrics=base_metrics,
            source_snapshots=source_snapshots,
            insight=insight,
            insight_requested=args.insight,
            insight_error=insight_error,
            insight_runtime=insight_runtime,
            published_report_path=output_path,
            archived_report_path=archived_report_path,
            notification=notification,
            timings_ms=timings_ms,
        )
        manifest_path, clusters_path = _write_run_artifacts(
            context=context,
            outcome=outcome,
        )
        stage = "publish_report"
        output_path = write_markdown(markdown, output_path)
        stage = "finalize_manifest"
        _finalize_run_manifest(
            manifest_path,
            notification=notification,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )
        if notification_error is not None:
            _print_json(
                {"code": "DAILY_REPORT_ERROR", "msg": str(notification_error)},
                stream=sys.stderr,
            )
            return 1
    except FeedbackQueryError as exc:
        _record_run_failure(
            context,
            stage=stage,
            exc=exc,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )
        _print_json(exc.payload, stream=sys.stderr)
        return 1
    except DailyReportError as exc:
        _record_run_failure(
            context,
            stage=stage,
            exc=exc,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )
        _print_json({"code": "DAILY_REPORT_ERROR", "msg": str(exc)}, stream=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        _record_run_failure(
            context,
            stage=stage,
            exc=exc,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )
        _print_json({"code": "NETWORK_ERROR", "msg": "反馈查询接口网络请求失败"}, stream=sys.stderr)
        return 1

    _print_json(
        {
            "success": True,
            "run_id": context.run_id,
            "output": str(output_path),
            "archived_report": str(archived_report_path),
            "manifest": str(manifest_path),
            "clusters": str(clusters_path),
            "feedback_count": len(feedbacks),
            "insight": insight is not None,
            "insight_degraded": insight_degraded,
            "sent": sent,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
