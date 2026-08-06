"""在本机提供反馈 Markdown 日报的只读浏览服务。"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route


LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8780
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
TABLE_SEPARATOR_PATTERN = re.compile(r"^\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$")
INLINE_PATTERN = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*)")
# 只解析日报生成器输出的受控 Mermaid pie 数据行，避免浏览器执行任意图表语法。
MERMAID_PIE_ITEM_PATTERN = re.compile(r'^"([^"\r\n]{1,80})"\s*:\s*(\d+)$')
# 固定高对比度色板使本地图表无需外部主题或脚本即可稳定展示。
CHART_COLORS = (
    "#0f766e",
    "#d97706",
    "#b91c1c",
    "#2563eb",
    "#4d7c0f",
    "#7c3aed",
    "#be185d",
    "#64748b",
)
# 仅识别日报生成器写入的布局标记；其他 HTML 仍按普通文本转义。
DISTRIBUTION_GRID_START = "<!-- feedback-distribution-grid:start -->"
DISTRIBUTION_GRID_END = "<!-- feedback-distribution-grid:end -->"
DISTRIBUTION_PANEL_START = "<!-- feedback-distribution-panel:start -->"
DISTRIBUTION_PANEL_END = "<!-- feedback-distribution-panel:end -->"
# 以下成对标记只描述问题分布双列表格，避免与上方图表布局协议混用。
PROBLEM_DISTRIBUTION_GRID_START = "<!-- feedback-problem-distribution-grid:start -->"
PROBLEM_DISTRIBUTION_GRID_END = "<!-- feedback-problem-distribution-grid:end -->"
PROBLEM_DISTRIBUTION_PANEL_START = "<!-- feedback-problem-distribution-panel:start -->"
PROBLEM_DISTRIBUTION_PANEL_END = "<!-- feedback-problem-distribution-panel:end -->"
DETAILS_SUMMARY_PATTERN = re.compile(r"^<summary>([^<\r\n]{1,80})</summary>$")
MARKDOWN_LAYOUT_TAGS = {
    DISTRIBUTION_GRID_START: '<div class="distribution-grid">',
    DISTRIBUTION_GRID_END: "</div>",
    DISTRIBUTION_PANEL_START: '<section class="distribution-panel">',
    DISTRIBUTION_PANEL_END: "</section>",
    PROBLEM_DISTRIBUTION_GRID_START: '<div class="summary-table-grid">',
    PROBLEM_DISTRIBUTION_GRID_END: "</div>",
    PROBLEM_DISTRIBUTION_PANEL_START: '<section class="summary-table-panel">',
    PROBLEM_DISTRIBUTION_PANEL_END: "</section>",
    "<details>": '<details class="data-table">',
    "</details>": "</details>",
}
DAILY_REPORT_NAME_PATTERN = re.compile(
    r"^反馈日报-\d{4}-\d{2}-\d{2}(?:_\d{4}-\d{2}-\d{2})?(?:-[^/\\]+)?\.md$",
    re.IGNORECASE,
)
MONTHLY_REPORT_NAME_PATTERN = re.compile(
    r"^\d{4}年\d{1,2}月反馈复盘分析报告\.md$",
    re.IGNORECASE,
)


class ReportServerError(Exception):
    """表示报告目录无法定位或服务参数不合法。"""


def resolve_reports_dir(start_dir: Path | None = None) -> Path:
    """定位项目根目录下的反馈报告目录。

    Args:
        start_dir: 查找 Git 项目根的起始目录。

    Returns:
        项目内 `output/feedback-query` 的绝对路径。

    Raises:
        ReportServerError: 无法找到 Git 项目根目录。
    """
    current = (start_dir or Path.cwd()).resolve()
    project_root = next(
        (directory for directory in (current, *current.parents) if (directory / ".git").exists()),
        None,
    )
    if project_root is None:
        raise ReportServerError("无法定位 Git 项目根目录，不能启动反馈日报服务")
    return (project_root / "output" / "feedback-query").resolve()


def list_reports(report_dir: Path) -> list[dict[str, Any]]:
    """返回目录中的 Markdown 报告元数据，最近更新的报告优先。"""
    try:
        root = report_dir.resolve(strict=True)
        if not root.is_dir():
            return []
        paths = list(root.iterdir())
    except (OSError, RuntimeError):
        return []

    result: list[tuple[int, dict[str, Any]]] = []
    for path in paths:
        if not _is_report_name(path.name) or path.is_symlink():
            continue
        resolved = _resolve_report_path(root, path.name)
        if resolved is None:
            continue
        try:
            file_stat = resolved.stat()
        except OSError:
            continue
        modified = datetime.fromtimestamp(file_stat.st_mtime).astimezone()
        result.append(
            (
                file_stat.st_mtime_ns,
                {
                    "name": path.name,
                    "size": file_stat.st_size,
                    "size_label": _format_size(file_stat.st_size),
                    "modified_at": modified.isoformat(timespec="seconds"),
                    "modified_label": modified.strftime("%Y-%m-%d %H:%M"),
                    "report_url": f"/reports/{quote(path.name)}",
                    "raw_url": f"/raw/{quote(path.name)}",
                },
            )
        )
    result.sort(key=lambda item: item[0], reverse=True)
    return [report for _, report in result]


def _format_size(size: int) -> str:
    """把字节数转换为紧凑的人类可读文本。"""
    if size < 1024:
        return f"{size} B"
    return f"{size / 1024:.1f} KB"


def _is_report_name(name: str) -> bool:
    """判断文件名是否属于反馈日报或月度复盘报告。"""
    return bool(
        DAILY_REPORT_NAME_PATTERN.fullmatch(name)
        or MONTHLY_REPORT_NAME_PATTERN.fullmatch(name)
    )


def _resolve_report_path(report_dir: Path, name: str) -> Path | None:
    """解析并限制单个 Markdown 报告路径。"""
    if not name or Path(name).name != name or not _is_report_name(name):
        return None
    try:
        root = report_dir.resolve(strict=True)
        source = root / name
        if source.is_symlink():
            return None
        candidate = source.resolve(strict=True)
        if candidate.parent != root or not candidate.is_file():
            return None
    except (OSError, RuntimeError):
        return None
    return candidate


def _read_report(path: Path) -> str | None:
    """读取 UTF-8 报告，文件替换或编码损坏时返回不可用。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _render_inline(value: str) -> str:
    """安全渲染日报使用的行内代码和粗体语法。"""
    normalized = value.replace("\\_", "_").replace("\\|", "|")
    fragments: list[str] = []
    cursor = 0
    for match in INLINE_PATTERN.finditer(normalized):
        fragments.append(html.escape(normalized[cursor : match.start()], quote=False))
        token = match.group(0)
        if token.startswith("`"):
            fragments.append(f"<code>{html.escape(token[1:-1], quote=False)}</code>")
        else:
            fragments.append(f"<strong>{html.escape(token[2:-2], quote=False)}</strong>")
        cursor = match.end()
    fragments.append(html.escape(normalized[cursor:], quote=False))
    return "".join(fragments)


def _table_cells(line: str) -> list[str]:
    """拆分 Markdown 表格行。"""
    content = line.strip()
    if content.startswith("|"):
        content = content[1:]
    if content.endswith("|"):
        content = content[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", content)]


def _render_code_block(code: str, language: str = "") -> str:
    """安全渲染代码块，并保留语言类名供兼容查看。"""
    language_class = ""
    if re.fullmatch(r"[a-z0-9_-]{1,30}", language):
        language_class = f' class="language-{language}"'
    return f"<pre><code{language_class}>{html.escape(code, quote=False)}</code></pre>"


def _render_mermaid_pie(code: str) -> str | None:
    """把日报使用的 Mermaid pie 子集渲染为无脚本本地图表。"""
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    if not lines or lines[0].lower() != "pie showdata":
        return None
    title = "数据分布"
    items: list[tuple[str, int]] = []
    for line in lines[1:]:
        if line.lower().startswith("title "):
            title = line[6:].strip()[:80] or title
            continue
        match = MERMAID_PIE_ITEM_PATTERN.fullmatch(line)
        # 超出色板或不符合受控语法时整图回退源码，避免颜色歧义和部分渲染。
        if match is None or len(items) >= len(CHART_COLORS):
            return None
        items.append((match.group(1), int(match.group(2))))
    total = sum(value for _, value in items)
    if not items or total <= 0:
        return None

    stops: list[str] = []
    legend: list[str] = []
    accessible_parts: list[str] = []
    start = 0.0
    for index, (label, value) in enumerate(items):
        percentage = value / total * 100
        end = start + percentage
        color = CHART_COLORS[index]
        stops.append(f"{color} {start:.2f}% {end:.2f}%")
        escaped_label = html.escape(label)
        legend.append(
            '<li><span class="legend-swatch" '
            f'style="--legend-color: {color}"></span><span>{escaped_label}</span>'
            f"<strong>{value} · {percentage:.1f}%</strong></li>"
        )
        accessible_parts.append(f"{label} {value}，{percentage:.1f}%")
        start = end
    escaped_title = html.escape(title)
    aria_label = html.escape(f"{title}；" + "；".join(accessible_parts), quote=True)
    gradient = ", ".join(stops)
    return (
        f'<figure class="mermaid-chart" role="img" aria-label="{aria_label}">'
        f"<figcaption>{escaped_title}</figcaption>"
        '<div class="chart-layout">'
        f'<div class="pie-visual" style="--pie: conic-gradient({gradient})"></div>'
        f'<ul class="chart-legend">{"".join(legend)}</ul>'
        "</div></figure>"
    )


def render_markdown(markdown: str) -> str:
    """把日报使用的 Markdown 子集安全渲染为 HTML。"""
    lines = markdown.splitlines()
    rendered: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        if stripped in MARKDOWN_LAYOUT_TAGS:
            rendered.append(MARKDOWN_LAYOUT_TAGS[stripped])
            index += 1
            continue

        details_summary = DETAILS_SUMMARY_PATTERN.fullmatch(stripped)
        if details_summary:
            rendered.append(f"<summary>{_render_inline(details_summary.group(1))}</summary>")
            index += 1
            continue

        if stripped.startswith("```"):
            language = stripped[3:].strip().lower()
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1
            code = chr(10).join(code_lines)
            chart = _render_mermaid_pie(code) if language == "mermaid" else None
            rendered.append(chart or _render_code_block(code, language))
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            rendered.append(f"<h{level}>{_render_inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if (
            stripped.startswith("|")
            and index + 1 < len(lines)
            and TABLE_SEPARATOR_PATTERN.fullmatch(lines[index + 1].strip())
        ):
            headers = _table_cells(stripped)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_table_cells(lines[index]))
                index += 1
            header_html = "".join(f"<th>{_render_inline(cell)}</th>" for cell in headers)
            row_html = "".join(
                "<tr>" + "".join(f"<td>{_render_inline(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            rendered.append(
                f'<div class="table-wrap"><table><thead><tr>{header_html}</tr></thead>'
                f"<tbody>{row_html}</tbody></table></div>"
            )
            continue

        if stripped.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(lines[index].strip()[2:])
                index += 1
            rendered.append("<ul>" + "".join(f"<li>{_render_inline(item)}</li>" for item in items) + "</ul>")
            continue

        if stripped.startswith(">"):
            rendered.append(f"<blockquote>{_render_inline(stripped[1:].strip())}</blockquote>")
            index += 1
            continue

        rendered.append(f"<p>{_render_inline(stripped)}</p>")
        index += 1
    return "\n".join(rendered)


def _page(title: str, body: str, reports: list[dict[str, Any]], selected: str | None) -> str:
    """生成带报告导航的完整 HTML 页面。"""
    escaped_title = html.escape(title)
    report_links = []
    for report in reports:
        active = " active" if report["name"] == selected else ""
        current = ' aria-current="page"' if active else ""
        report_links.append(
            f'<a class="report-link{active}" href="{report["report_url"]}" '
            f'data-name="{html.escape(report["name"].lower(), quote=True)}"{current}>'
            f'<span class="report-name">{html.escape(report["name"])}</span>'
            f'<span class="report-meta">{report["modified_label"]} · {report["size_label"]}</span>'
            "</a>"
        )
    navigation = "".join(report_links) or '<p class="empty-nav">暂无报告</p>'
    raw_action = ""
    if selected:
        raw_action = (
            f'<a class="raw-link" href="/raw/{quote(selected)}" target="_blank" '
            'rel="noopener">查看原文</a>'
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title} · Feedback Insight</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #182026;
      --muted: #66727a;
      --line: #dce1e4;
      --soft: #f4f6f7;
      --paper: #ffffff;
      --accent: #0f766e;
      --accent-soft: #e7f4f1;
      --warm: #a45c1a;
    }}
    * {{ box-sizing: border-box; letter-spacing: 0; }}
    html {{ background: var(--paper); }}
    body {{ margin: 0; color: var(--ink); background: var(--paper); font: 14px/1.65 "Segoe UI", "Microsoft YaHei", sans-serif; }}
    a {{ color: inherit; }}
    .topbar {{ height: 58px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 24px; border-bottom: 1px solid var(--line); background: var(--paper); }}
    .brand {{ display: flex; align-items: baseline; gap: 10px; min-width: 0; }}
    .brand strong {{ font-size: 17px; }}
    .brand span {{ color: var(--muted); font-size: 12px; }}
    .raw-link {{ flex: 0 0 auto; color: var(--accent); font-weight: 600; text-decoration: none; }}
    .layout {{ min-height: calc(100vh - 58px); display: grid; grid-template-columns: minmax(240px, 300px) minmax(0, 1fr); }}
    .sidebar {{ position: sticky; top: 58px; height: calc(100vh - 58px); overflow: auto; border-right: 1px solid var(--line); background: var(--soft); padding: 18px 12px; }}
    .search {{ width: 100%; height: 38px; margin-bottom: 14px; padding: 0 11px; border: 1px solid #c8d0d4; border-radius: 6px; background: var(--paper); color: var(--ink); outline: none; }}
    .search:focus {{ border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }}
    .report-link {{ display: block; padding: 10px 11px; border-left: 3px solid transparent; text-decoration: none; }}
    .report-link[hidden] {{ display: none; }}
    .report-link:hover {{ background: #e9edef; }}
    .report-link.active {{ border-left-color: var(--accent); background: var(--accent-soft); }}
    .report-name {{ display: block; overflow-wrap: anywhere; font-weight: 600; }}
    .report-meta {{ display: block; margin-top: 2px; color: var(--muted); font-size: 12px; }}
    .empty-nav {{ padding: 8px 11px; color: var(--muted); }}
    main {{ min-width: 0; padding: 34px clamp(20px, 5vw, 72px) 72px; }}
    article {{ max-width: 1280px; margin: 0 auto; }}
    h1 {{ margin: 0 0 10px; font-size: 28px; line-height: 1.25; }}
    h2 {{ margin: 34px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line); font-size: 20px; line-height: 1.35; }}
    h3 {{ margin: 26px 0 10px; font-size: 16px; }}
    h4, h5, h6 {{ margin: 20px 0 8px; font-size: 14px; }}
    p {{ margin: 8px 0; }}
    ul {{ margin: 8px 0 16px; padding-left: 22px; }}
    li {{ margin: 4px 0; }}
    blockquote {{ margin: 12px 0 20px; padding: 10px 14px; border-left: 3px solid var(--warm); background: #fff8ef; color: #4f4a44; }}
    code {{ padding: 1px 4px; border-radius: 3px; background: #edf0f2; font-family: Consolas, monospace; font-size: 12px; }}
    pre {{ overflow: auto; padding: 14px; border: 1px solid var(--line); border-radius: 6px; background: #f7f8f9; }}
    pre code {{ padding: 0; background: transparent; }}
    .mermaid-chart {{ margin: 12px 0 22px; padding: 16px; border: 1px solid var(--line); border-radius: 6px; background: #fafbfb; }}
    .mermaid-chart figcaption {{ margin-bottom: 14px; font-size: 15px; font-weight: 700; }}
    .chart-layout {{ display: grid; grid-template-columns: minmax(150px, 210px) minmax(220px, 1fr); align-items: center; gap: 24px; }}
    .pie-visual {{ position: relative; width: 100%; aspect-ratio: 1; border-radius: 50%; background: var(--pie); }}
    .pie-visual::after {{ position: absolute; inset: 28%; border-radius: 50%; background: #fafbfb; content: ""; }}
    .chart-legend {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px 18px; margin: 0; padding: 0; list-style: none; }}
    .chart-legend li {{ display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; align-items: center; gap: 8px; min-width: 0; }}
    .chart-legend span:not(.legend-swatch) {{ overflow-wrap: anywhere; }}
    .chart-legend strong {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .legend-swatch {{ width: 10px; height: 10px; border-radius: 2px; background: var(--legend-color); }}
    .distribution-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; margin: 12px 0 28px; }}
    .distribution-panel {{ min-width: 0; padding: 0 18px 18px; border: 1px solid var(--line); border-radius: 6px; background: #fafbfb; }}
    .distribution-panel h3 {{ margin: 16px 0 4px; }}
    .distribution-panel .mermaid-chart {{ margin: 0; padding: 12px 0 8px; border: 0; background: transparent; }}
    .distribution-panel .mermaid-chart figcaption {{ display: none; }}
    .distribution-panel .chart-layout {{ grid-template-columns: 1fr; gap: 14px; }}
    .distribution-panel .pie-visual {{ max-width: 150px; margin: 0 auto; }}
    .distribution-panel .chart-legend {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .data-table {{ margin-top: 10px; border-top: 1px solid var(--line); }}
    .data-table summary {{ padding: 10px 0 0; color: var(--accent); cursor: pointer; font-size: 12px; font-weight: 600; }}
    .data-table .table-wrap {{ margin: 10px 0 0; }}
    .summary-table-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; margin: 12px 0 28px; }}
    .summary-table-panel {{ min-width: 0; }}
    .summary-table-panel h3 {{ margin: 0 0 8px; }}
    .summary-table-panel .table-wrap {{ margin: 0; }}
    .table-wrap {{ width: 100%; overflow-x: auto; margin: 10px 0 22px; border: 1px solid var(--line); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--paper); font-size: 13px; }}
    th, td {{ min-width: 90px; padding: 9px 11px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; overflow-wrap: anywhere; }}
    th {{ position: sticky; top: 0; background: #eef2f3; font-weight: 700; }}
    tbody tr:hover {{ background: #f8faf9; }}
    .empty-state {{ padding: 70px 0; color: var(--muted); text-align: center; }}
    @media (max-width: 780px) {{
      .topbar {{ height: auto; min-height: 58px; padding: 12px 16px; }}
      .brand span {{ display: none; }}
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; height: auto; max-height: 240px; overflow: auto; border-right: 0; border-bottom: 1px solid var(--line); }}
      main {{ padding: 24px 16px 56px; }}
      h1 {{ font-size: 23px; }}
      .distribution-grid {{ grid-template-columns: 1fr; }}
      .summary-table-grid {{ grid-template-columns: 1fr; }}
      .chart-layout {{ grid-template-columns: 1fr; }}
      .distribution-panel {{ padding: 0 14px 14px; }}
      .distribution-panel .chart-layout {{ grid-template-columns: 1fr; }}
      .pie-visual {{ max-width: 190px; margin: 0 auto; }}
      .chart-legend {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand"><strong>Feedback Insight</strong><span>{len(reports)} 份本地报告</span></div>
    {raw_action}
  </header>
  <div class="layout">
    <aside class="sidebar">
      <input class="search" id="report-search" type="search" placeholder="筛选报告" aria-label="筛选报告">
      <nav id="report-list">{navigation}</nav>
    </aside>
    <main><article>{body}</article></main>
  </div>
  <script>
    const input = document.getElementById('report-search');
    input.addEventListener('input', () => {{
      const term = input.value.trim().toLowerCase();
      document.querySelectorAll('.report-link').forEach((item) => {{
        item.hidden = !item.dataset.name.includes(term);
      }});
    }});
  </script>
</body>
</html>"""


def create_app(report_dir: Path | None = None) -> Starlette:
    """创建只读反馈报告 ASGI 应用。

    Args:
        report_dir: 测试或调用方指定的报告目录，默认定位项目输出目录。

    Returns:
        可由 Uvicorn 或测试客户端运行的 Starlette 应用。
    """
    root = (report_dir or resolve_reports_dir()).resolve()

    async def home(_: Request) -> Response:
        reports = list_reports(root)
        if reports:
            return RedirectResponse(
                reports[0]["report_url"],
                status_code=302,
                headers=SECURITY_HEADERS,
            )
        body = '<div class="empty-state">暂无反馈日报</div>'
        return HTMLResponse(_page("本地报告", body, reports, None), headers=SECURITY_HEADERS)

    async def reports_api(_: Request) -> Response:
        return JSONResponse({"reports": list_reports(root)}, headers=SECURITY_HEADERS)

    async def health(_: Request) -> Response:
        return JSONResponse(
            {"status": "ok", "report_count": len(list_reports(root))},
            headers=SECURITY_HEADERS,
        )

    async def report_page(request: Request) -> Response:
        name = request.path_params["name"]
        path = _resolve_report_path(root, name)
        if path is None:
            return Response("Not Found", status_code=404, headers=SECURITY_HEADERS)
        markdown = _read_report(path)
        if markdown is None:
            return Response("Report unavailable", status_code=500, headers=SECURITY_HEADERS)
        body = render_markdown(markdown)
        return HTMLResponse(
            _page(path.stem, body, list_reports(root), path.name),
            headers=SECURITY_HEADERS,
        )

    async def raw_report(request: Request) -> Response:
        name = request.path_params["name"]
        path = _resolve_report_path(root, name)
        if path is None:
            return Response("Not Found", status_code=404, headers=SECURITY_HEADERS)
        content = _read_report(path)
        if content is None:
            return Response("Report unavailable", status_code=500, headers=SECURITY_HEADERS)
        return Response(
            content,
            media_type="text/markdown",
            headers={**SECURITY_HEADERS, "Content-Disposition": f'inline; filename="{quote(path.name)}"'},
        )

    app = Starlette(
        debug=False,
        routes=[
            Route("/", home, name="home"),
            Route("/api/reports", reports_api, name="reports_api"),
            Route("/health", health, name="health"),
            Route("/reports/{name:path}", report_page, name="report"),
            Route("/raw/{name:path}", raw_report, name="raw_report"),
        ],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )
    return app


def _port(value: str) -> int:
    """校验本地服务端口。"""
    parsed = int(value)
    if parsed < 1 or parsed > 65535:
        raise argparse.ArgumentTypeError("端口必须在 1 到 65535 之间")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """启动仅监听本机回环地址的反馈日报服务。"""
    parser = argparse.ArgumentParser(description="启动反馈日报本地浏览服务")
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT, help="监听端口，默认 8780")
    args = parser.parse_args(argv)
    try:
        report_dir = resolve_reports_dir()
    except ReportServerError as exc:
        print(json.dumps({"success": False, "message": str(exc)}, ensure_ascii=True))
        return 1
    print(
        json.dumps(
            {
                "success": True,
                "url": f"http://{LOCAL_HOST}:{args.port}",
                "report_dir": str(report_dir),
            },
            ensure_ascii=True,
        )
    )
    uvicorn.run(
        create_app(report_dir),
        host=LOCAL_HOST,
        port=args.port,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
