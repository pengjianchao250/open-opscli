"""生成内部反馈 Markdown 日报并可选推送企业微信群机器人。

脚本默认统计 Asia/Shanghai 时区的完整昨日，自动翻页读取反馈列表，
仅使用非敏感列表字段生成报告和群消息。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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
from opscli.feedback.services.insight import (
    DEFAULT_TAXONOMY_PATH,
    FeedbackTaxonomyStore,
    INSIGHT_PROMPT_HASH,
    INSIGHT_PROMPT_VERSION,
    InsightConfigError,
    aggregate_feedback_classifications,
    sanitize_feedback_text,
    validate_feedback_classifications,
)

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
# 取数与 Codex 交接产物独立演进，1.1 增加 taxonomy 缓存分类产物。
PREPARED_ARTIFACT_SCHEMA_VERSION = "1.1"
# 与生产反馈洞察批次保持 100 条一致，兼顾上下文成本和单次输出可靠性。
PREPARED_CHUNK_SIZE = 100
# Codex 分类契约内容或输出约束变化时递增，供准备产物失效与审计使用。
CODEX_INSIGHT_PROMPT_VERSION = "codex-v2"
# 契约放在不打包的内部 Skill 内，由 Codex 自动化和 Python 哈希共同引用。
CODEX_INSIGHT_CONTRACT_PATH = SCRIPT_DIR.parent / "reference" / "Codex反馈洞察分类契约.md"
# 与 `opscli feedback insight` 使用同一默认配置路径，确保批次数预算一致。
DEFAULT_INSIGHT_CONFIG = CONFIG_DIR / "feedback_insight.json"
# 企业微信 markdown_v2.content 官方上限为 4096 字节。
WECOM_CONTENT_BYTES = 4096
FEEDBACK_DETAIL_URL = "https://ops.xenkee.com/dashboard/share/3e2W4spQ"
# 列表标题可能由用户或 Agent 生成，统一清理常见个人信息和凭据形态。
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
URL_PATTERN = re.compile(r"https?://[^\s|]+", re.IGNORECASE)
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


class PreparedAnalysis(NamedTuple):
    """已校验分类及其确定性聚合结果。"""

    prepared: dict[str, Any]
    manifest_path: Path
    analysis_input: dict[str, Any]
    report_input: dict[str, Any]
    snapshots: dict[str, Any]
    classifications: list[dict[str, Any]]
    insight_runtime: dict[str, Any]
    insight: dict[str, Any]
    model_feedbacks: list[dict[str, Any]]
    window: ReportWindow
    comparison_window: ReportWindow
    feedbacks: list[dict[str, Any]]


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
    parser.add_argument(
        "--taxonomy-file",
        type=Path,
        help="持久 taxonomy 文件；默认 ~/.config/opscli/feedback_taxonomy.json",
    )
    pipeline = parser.add_mutually_exclusive_group()
    pipeline.add_argument(
        "--prepare-only",
        action="store_true",
        help="只准备昨日脱敏数据和 READY 标记，不调用模型或发布日报",
    )
    pipeline.add_argument(
        "--claim-ready",
        action="store_true",
        help="领取最新一份 ready 数据并切换为 analyzing，供 Codex 计划任务使用",
    )
    pipeline.add_argument(
        "--validate-chunk",
        type=Path,
        help="校验 Codex 写入的单个 chunk 输出并记录检查点",
    )
    pipeline.add_argument(
        "--prepare-narrative",
        type=Path,
        help="基于已校验分类生成只读管理叙事事实包",
    )
    pipeline.add_argument(
        "--validate-narrative",
        type=Path,
        help="校验 Codex 写入的管理叙事输出并记录检查点",
    )
    pipeline.add_argument(
        "--finalize-prepared",
        type=Path,
        help="从已准备目录离线聚合、生成并发布 AI 日报",
    )
    parser.add_argument(
        "--analysis-model",
        default="codex_app",
        help="Codex 最终化时记录的模型名称，不参与统计",
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
    return sanitize_feedback_text(value, maximum)


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
        detail_context = detail.get("context")
        observation = (
            detail_context.get("observation") if isinstance(detail_context, dict) else None
        )
        if isinstance(observation, dict) and observation.get("error_code"):
            row["error_code"] = _safe_insight_text(observation["error_code"], 200)
        result.append(row)
    return result


def run_feedback_insight(
    payload: dict[str, Any],
    config_path: Path | None = None,
    taxonomy_path: Path | None = None,
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
    if taxonomy_path is not None:
        command.extend(["--taxonomy-file", str(taxonomy_path)])
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
    text = sanitize_feedback_text(value or "-", maximum * 2)
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


def _safe_narrative_markdown(value: Any, maximum: int) -> str:
    """将已校验叙事转为单段、不可改变报告结构的 Markdown 文本。"""
    text = " ".join(str(value).split())
    return _safe_text(text, maximum=maximum).replace("#", "\\#")


def _render_management_markdown(
    feedbacks: list[dict[str, Any]],
    window: ReportWindow,
    insight: dict[str, Any],
    base_metrics: dict[str, Any],
    management: dict[str, Any],
) -> str:
    """按管理结论优先、明细折叠的结构渲染 Codex 日报。"""
    narrative = management["narrative"]
    facts = management["facts"]
    problems = [item for item in feedbacks if item.get("feedback_type") != "query_result"]
    severe = [item for item in problems if item.get("severity") in {"critical", "high"}]
    module_insights = {
        item["module"]: item["insight"] for item in narrative["module_insights"]
    }
    problem_by_ref = {
        item["problem_ref"]: item for item in facts["all_problems"]
    }
    comparison = facts["comparison"]
    lines = [
        f"# 反馈 AI 洞悉（{window.label}）",
        "",
        "> 生成方式：Codex App 基于脱敏分类和 Python 确定性统计生成管理叙事。",
        "",
        "## 一、范围与口径",
        "",
        f"- 时间范围：{window.date_from} 至 {window.date_to}（Asia/Shanghai）。",
        f"- 全部反馈：{base_metrics['feedback_count']} 条。",
        f"- 纳入洞悉的问题反馈：{base_metrics['problem_feedback_count']} 条。",
        "- 严重度：Critical {critical}、High {high}、Medium {medium}、Low {low}。".format(
            critical=base_metrics["problem_severities"].get("critical", 0),
            high=base_metrics["problem_severities"].get("high", 0),
            medium=base_metrics["problem_severities"].get("medium", 0),
            low=base_metrics["problem_severities"].get("low", 0),
        ),
        f"- 失败调用累计：{base_metrics['failed_call_count']} 次。",
        "- AI 不计算次数、环比、影响人数或优先级；所有数字来自确定性事实包。",
        "",
        "## 二、执行摘要",
        "",
    ]
    for paragraph in narrative["executive_summary"]:
        lines.extend([_safe_narrative_markdown(paragraph, 1000), ""])

    lines.extend(
        [
            "## 三、根因分布",
            "",
            "| 根因类别 | 次数 | 占比 | High/Critical | 影响用户 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in facts["root_causes"]:
        lines.append(
            "| {category} | {count} | {share}% | {severe} | {users} |".format(
                category=_safe_text(row["category"], maximum=100),
                count=row["current_count"],
                share=row["share_percent"],
                severe=row["severe_count"],
                users=row["affected_users"],
            )
        )

    lines.extend(
        [
            "",
            "## 四、重点模块",
            "",
            "| 模块 | 问题反馈 | 占比 | High/Critical | 最高优先级 | 洞悉 |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for row in facts["modules"]:
        lines.append(
            "| {module} | {count} | {share}% | {severe} | {priority} | {insight_text} |".format(
                module=_safe_text(row["module"], maximum=80),
                count=row["feedback_count"],
                share=row["share_percent"],
                severe=row["severe_count"],
                priority=_safe_text(row["highest_priority"], maximum=10),
                insight_text=_safe_narrative_markdown(
                    module_insights.get(row["module"], "-"), 200
                ),
            )
        )

    lines.extend(["", "## 五、重复问题证据", ""])
    for index, row in enumerate(facts["repeated_problems"], start=1):
        summary = str(row["problem_summary"]).rstrip("。！？.!?")
        lines.append(
            f"{index}. `{_safe_text(row['module'], maximum=80)}` "
            f"{_safe_text(summary, maximum=180)}："
            f"{row['current_count']} 条，{row['affected_users']} 个影响用户，"
            f"优先级 {row['priority']}。"
        )

    lines.extend(["", "## 六、P0/P1 风险", ""])
    if narrative["risk_themes"]:
        for index, theme in enumerate(narrative["risk_themes"], start=1):
            lines.extend(
                [
                    f"### {theme['priority']}-{index} {_safe_text(theme['title'], maximum=120)}",
                    "",
                    _safe_narrative_markdown(theme["summary"], 600),
                    "",
                ]
            )
            for problem_ref in theme["problem_refs"]:
                row = problem_by_ref[problem_ref]
                summary = str(row["problem_summary"]).rstrip("。！？.!?")
                lines.append(
                    f"- {_safe_text(summary, maximum=180)}：{row['current_count']} 条，"
                    f"{row['affected_users']} 个影响用户，{row['priority']}。"
                )
            lines.extend(
                ["", f"建议：{_safe_narrative_markdown(theme['recommendation'], 800)}", ""]
            )
    else:
        lines.extend(["本日没有确定性优先级为 P0/P1 的风险主题。", ""])

    lines.extend(["## 七、治理工作建议", ""])
    for action in narrative["governance_actions"]:
        lines.extend(
            [
                f"### {action['priority']} {_safe_text(action['title'], maximum=120)}",
                "",
                _safe_narrative_markdown(action["summary"], 600),
                "",
                f"建议：{_safe_narrative_markdown(action['recommendation'], 800)}",
                "",
            ]
        )

    change = comparison["change_percent"]
    change_text = "新增" if change is None else f"{change}%"
    lines.extend(
        [
            "## 八、日环比",
            "",
            "| 周期 | 问题反馈 | High/Critical | 影响用户 |",
            "|---|---:|---:|---:|",
            (
                f"| {comparison['current_label']} | {comparison['current_count']} | "
                f"{comparison['current_severe_count']} | "
                f"{comparison['current_affected_users']} |"
            ),
            (
                f"| {comparison['previous_label']} | {comparison['previous_count']} | "
                f"{comparison['previous_severe_count']} | "
                f"{comparison['previous_affected_users']} |"
            ),
            "",
            f"问题反馈日环比：{change_text}。绝对量变化仍需结合调用量判断故障率。",
            "",
            "## 九、局限与后续",
            "",
        ]
    )
    for item in narrative["limitations"]:
        lines.append(f"- {_safe_narrative_markdown(item, 500)}")

    lines.extend(
        [
            "",
            "## 附录：结构化明细",
            "",
            "<details>",
            f"<summary>查看全部问题簇（{len(insight.get('problems', []))} 个）</summary>",
            "",
            "| 模块 | 主要问题 | 本日 | 前一日 | 变化 | 优先级 | 建议工作 |",
            "|---|---|---:|---:|---:|---|---|",
        ]
    )
    for row in insight.get("problems", []):
        row_change = row.get("change_percent")
        row_change_text = "新增" if row_change is None else f"{row_change}%"
        lines.append(
            "| {module} | {summary} | {current} | {previous} | {change} | {priority} | {work} |".format(
                module=_safe_text(row.get("module"), maximum=80),
                summary=_safe_text(row.get("problem_summary"), maximum=160),
                current=int(row.get("current_count") or 0),
                previous=int(row.get("previous_count") or 0),
                change=row_change_text,
                priority=_safe_text(row.get("priority"), maximum=20),
                work=_safe_text(row.get("recommended_work"), maximum=220),
            )
        )
    lines.extend(["", "</details>", "", "<details>", f"<summary>查看 Critical / High 反馈（{len(severe)} 条）</summary>", "", "| 严重度 | 标题 | 来源 | 反馈 UUID | 创建时间 |", "|---|---|---|---|---|"])
    for item in severe:
        lines.append(
            "| {severity} | {title} | {source} | `{uuid}` | {created} |".format(
                severity=_safe_text(item.get("severity")),
                title=_safe_text(item.get("title")),
                source=_safe_text(item.get("source")),
                uuid=_safe_text(item.get("feedback_uuid")),
                created=_format_created_at(item.get("created_at")),
            )
        )
    lines.extend(["", "</details>", "", "<details>", f"<summary>查看全部问题反馈（{len(problems)} 条）</summary>", "", "| 严重度 | 类型 | 标题 | 来源 | 状态 | 反馈 UUID |", "|---|---|---|---|---|---|"])
    for item in problems:
        lines.append(
            "| {severity} | {kind} | {title} | {source} | {status} | `{uuid}` |".format(
                severity=_safe_text(item.get("severity")),
                kind=_safe_text(item.get("feedback_type")),
                title=_safe_text(item.get("title")),
                source=_safe_text(item.get("source")),
                status=_safe_text(item.get("status")),
                uuid=_safe_text(item.get("feedback_uuid")),
            )
        )
    lines.extend(["", "</details>"])
    return "\n".join(lines) + "\n"


def render_markdown(
    feedbacks: list[dict[str, Any]],
    window: ReportWindow,
    insight: dict[str, Any] | None = None,
    insight_degraded: bool = False,
    base_metrics: dict[str, Any] | None = None,
    management: dict[str, Any] | None = None,
) -> str:
    """将反馈列表渲染为不含个人和执行上下文的 Markdown 日报。"""
    problems = [item for item in feedbacks if item.get("feedback_type") != "query_result"]
    severe = [item for item in problems if item.get("severity") in {"critical", "high"}]
    metrics = base_metrics or _build_base_metrics(feedbacks)
    if insight is not None and management is not None:
        return _render_management_markdown(
            feedbacks, window, insight, metrics, management
        )
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
            "management_facts": (
                outcome.insight.get("management_facts") if outcome.insight else None
            ),
            "report_narrative": (
                outcome.insight.get("report_narrative") if outcome.insight else None
            ),
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


def _read_json_artifact(path: Path, label: str) -> dict[str, Any]:
    """读取反馈输出目录中的 JSON 对象。"""
    resolved_path = resolve_output_path(path)
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DailyReportError(f"{label} 不存在、不可读取或不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise DailyReportError(f"{label} 必须是 JSON 对象")
    return payload


def _prepared_directory(window: ReportWindow) -> Path:
    """返回单日准备产物目录。"""
    if " 至 " in window.label:
        raise DailyReportError("--prepare-only 仅支持单日时间窗口")
    return resolve_output_path(Path("prepared") / window.label / "placeholder").parent


def _safe_report_feedbacks(feedbacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保存渲染日报所需的脱敏列表字段，不保留用户身份。"""
    keys = (
        "feedback_uuid",
        "feedback_type",
        "severity",
        "source",
        "status",
        "failed_call_count",
        "created_at",
    )
    rows: list[dict[str, Any]] = []
    for item in feedbacks:
        row = {key: item.get(key) for key in keys if item.get(key) is not None}
        row["title"] = _safe_text(item.get("title"), maximum=500)
        rows.append(row)
    return rows


def _prepared_manifest_reusable(
    prepared_dir: Path,
    taxonomy_store_id: str | None = None,
) -> dict[str, Any] | None:
    """检查已有 ready/analyzing/completed 准备产物能否直接复用。"""
    manifest_path = prepared_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = _read_json_artifact(manifest_path, "准备清单")
        if manifest.get("schema_version") != PREPARED_ARTIFACT_SCHEMA_VERSION:
            return None
        if (
            taxonomy_store_id is not None
            and manifest.get("taxonomy", {}).get("store_id") != taxonomy_store_id
        ):
            return None
        if manifest.get("state") not in {
            "ready",
            "analyzing",
            "narrating",
            "completed",
        }:
            return None
        period_label = str(manifest.get("period", {}).get("label") or "")
        ready_path = prepared_dir / str(
            manifest.get("artifacts", {}).get("ready_marker") or "READY"
        )
        if ready_path.read_text(encoding="utf-8") != f"{period_label} 数据已完成\n":
            return None
        contract = manifest.get("contract", {})
        if (
            contract.get("prompt_version") != CODEX_INSIGHT_PROMPT_VERSION
            or contract.get("prompt_hash") != _codex_contract_hash()
        ):
            return None
        for key in ("analysis_input", "report_input", "cached_classifications"):
            artifact = manifest.get("artifacts", {}).get(key)
            expected_hash = manifest.get("source_snapshots", {}).get(key)
            if not isinstance(artifact, str) or not isinstance(expected_hash, str):
                return None
            payload = _read_json_artifact(prepared_dir / artifact, key)
            if _payload_hash(payload) != expected_hash:
                return None
        chunks = manifest.get("chunks")
        if not isinstance(chunks, list):
            return None
        repaired_checkpoint = False
        for chunk in chunks:
            if not isinstance(chunk, dict):
                return None
            chunk_input = _read_json_artifact(
                prepared_dir / str(chunk.get("input") or ""), "chunk 输入"
            )
            if _payload_hash(chunk_input) != chunk.get("input_sha256"):
                return None
            if chunk.get("status") == "validated":
                try:
                    _, output_hash = _validated_chunk_classifications(
                        prepared_dir, manifest, chunk
                    )
                except DailyReportError:
                    output_hash = None
                if output_hash != chunk.get("output_sha256"):
                    if manifest.get("state") == "completed":
                        return None
                    _write_json_artifact(
                        {
                            "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
                            "status": "invalid",
                            "error": {"code": "CHUNK_CHECKPOINT_INVALID"},
                        },
                        prepared_dir / str(chunk.get("output") or ""),
                    )
                    chunk["status"] = "failed"
                    chunk["error"] = {
                        "code": "CHUNK_CHECKPOINT_INVALID",
                        "message": "已校验 chunk 输出缺失、损坏或哈希不匹配",
                    }
                    chunk.pop("output_sha256", None)
                    chunk.pop("classification_count", None)
                    chunk.pop("validated_at", None)
                    repaired_checkpoint = True
        if repaired_checkpoint:
            _write_json_artifact(manifest, manifest_path)
        return manifest
    except (DailyReportError, OSError):
        return None


def _codex_contract_hash() -> str:
    """返回 Codex 洞察契约哈希，确保调度结果可追溯。"""
    try:
        content = CODEX_INSIGHT_CONTRACT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise DailyReportError("Codex 洞察契约文件不存在或不可读取") from exc
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _taxonomy_store(path: Path | None) -> FeedbackTaxonomyStore:
    """创建日报使用的 taxonomy 存储，并统一默认路径。"""
    return FeedbackTaxonomyStore(path or DEFAULT_TAXONOMY_PATH)


def _taxonomy_store_id(path: Path | None) -> str:
    """返回不暴露本地路径的稳定 taxonomy 存储身份。"""
    normalized = os.path.normcase(str((path or DEFAULT_TAXONOMY_PATH).expanduser().resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _partition_taxonomy_matches(
    feedbacks: list[dict[str, Any]],
    taxonomy_path: Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """按持久 taxonomy 将反馈拆分为缓存分类和待 Codex 分类。"""
    store = _taxonomy_store(taxonomy_path)
    try:
        state = store.load()
    except InsightConfigError as exc:
        raise DailyReportError(str(exc)) from exc
    cached: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for feedback in feedbacks:
        classification = store.match(state, feedback)
        if classification is None:
            pending.append(feedback)
        else:
            cached.append(classification)
    return state, cached, pending


def prepare_feedback_data(args: argparse.Namespace) -> dict[str, Any]:
    """查询、脱敏并持久化昨日数据，不调用模型或发送通知。

    Args:
        args: 日报命令参数，使用日期、分页、服务地址和查询超时字段。

    Returns:
        包含周期键、准备目录、记录数、分块数及是否复用的安全结果。

    Raises:
        DailyReportError: 时间窗口、契约或准备产物不合法。
        FeedbackQueryError: 反馈列表或详情查询失败。
        httpx.HTTPError: 反馈接口发生网络错误。
    """
    window = resolve_report_window(args.date_from, args.date_to)
    comparison_window = resolve_comparison_window(window)
    prepared_dir = _prepared_directory(window)
    taxonomy_store_id = _taxonomy_store_id(args.taxonomy_file)
    reusable = _prepared_manifest_reusable(prepared_dir, taxonomy_store_id)
    if reusable is not None:
        return {
            "success": True,
            "state": reusable["state"],
            "period_key": reusable["period_key"],
            "prepared_dir": str(prepared_dir),
            "reused": True,
        }

    generated_at = datetime.now(timezone.utc)
    context = _run_context(window, generated_at, insight_requested=True)
    manifest_path = prepared_dir / "manifest.json"
    preparing = {
        "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
        "period_key": context.period_key,
        "state": "preparing",
        "period": _period_payload(window),
        "comparison_period": _period_payload(comparison_window),
        "started_at": generated_at.isoformat().replace("+00:00", "Z"),
    }
    _write_json_artifact(preparing, manifest_path)
    try:
        client = FeedbackQueryClient(load_api_key(), args.base_url, args.timeout)
        feedbacks = fetch_feedbacks(client, window, per_page=args.per_page)
        comparison_feedbacks = fetch_feedbacks(
            client, comparison_window, per_page=args.per_page
        )
        current_details = fetch_feedback_details(client, feedbacks)
        comparison_details = fetch_feedback_details(client, comparison_feedbacks)
        analysis_input = {
            "period": _period_payload(window),
            "comparison_period": _period_payload(comparison_window),
            "current_feedbacks": build_insight_feedbacks(feedbacks, current_details),
            "comparison_feedbacks": build_insight_feedbacks(
                comparison_feedbacks, comparison_details
            ),
        }
        report_input = {"feedbacks": _safe_report_feedbacks(feedbacks)}
        _write_json_artifact(analysis_input, prepared_dir / "analysis-input.json")
        _write_json_artifact(report_input, prepared_dir / "report-input.json")

        model_feedbacks = [
            {**item, "period": period}
            for period, items in (
                ("current", analysis_input["current_feedbacks"]),
                ("comparison", analysis_input["comparison_feedbacks"]),
            )
            for item in items
        ]
        taxonomy_state, cached_classifications, pending_feedbacks = (
            _partition_taxonomy_matches(model_feedbacks, args.taxonomy_file)
        )
        cached_payload = {
            "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
            "period_key": context.period_key,
            "feedback_uuids": [
                classification["feedback_uuid"]
                for classification in cached_classifications
            ],
            "classifications": cached_classifications,
        }
        _write_json_artifact(
            cached_payload,
            prepared_dir / "cached-classifications.json",
        )
        chunks: list[dict[str, Any]] = []
        for start in range(0, len(pending_feedbacks), PREPARED_CHUNK_SIZE):
            index = len(chunks) + 1
            input_name = f"chunks/chunk-{index:03d}.input.json"
            output_name = f"chunks/chunk-{index:03d}.output.json"
            chunk_payload = {
                "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
                "period_key": context.period_key,
                "chunk_index": index,
                "feedbacks": pending_feedbacks[start : start + PREPARED_CHUNK_SIZE],
            }
            _write_json_artifact(chunk_payload, prepared_dir / input_name)
            chunks.append(
                {
                    "index": index,
                    "status": "pending",
                    "feedback_count": len(chunk_payload["feedbacks"]),
                    "input": input_name,
                    "input_sha256": _payload_hash(chunk_payload),
                    "output": output_name,
                }
            )

        manifest = {
            **preparing,
            "state": "ready",
            "prepared_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "feedback_count": len(feedbacks),
            "comparison_feedback_count": len(comparison_feedbacks),
            "model_feedback_count": len(model_feedbacks),
            "source_snapshots": {
                "current": _source_snapshot_hash(feedbacks),
                "comparison": _source_snapshot_hash(comparison_feedbacks),
                "analysis_input": _payload_hash(analysis_input),
                "report_input": _payload_hash(report_input),
                "cached_classifications": _payload_hash(cached_payload),
            },
            "artifacts": {
                "analysis_input": "analysis-input.json",
                "report_input": "report-input.json",
                "cached_classifications": "cached-classifications.json",
                "ready_marker": "READY",
            },
            "taxonomy": {
                "schema_version": taxonomy_state.get("schema_version"),
                "store_id": taxonomy_store_id,
                "revision": int(taxonomy_state.get("revision") or 0),
                "cache_hit_count": len(cached_classifications),
                "model_classification_count": len(pending_feedbacks),
            },
            "chunks": chunks,
            "contract": {
                "prompt_version": CODEX_INSIGHT_PROMPT_VERSION,
                "prompt_hash": _codex_contract_hash(),
            },
        }
        _write_json_artifact(manifest, manifest_path)
        # manifest 是原子主状态；READY 最后写，避免失败运行留下虚假完成标记。
        _write_text_atomically(
            f"{window.label} 数据已完成\n",
            resolve_output_path(prepared_dir / "READY"),
        )
        return {
            "success": True,
            "state": "ready",
            "period_key": context.period_key,
            "prepared_dir": str(prepared_dir),
            "feedback_count": len(feedbacks),
            "comparison_feedback_count": len(comparison_feedbacks),
            "chunk_count": len(chunks),
            "taxonomy_cache_hit_count": len(cached_classifications),
            "model_classification_count": len(pending_feedbacks),
            "reused": False,
        }
    except Exception as exc:
        failure = {
            **preparing,
            "state": "failed",
            "failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "failure": _execution_failure(exc),
        }
        _write_json_artifact(failure, manifest_path)
        raise


def claim_ready_preparation(window: ReportWindow) -> dict[str, Any]:
    """领取最新 ready 数据，或恢复上次未完成的 analyzing 数据。

    Args:
        window: 本次自动化应消费的单日报告窗口，默认由命令解析为上海时区昨日。

    Returns:
        idle 状态，或包含准备目录、分块和契约元数据的 analyzing 状态。

    Raises:
        DailyReportError: 反馈输出目录或候选准备清单不可安全读取。
    """
    prepared_root = resolve_output_path(Path("prepared") / "placeholder").parent
    manifest_path = prepared_root / window.label / "manifest.json"
    manifest = _prepared_manifest_reusable(manifest_path.parent)
    if manifest is None or manifest.get("state") not in {
        "ready",
        "analyzing",
        "narrating",
    }:
        return {
            "success": True,
            "state": "idle",
            "period": window.label,
            "reason": "昨日没有可分析的 ready 数据",
        }
    if manifest.get("state") != "narrating":
        manifest["state"] = "analyzing"
    manifest["claimed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest["claim_count"] = int(manifest.get("claim_count") or 0) + 1
    _write_json_artifact(manifest, manifest_path)
    return {
        "success": True,
        "state": manifest["state"],
        "period_key": manifest["period_key"],
        "prepared_dir": str(manifest_path.parent),
        "analysis_input": str(manifest_path.parent / manifest["artifacts"]["analysis_input"]),
        "chunks": manifest.get("chunks", []),
        "narrative": manifest.get("narrative"),
        "narrative_input": (
            str(manifest_path.parent / manifest["artifacts"]["narrative_input"])
            if manifest.get("artifacts", {}).get("narrative_input")
            else None
        ),
        "narrative_output": (
            str(manifest_path.parent / manifest["artifacts"]["narrative_output"])
            if manifest.get("artifacts", {}).get("narrative_output")
            else None
        ),
        "contract": manifest.get("contract", {}),
    }


def _chunk_record_for_output(
    prepared_dir: Path,
    manifest: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    try:
        relative_output = output_path.relative_to(prepared_dir).as_posix()
    except ValueError as exc:
        raise DailyReportError("chunk 输出必须位于对应 prepared 目录") from exc
    for chunk in manifest.get("chunks", []):
        if isinstance(chunk, dict) and chunk.get("output") == relative_output:
            return chunk
    raise DailyReportError("chunk 输出未在准备清单中声明")


def _validated_chunk_classifications(
    prepared_dir: Path,
    manifest: dict[str, Any],
    chunk: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    input_payload = _read_json_artifact(prepared_dir / chunk["input"], "chunk 输入")
    if _payload_hash(input_payload) != chunk.get("input_sha256"):
        raise DailyReportError("chunk 输入哈希不匹配")
    output_payload = _read_json_artifact(prepared_dir / chunk["output"], "chunk 输出")
    allowed_top_level = {
        "schema_version",
        "period_key",
        "chunk_index",
        "classifications",
    }
    if set(output_payload) != allowed_top_level:
        raise DailyReportError("chunk 输出包含缺失或契约外顶层字段")
    if (
        output_payload.get("schema_version") != PREPARED_ARTIFACT_SCHEMA_VERSION
        or output_payload.get("period_key") != manifest.get("period_key")
        or output_payload.get("chunk_index") != chunk.get("index")
    ):
        raise DailyReportError("chunk 输出元数据与准备清单不一致")
    feedbacks = input_payload.get("feedbacks")
    if not isinstance(feedbacks, list):
        raise DailyReportError("chunk 输入缺少 feedbacks 数组")
    expected_uuids = [str(item.get("feedback_uuid") or "") for item in feedbacks]
    try:
        normalized = validate_feedback_classifications(
            output_payload.get("classifications"),
            expected_uuids,
        )
    except Exception as exc:
        raise DailyReportError(f"chunk 分类校验失败: {_safe_insight_text(str(exc), 500)}") from exc
    canonical_payload = {
        "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
        "period_key": manifest["period_key"],
        "chunk_index": chunk["index"],
        "classifications": normalized,
    }
    return normalized, _payload_hash(canonical_payload)


def validate_prepared_chunk(output: Path) -> dict[str, Any]:
    """校验单个 Codex 分类输出并原子更新准备清单检查点。

    Args:
        output: 位于 prepared 目录内、已由 Codex 写入的 chunk 输出路径。

    Returns:
        周期键、chunk 序号、分类数和 validated 状态。

    Raises:
        DailyReportError: 路径、元数据、哈希、稳定键、置信度或 UUID 覆盖不合法。
    """
    output_path = resolve_output_path(output)
    prepared_dir = output_path.parent.parent
    manifest_path = prepared_dir / "manifest.json"
    manifest = _read_json_artifact(manifest_path, "准备清单")
    chunk = _chunk_record_for_output(prepared_dir, manifest, output_path)
    try:
        classifications, _ = _validated_chunk_classifications(
            prepared_dir, manifest, chunk
        )
    except DailyReportError as exc:
        chunk["status"] = "failed"
        chunk["error"] = {"code": "CHUNK_VALIDATION_ERROR", "message": str(exc)}
        _write_json_artifact(
            {
                "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
                "status": "invalid",
                "error": {"code": "CHUNK_VALIDATION_ERROR"},
            },
            output_path,
        )
        _write_json_artifact(manifest, manifest_path)
        raise
    canonical_output = {
        "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
        "period_key": manifest["period_key"],
        "chunk_index": chunk["index"],
        "classifications": classifications,
    }
    _write_json_artifact(canonical_output, output_path)
    output_hash = _payload_hash(canonical_output)
    chunk.update(
        {
            "status": "validated",
            "classification_count": len(classifications),
            "output_sha256": output_hash,
            "validated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )
    chunk.pop("error", None)
    _write_json_artifact(manifest, manifest_path)
    return {
        "success": True,
        "status": "validated",
        "period_key": manifest["period_key"],
        "chunk_index": chunk["index"],
        "classification_count": len(classifications),
    }


def _load_prepared_analysis(
    prepared_dir: Path,
    args: argparse.Namespace,
    allowed_states: set[str],
) -> PreparedAnalysis:
    """校验 prepared 输入和分类，并生成确定性聚合结果。"""
    manifest_path = prepared_dir / "manifest.json"
    prepared = _read_json_artifact(manifest_path, "准备清单")
    if prepared.get("state") not in allowed_states:
        raise DailyReportError("准备清单不是当前阶段可处理状态")
    if prepared.get("taxonomy", {}).get("store_id") != _taxonomy_store_id(
        args.taxonomy_file
    ):
        raise DailyReportError("使用的 taxonomy 文件与准备阶段不一致")
    analysis_input = _read_json_artifact(
        prepared_dir / prepared["artifacts"]["analysis_input"], "analysis-input"
    )
    report_input = _read_json_artifact(
        prepared_dir / prepared["artifacts"]["report_input"], "report-input"
    )
    snapshots = prepared.get("source_snapshots", {})
    if (
        _payload_hash(analysis_input) != snapshots.get("analysis_input")
        or _payload_hash(report_input) != snapshots.get("report_input")
    ):
        raise DailyReportError("准备输入哈希不匹配，拒绝继续")

    cached_path = prepared.get("artifacts", {}).get("cached_classifications")
    if not isinstance(cached_path, str):
        raise DailyReportError("准备清单缺少 taxonomy 缓存分类产物")
    cached_payload = _read_json_artifact(
        prepared_dir / cached_path, "cached-classifications"
    )
    if _payload_hash(cached_payload) != snapshots.get("cached_classifications"):
        raise DailyReportError("taxonomy 缓存分类哈希不匹配，拒绝继续")
    if set(cached_payload) != {
        "schema_version",
        "period_key",
        "feedback_uuids",
        "classifications",
    } or (
        cached_payload.get("schema_version") != PREPARED_ARTIFACT_SCHEMA_VERSION
        or cached_payload.get("period_key") != prepared.get("period_key")
        or not isinstance(cached_payload.get("feedback_uuids"), list)
    ):
        raise DailyReportError("taxonomy 缓存分类元数据不合法")
    try:
        classifications = validate_feedback_classifications(
            cached_payload.get("classifications"),
            [str(value) for value in cached_payload["feedback_uuids"]],
        )
    except Exception as exc:
        raise DailyReportError(
            f"taxonomy 缓存分类校验失败: {_safe_insight_text(str(exc), 500)}"
        ) from exc
    taxonomy_cache_hit_count = len(classifications)

    chunks = prepared.get("chunks")
    if not isinstance(chunks, list):
        raise DailyReportError("准备清单缺少 chunks 数组")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise DailyReportError("准备清单包含非法 chunk")
        if chunk.get("status") != "validated":
            raise DailyReportError("存在尚未 validated 的 chunk，拒绝继续")
        rows, output_hash = _validated_chunk_classifications(
            prepared_dir, prepared, chunk
        )
        if chunk.get("output_sha256") != output_hash:
            raise DailyReportError("已校验 chunk 输出在检查点后发生变化")
        classifications.extend(rows)

    contract = prepared.get("contract", {})
    insight_runtime = {
        "provider": "codex_app",
        "model": _safe_insight_text(args.analysis_model, 100),
        "batch_size": max(
            (int(chunk.get("feedback_count") or 0) for chunk in chunks), default=0
        ),
        "batch_count": len(chunks),
        "taxonomy_cache_hit_count": taxonomy_cache_hit_count,
        "model_classification_count": sum(
            int(chunk.get("feedback_count") or 0) for chunk in chunks
        ),
        "prompt_version": contract.get("prompt_version")
        or CODEX_INSIGHT_PROMPT_VERSION,
        "prompt_hash": contract.get("prompt_hash") or _codex_contract_hash(),
    }
    insight = aggregate_feedback_classifications(
        analysis_input, classifications, model_metadata=insight_runtime
    )
    model_feedbacks = [
        {**item, "period": period_name}
        for period_name, items in (
            ("current", analysis_input.get("current_feedbacks", [])),
            ("comparison", analysis_input.get("comparison_feedbacks", [])),
        )
        for item in items
        if isinstance(item, dict)
    ]
    period = prepared["period"]
    comparison_period = prepared["comparison_period"]
    window = ReportWindow(period["date_from"], period["date_to"], period["label"])
    comparison_window = ReportWindow(
        comparison_period["date_from"],
        comparison_period["date_to"],
        comparison_period["label"],
    )
    feedbacks = report_input.get("feedbacks")
    if not isinstance(feedbacks, list):
        raise DailyReportError("report-input 缺少 feedbacks 数组")
    return PreparedAnalysis(
        prepared=prepared,
        manifest_path=manifest_path,
        analysis_input=analysis_input,
        report_input=report_input,
        snapshots=snapshots,
        classifications=classifications,
        insight_runtime=insight_runtime,
        insight=insight,
        model_feedbacks=model_feedbacks,
        window=window,
        comparison_window=comparison_window,
        feedbacks=feedbacks,
    )


def _management_facts(analysis: PreparedAnalysis) -> dict[str, Any]:
    """从完整分类映射生成只读管理事实，AI 不参与数值计算。"""
    classification_map = {
        item["feedback_uuid"]: item for item in analysis.classifications
    }
    current = analysis.analysis_input.get("current_feedbacks", [])
    previous = analysis.analysis_input.get("comparison_feedbacks", [])
    problem_total = len(current)
    category_counts: Counter[str] = Counter()
    category_severe: Counter[str] = Counter()
    category_users: dict[str, set[str]] = {}
    for item in current:
        classification = classification_map[item["feedback_uuid"]]
        category = classification["problem_category"]
        category_counts[category] += 1
        if item.get("severity") in {"critical", "high"}:
            category_severe[category] += 1
        user_key = item.get("user_key")
        if user_key:
            category_users.setdefault(category, set()).add(str(user_key))
    root_causes = [
        {
            "category": category,
            "current_count": count,
            "share_percent": round(count * 100 / problem_total, 1)
            if problem_total
            else 0.0,
            "severe_count": category_severe[category],
            "affected_users": len(category_users.get(category, set())),
        }
        for category, count in category_counts.most_common(12)
    ]
    remaining_categories = [
        category for category, _count in category_counts.most_common()[12:]
    ]
    if remaining_categories:
        remaining_count = sum(category_counts[category] for category in remaining_categories)
        remaining_users = set().union(
            *(category_users.get(category, set()) for category in remaining_categories)
        )
        root_causes.append(
            {
                "category": "其他问题",
                "current_count": remaining_count,
                "share_percent": round(remaining_count * 100 / problem_total, 1)
                if problem_total
                else 0.0,
                "severe_count": sum(
                    category_severe[category] for category in remaining_categories
                ),
                "affected_users": len(remaining_users),
            }
        )
    problem_rows = []
    for problem in analysis.insight.get("problems", []):
        row = dict(problem)
        row["problem_ref"] = f"{problem['module']}/{problem['problem_key']}"
        problem_rows.append(row)
    severe_by_module: Counter[str] = Counter()
    for row in problem_rows:
        if row["severity"] in {"critical", "high"}:
            severe_by_module[row["module"]] += row["current_count"]
    modules = []
    ranked_modules = sorted(
        analysis.insight.get("modules", []),
        key=lambda item: (-item["feedback_count"], item["module"]),
    )
    for row in ranked_modules[:7]:
        module = row["module"]
        modules.append(
            {
                **row,
                "share_percent": round(row["feedback_count"] * 100 / problem_total, 1)
                if problem_total
                else 0.0,
                "severe_count": severe_by_module[module],
            }
        )

    def period_metrics(items: list[dict[str, Any]]) -> tuple[int, int, int]:
        return (
            len(items),
            sum(
                1 for item in items if item.get("severity") in {"critical", "high"}
            ),
            len({str(item["user_key"]) for item in items if item.get("user_key")}),
        )

    current_count, current_severe, current_users = period_metrics(current)
    previous_count, previous_severe, previous_users = period_metrics(previous)
    change_percent = (
        None
        if previous_count == 0
        else round((current_count - previous_count) * 100 / previous_count, 1)
    )
    return {
        "period": analysis.prepared["period"],
        "comparison_period": analysis.prepared["comparison_period"],
        "base_metrics": _build_base_metrics(analysis.feedbacks),
        "root_causes": root_causes,
        "modules": modules,
        "repeated_problems": sorted(
            [row for row in problem_rows if row["current_count"] > 1],
            key=lambda item: (-item["current_count"], item["problem_ref"]),
        )[:10],
        "priority_risks": [
            row for row in problem_rows if row["priority"] in {"P0", "P1"}
        ],
        "all_problems": problem_rows,
        "comparison": {
            "current_label": analysis.window.label,
            "previous_label": analysis.comparison_window.label,
            "current_count": current_count,
            "previous_count": previous_count,
            "change_percent": change_percent,
            "current_severe_count": current_severe,
            "previous_severe_count": previous_severe,
            "current_affected_users": current_users,
            "previous_affected_users": previous_users,
        },
    }


def prepare_report_narrative(args: argparse.Namespace) -> dict[str, Any]:
    """在分类完成后生成供 Codex 撰写管理叙事的确定性事实包。

    Args:
        args: 包含 prepared 目录、taxonomy 路径和分析模型标识的命令参数。

    Returns:
        叙事输入输出路径、当前状态及是否复用既有事实包。

    Raises:
        DailyReportError: prepared 分类、输入哈希或 taxonomy 身份不合法。
    """
    prepared_dir = resolve_output_path(args.prepare_narrative / "placeholder").parent
    analysis = _load_prepared_analysis(
        prepared_dir,
        args,
        {"ready", "analyzing", "failed", "completed", "narrating"},
    )
    existing_input = analysis.prepared.get("artifacts", {}).get("narrative_input")
    existing_output = analysis.prepared.get("artifacts", {}).get("narrative_output")
    existing_hash = analysis.prepared.get("source_snapshots", {}).get(
        "narrative_input"
    )
    if (
        analysis.prepared.get("state") == "narrating"
        and isinstance(existing_input, str)
        and isinstance(existing_output, str)
        and isinstance(existing_hash, str)
    ):
        existing_payload = _read_json_artifact(
            prepared_dir / existing_input, "narrative-input"
        )
        if _payload_hash(existing_payload) == existing_hash:
            return {
                "success": True,
                "state": "narrating",
                "period_key": analysis.prepared["period_key"],
                "input": str(prepared_dir / existing_input),
                "output": str(prepared_dir / existing_output),
                "narrative_status": analysis.prepared.get("narrative", {}).get(
                    "status"
                ),
                "reused": True,
            }
    narrative_input = {
        "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
        "period_key": analysis.prepared["period_key"],
        "facts": _management_facts(analysis),
    }
    input_path = prepared_dir / "narrative-input.json"
    output_path = prepared_dir / "narrative-output.json"
    _write_json_artifact(narrative_input, input_path)
    analysis.prepared["state"] = "narrating"
    analysis.prepared["contract"] = {
        "prompt_version": CODEX_INSIGHT_PROMPT_VERSION,
        "prompt_hash": _codex_contract_hash(),
    }
    analysis.prepared["artifacts"].update(
        {
            "narrative_input": input_path.name,
            "narrative_output": output_path.name,
        }
    )
    analysis.prepared["source_snapshots"]["narrative_input"] = _payload_hash(
        narrative_input
    )
    analysis.prepared["narrative"] = {"status": "pending"}
    _write_json_artifact(analysis.prepared, analysis.manifest_path)
    (prepared_dir / "COMPLETED").unlink(missing_ok=True)
    return {
        "success": True,
        "state": "narrating",
        "period_key": analysis.prepared["period_key"],
        "input": str(input_path),
        "output": str(output_path),
        "narrative_status": "pending",
        "reused": False,
    }


def _narrative_text(value: Any, label: str, maximum: int) -> str:
    text = _safe_insight_text(value, maximum).strip()
    if not text:
        raise DailyReportError(f"管理叙事缺少{label}")
    if re.search(r"\d", text):
        raise DailyReportError(f"管理叙事{label}不得自行引用数字")
    numeric_text = text
    for lexical_word in (
        "统一",
        "一致",
        "单一",
        "唯一",
        "同一",
        "进一步",
        "一旦",
        "一律",
        "一并",
        "一体",
    ):
        numeric_text = numeric_text.replace(lexical_word, "")
    if re.search(r"[零〇一二两三四五六七八九十百千万亿]", numeric_text) or re.search(
        r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
        r"eighty|ninety|hundreds?|thousands?|millions?|billions?|trillions?|"
        r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
        r"eleventh|twelfth|dozens?|scores?|half|halves|quarters?|couple|pair)\b",
        numeric_text,
        re.IGNORECASE,
    ):
        raise DailyReportError(f"管理叙事{label}不得自行引用数字")
    return text


def _validate_report_narrative(
    payload: dict[str, Any],
    narrative_input: dict[str, Any],
    *,
    allow_derived_priority: bool = False,
) -> dict[str, Any]:
    """校验管理叙事字段、事实引用和确定性优先级边界。"""
    allowed = {
        "schema_version",
        "period_key",
        "executive_summary",
        "module_insights",
        "risk_themes",
        "governance_actions",
        "limitations",
    }
    if set(payload) != allowed:
        raise DailyReportError("管理叙事包含缺失或契约外顶层字段")
    if (
        payload.get("schema_version") != PREPARED_ARTIFACT_SCHEMA_VERSION
        or payload.get("period_key") != narrative_input.get("period_key")
    ):
        raise DailyReportError("管理叙事元数据与事实包不一致")
    facts = narrative_input["facts"]
    known_modules = {item["module"] for item in facts["modules"]}
    problem_by_ref = {
        item["problem_ref"]: item for item in facts["all_problems"]
    }
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}

    def text_list(key: str, minimum: int, maximum: int) -> list[str]:
        values = payload.get(key)
        if not isinstance(values, list) or not minimum <= len(values) <= maximum:
            raise DailyReportError(f"管理叙事 {key} 数量不合法")
        return [
            _narrative_text(value, key, 1000 if key == "executive_summary" else 500)
            for value in values
        ]

    module_insights = payload.get("module_insights")
    if not isinstance(module_insights, list) or len(module_insights) > 7:
        raise DailyReportError("管理叙事 module_insights 数量不合法")
    normalized_modules = []
    seen_modules: set[str] = set()
    for item in module_insights:
        if not isinstance(item, dict) or set(item) != {"module", "insight"}:
            raise DailyReportError("管理叙事模块洞悉字段不合法")
        module = str(item.get("module") or "")
        if module not in known_modules or module in seen_modules:
            raise DailyReportError("管理叙事模块未在事实包中声明或重复")
        seen_modules.add(module)
        normalized_modules.append(
            {"module": module, "insight": _narrative_text(item["insight"], "模块洞悉", 300)}
        )

    def themed_items(
        key: str, allowed_evidence_priorities: set[str]
    ) -> list[dict[str, Any]]:
        values = payload.get(key)
        if not isinstance(values, list) or len(values) > 6:
            raise DailyReportError(f"管理叙事 {key} 数量不合法")
        normalized = []
        for item in values:
            expected_fields = {
                "title",
                "summary",
                "problem_refs",
                "recommendation",
            }
            if allow_derived_priority:
                expected_fields.add("priority")
            if not isinstance(item, dict) or set(item) != expected_fields:
                raise DailyReportError(f"管理叙事 {key} 字段不合法")
            refs = item.get("problem_refs")
            if not isinstance(refs, list) or not refs:
                raise DailyReportError(f"管理叙事 {key} 证据不合法")
            if len(refs) != len(set(refs)) or any(ref not in problem_by_ref for ref in refs):
                raise DailyReportError("管理叙事问题引用未在事实包中声明或重复")
            evidence_priorities = {
                problem_by_ref[ref]["priority"] for ref in refs
            }
            if not evidence_priorities <= allowed_evidence_priorities:
                raise DailyReportError(f"管理叙事 {key} 引用了不允许的优先级")
            priority = min(
                evidence_priorities, key=lambda value: priority_rank[value]
            )
            if allow_derived_priority and item.get("priority") != priority:
                raise DailyReportError("管理叙事派生优先级与确定性事实不一致")
            normalized.append(
                {
                    "priority": priority,
                    "title": _narrative_text(item["title"], "主题标题", 120),
                    "summary": _narrative_text(item["summary"], "主题摘要", 600),
                    "problem_refs": list(refs),
                    "recommendation": _narrative_text(
                        item["recommendation"], "治理建议", 800
                    ),
                }
            )
        return normalized

    risk_themes = themed_items("risk_themes", {"P0", "P1"})
    expected_risk_refs = {
        item["problem_ref"] for item in facts["priority_risks"]
    }
    covered_risk_refs = {
        problem_ref
        for theme in risk_themes
        for problem_ref in theme["problem_refs"]
    }
    if covered_risk_refs != expected_risk_refs:
        raise DailyReportError("风险主题未完整覆盖确定性 P0/P1 问题")
    governance_actions = themed_items("governance_actions", {"P1", "P2"})
    has_governance_candidates = any(
        item["priority"] in {"P1", "P2"} for item in facts["all_problems"]
    )
    if has_governance_candidates and not governance_actions:
        raise DailyReportError("存在 P1/P2 问题时必须提供治理工作建议")
    return {
        "schema_version": PREPARED_ARTIFACT_SCHEMA_VERSION,
        "period_key": narrative_input["period_key"],
        "executive_summary": text_list("executive_summary", 1, 3),
        "module_insights": normalized_modules,
        "risk_themes": risk_themes,
        "governance_actions": governance_actions,
        "limitations": text_list("limitations", 1, 5),
    }


def validate_report_narrative(output: Path) -> dict[str, Any]:
    """校验 Codex 管理叙事并原子更新 prepared 检查点。

    Args:
        output: Codex 写入且由 manifest 声明的 narrative-output.json 路径。

    Returns:
        周期键、规范化输出路径和 validated 状态。

    Raises:
        DailyReportError: 文件、哈希、字段、问题引用或优先级证据不合法。
    """
    output_path = resolve_output_path(output)
    prepared_dir = output_path.parent
    manifest_path = prepared_dir / "manifest.json"
    manifest = _read_json_artifact(manifest_path, "准备清单")
    declared_output = manifest.get("artifacts", {}).get("narrative_output")
    if declared_output != output_path.name:
        raise DailyReportError("管理叙事输出未在准备清单中声明")
    input_path = prepared_dir / manifest["artifacts"]["narrative_input"]
    narrative_input = _read_json_artifact(input_path, "narrative-input")
    if _payload_hash(narrative_input) != manifest.get("source_snapshots", {}).get(
        "narrative_input"
    ):
        raise DailyReportError("管理叙事事实包哈希不匹配")
    payload = _read_json_artifact(output_path, "narrative-output")
    canonical = _validate_report_narrative(payload, narrative_input)
    _write_json_artifact(canonical, output_path)
    manifest["narrative"] = {
        "status": "validated",
        "output_sha256": _payload_hash(canonical),
        "validated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json_artifact(manifest, manifest_path)
    return {
        "success": True,
        "status": "validated",
        "period_key": manifest["period_key"],
        "output": str(output_path),
    }


def finalize_prepared_report(args: argparse.Namespace) -> dict[str, Any]:
    """校验 Codex 分类，确定性聚合并发布日报。

    Args:
        args: 包含 prepared 目录、模型标识、输出位置和通知开关的命令参数。

    Returns:
        最终运行 ID、报告与结构化产物路径、通知状态和反馈数量。

    Raises:
        DailyReportError: 准备产物、分类输出、发布或通知不合法或失败。
    """
    prepared_dir = resolve_output_path(args.finalize_prepared / "placeholder").parent
    analysis = _load_prepared_analysis(
        prepared_dir, args, {"narrating", "failed"}
    )
    prepared = analysis.prepared
    prepared_manifest_path = analysis.manifest_path
    snapshots = analysis.snapshots
    insight_runtime = analysis.insight_runtime
    insight = analysis.insight
    narrative_meta = prepared.get("narrative")
    if not isinstance(narrative_meta, dict) or narrative_meta.get("status") != "validated":
        raise DailyReportError("管理叙事尚未 validated，拒绝最终化")
    narrative_input = _read_json_artifact(
        prepared_dir / prepared["artifacts"]["narrative_input"], "narrative-input"
    )
    narrative_output = _read_json_artifact(
        prepared_dir / prepared["artifacts"]["narrative_output"], "narrative-output"
    )
    if (
        _payload_hash(narrative_input) != snapshots.get("narrative_input")
        or _payload_hash(narrative_output) != narrative_meta.get("output_sha256")
    ):
        raise DailyReportError("管理叙事在检查点后发生变化")
    narrative = _validate_report_narrative(
        narrative_output, narrative_input, allow_derived_priority=True
    )
    classification_map = {
        classification["feedback_uuid"]: classification
        for classification in analysis.classifications
    }
    try:
        taxonomy_store = _taxonomy_store(args.taxonomy_file)
        taxonomy_state = taxonomy_store.persist(
            taxonomy_store.load(),
            analysis.model_feedbacks,
            classification_map,
        )
    except (InsightConfigError, KeyError) as exc:
        raise DailyReportError(str(exc)) from exc
    insight_runtime["taxonomy_revision"] = int(taxonomy_state.get("revision") or 0)
    window = analysis.window
    comparison_window = analysis.comparison_window
    feedbacks = analysis.feedbacks
    management = {"facts": narrative_input["facts"], "narrative": narrative}
    insight = {
        **insight,
        "management_facts": narrative_input["facts"],
        "report_narrative": narrative,
    }

    generated_at = datetime.now(timezone.utc)
    context = _run_context(window, generated_at, insight_requested=True)
    started_at = perf_counter()
    _start_run_manifest(
        context,
        insight_requested=True,
        insight_runtime=insight_runtime,
        notification_requested=args.send,
    )
    try:
        base_metrics = _build_base_metrics(feedbacks)
        markdown = render_markdown(
            feedbacks,
            window,
            insight,
            False,
            base_metrics,
            management=management,
        )
        output_path = resolve_output_path(
            args.output or Path(f"反馈日报-{window.label.replace(' 至 ', '_')}.md")
        )
        archived_report_path = write_markdown(markdown, context.directory / "report.md")
        notification: dict[str, Any] = {
            "requested": args.send,
            "status": "pending" if args.send else "disabled",
        }
        notification_error = None
        if args.send:
            try:
                send_wecom_summary(render_wecom_summary(feedbacks, window, insight, False))
                notification["status"] = "success"
            except DailyReportError as exc:
                notification["status"] = "failed"
                notification["error"] = {
                    "code": "NOTIFICATION_ERROR",
                    "message": _safe_insight_text(str(exc), 500),
                }
                notification_error = exc
        outcome = RunOutcome(
            comparison_window=comparison_window,
            base_metrics=base_metrics,
            source_snapshots={
                "current": snapshots.get("current"),
                "comparison": snapshots.get("comparison"),
                "model_input": snapshots.get("analysis_input"),
            },
            insight=insight,
            insight_requested=True,
            insight_error=None,
            insight_runtime=insight_runtime,
            published_report_path=output_path,
            archived_report_path=archived_report_path,
            notification=notification,
            timings_ms={},
        )
        manifest_path, clusters_path = _write_run_artifacts(context=context, outcome=outcome)
        output_path = write_markdown(markdown, output_path)
        _finalize_run_manifest(
            manifest_path,
            notification=notification,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )
        prepared.update(
            {
                "state": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "analysis": insight_runtime,
                "result": {
                    "run_id": context.run_id,
                    "manifest": str(manifest_path),
                    "clusters": str(clusters_path),
                    "report": str(output_path),
                },
            }
        )
        _write_json_artifact(prepared, prepared_manifest_path)
        # completed manifest 是原子主状态；COMPLETED 最后写，避免失败运行留下假标记。
        _write_text_atomically(
            f"{window.label} AI 洞察已完成\n",
            resolve_output_path(prepared_dir / "COMPLETED"),
        )
        result = {
            "success": True,
            "state": "completed",
            "run_id": context.run_id,
            "output": str(output_path),
            "manifest": str(manifest_path),
            "clusters": str(clusters_path),
            "feedback_count": len(feedbacks),
            "insight": True,
            "taxonomy_cache_hit_count": insight_runtime["taxonomy_cache_hit_count"],
            "model_classification_count": insight_runtime["model_classification_count"],
            "sent": notification["status"] == "success",
        }
        if notification_error is not None:
            result["notification_error"] = {
                "code": "NOTIFICATION_ERROR",
                "message": _safe_insight_text(str(notification_error), 500),
            }
        return result
    except Exception as exc:
        _record_run_failure(
            context,
            stage="finalize_prepared",
            exc=exc,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )
        prepared["state"] = "failed"
        prepared["failure"] = _execution_failure(exc)
        try:
            resolve_output_path(prepared_dir / "COMPLETED").unlink(missing_ok=True)
        except OSError:
            pass
        _write_json_artifact(prepared, prepared_manifest_path)
        raise


def main(argv: list[str] | None = None) -> int:
    """查询反馈、生成 Markdown 日报并按需推送企业微信。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    pipeline_action = any(
        (
            args.prepare_only,
            args.claim_ready,
            args.validate_chunk is not None,
            args.prepare_narrative is not None,
            args.validate_narrative is not None,
            args.finalize_prepared is not None,
        )
    )
    if pipeline_action:
        if args.insight or args.insight_config is not None:
            _print_json(
                {
                    "code": "DAILY_REPORT_ERROR",
                    "msg": "两阶段流水线不接受 --insight 或 --insight-config",
                },
                stream=sys.stderr,
            )
            return 1
        try:
            if args.prepare_only:
                result = prepare_feedback_data(args)
            elif args.claim_ready:
                result = claim_ready_preparation(
                    resolve_report_window(args.date_from, args.date_to)
                )
            elif args.validate_chunk is not None:
                result = validate_prepared_chunk(args.validate_chunk)
            elif args.prepare_narrative is not None:
                result = prepare_report_narrative(args)
            elif args.validate_narrative is not None:
                result = validate_report_narrative(args.validate_narrative)
            else:
                result = finalize_prepared_report(args)
        except FeedbackQueryError as exc:
            _print_json(exc.payload, stream=sys.stderr)
            return 1
        except DailyReportError as exc:
            _print_json({"code": "DAILY_REPORT_ERROR", "msg": str(exc)}, stream=sys.stderr)
            return 1
        except httpx.HTTPError:
            _print_json(
                {"code": "NETWORK_ERROR", "msg": "反馈查询接口网络请求失败"},
                stream=sys.stderr,
            )
            return 1
        _print_json(result)
        return 0

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
                        args.taxonomy_file,
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
