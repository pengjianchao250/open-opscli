"""生成内部反馈 Markdown 日报并可选推送企业微信群机器人。

脚本默认统计 Asia/Shanghai 时区的完整昨日，自动翻页读取反馈列表，
仅使用非敏感列表字段生成报告和群消息。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

import httpx

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


class DailyReportError(Exception):
    """表示日报参数、响应、文件或企业微信推送失败。"""


class ReportWindow(NamedTuple):
    """反馈日报查询时间窗口。"""

    date_from: str
    date_to: str
    label: str


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


def _count_rows(counter: Counter[str], order: tuple[str, ...]) -> list[str]:
    """按固定业务顺序生成 Markdown 统计表行。"""
    rows = [f"| {name} | {counter[name]} |" for name in order if counter[name]]
    known = set(order)
    rows.extend(f"| {_safe_text(name)} | {count} |" for name, count in sorted(counter.items()) if name not in known)
    return rows or ["| - | 0 |"]


def render_markdown(feedbacks: list[dict[str, Any]], window: ReportWindow) -> str:
    """将反馈列表渲染为不含个人和执行上下文的 Markdown 日报。"""
    problems = [item for item in feedbacks if item.get("feedback_type") != "query_result"]
    severe = [item for item in problems if item.get("severity") in {"critical", "high"}]
    failed_calls = sum(int(item.get("failed_call_count") or 0) for item in feedbacks)
    type_counter = Counter(str(item.get("feedback_type") or "unknown") for item in feedbacks)
    severity_counter = Counter(str(item.get("severity") or "unknown") for item in problems)
    source_counter = Counter(str(item.get("source") or "unknown") for item in problems)
    status_counter = Counter(str(item.get("status") or "unknown") for item in problems)

    lines = [
        f"# 反馈日报（{window.label}）",
        "",
        f"> 统计范围：{window.date_from} 至 {window.date_to}（Asia/Shanghai）  ",
        "> 隐私说明：报告不包含邮箱、用户 ID、原始 payload、context、附件或凭据。",
        "",
        "## 一、执行摘要",
        "",
        f"- 反馈总数：**{len(feedbacks)}**",
        f"- 问题反馈：**{len(problems)}**",
        f"- Critical / High：**{len(severe)}**",
        f"- 失败调用：**{failed_calls}**",
        "",
        "## 二、反馈类型",
        "",
        "| 类型 | 数量 |",
        "|---|---:|",
        *_count_rows(type_counter, ("bug", "data_issue", "ux", "docs", "feature", "other", "query_result")),
        "",
        "## 三、问题分布",
        "",
        "### 严重度",
        "",
        "| 严重度 | 数量 |",
        "|---|---:|",
        *_count_rows(severity_counter, ("critical", "high", "medium", "low")),
        "",
        "### 来源",
        "",
        "| 来源 | 数量 |",
        "|---|---:|",
        *_count_rows(source_counter, ("cli", "mcp", "skill", "api")),
        "",
        "### 状态",
        "",
        "| 状态 | 数量 |",
        "|---|---:|",
        *_count_rows(status_counter, ("new", "triaged", "processing", "resolved", "rejected")),
        "",
        "## 四、Critical / High 问题",
        "",
        "| 严重度 | 标题 | 来源 | 状态 | 失败调用 | 反馈 UUID | 创建时间 |",
        "|---|---|---|---|---:|---|---|",
    ]
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
            "## 五、全部问题反馈",
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


def render_wecom_summary(feedbacks: list[dict[str, Any]], window: ReportWindow) -> str:
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


def write_markdown(markdown: str, output_path: Path) -> Path:
    """将 Markdown 日报限制写入项目反馈导出目录。"""
    resolved_path = resolve_output_path(output_path)
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        raise DailyReportError(f"无法写入反馈 Markdown 日报: {resolved_path}") from exc
    return resolved_path


def _print_json(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    """使用 GBK 安全的 ASCII JSON 输出执行结果。"""
    print(json.dumps(payload, ensure_ascii=True), file=stream)


def main(argv: list[str] | None = None) -> int:
    """查询反馈、生成 Markdown 日报并按需推送企业微信。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        window = resolve_report_window(args.date_from, args.date_to)
        api_key = load_api_key()
        client = FeedbackQueryClient(api_key, args.base_url, args.timeout)
        feedbacks = fetch_feedbacks(client, window, per_page=args.per_page)
        markdown = render_markdown(feedbacks, window)
        default_name = f"反馈日报-{window.label.replace(' 至 ', '_')}.md"
        output_path = write_markdown(markdown, args.output or Path(default_name))

        sent = False
        if args.send:
            send_wecom_summary(render_wecom_summary(feedbacks, window))
            sent = True
    except FeedbackQueryError as exc:
        _print_json(exc.payload, stream=sys.stderr)
        return 1
    except DailyReportError as exc:
        _print_json({"code": "DAILY_REPORT_ERROR", "msg": str(exc)}, stream=sys.stderr)
        return 1
    except httpx.HTTPError:
        _print_json({"code": "NETWORK_ERROR", "msg": "反馈查询接口网络请求失败"}, stream=sys.stderr)
        return 1

    _print_json(
        {
            "success": True,
            "output": str(output_path),
            "feedback_count": len(feedbacks),
            "sent": sent,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
