"""反馈日报本地浏览服务契约测试。"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest
from starlette.testclient import TestClient


SCRIPT_PATH = Path(
    "opscli/skills/templates/ops-feedback-query/scripts/serve_feedback_reports.py"
)


def _load_script() -> ModuleType:
    """从 Skill 模板加载本地报告服务脚本。"""
    spec = importlib.util.spec_from_file_location("ops_feedback_report_server", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_server_lists_only_markdown_sorted_by_mtime(tmp_path: Path):
    """报告列表只展示 Markdown，并按最近更新时间倒序排列。"""
    module = _load_script()
    older = tmp_path / "反馈日报-2026-08-03.md"
    newer = tmp_path / "反馈日报-2026-08-04.md"
    older.write_text("# 旧报告", encoding="utf-8")
    newer.write_text("# 新报告", encoding="utf-8")
    (tmp_path / "private.json").write_text('{"api_key":"secret"}', encoding="utf-8")
    same_second_ns = (newer.stat().st_mtime_ns // 1_000_000_000) * 1_000_000_000
    os.utime(older, ns=(same_second_ns + 100_000_000, same_second_ns + 100_000_000))
    os.utime(newer, ns=(same_second_ns + 900_000_000, same_second_ns + 900_000_000))

    with TestClient(module.create_app(tmp_path)) as client:
        response = client.get("/api/reports")
        page = client.get("/")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["reports"]] == [newer.name, older.name]
    assert "private.json" not in page.text
    assert "反馈日报" in page.text
    assert page.headers["cache-control"] == "no-store"


def test_report_server_renders_safe_markdown_and_raw_content(tmp_path: Path):
    """报告页面应渲染常用 Markdown，并转义潜在脚本内容。"""
    module = _load_script()
    report = tmp_path / "反馈日报-2026-08-04.md"
    markdown = "\n".join(
        [
            "# 反馈日报（2026-08-04）",
            "",
            "- 问题反馈：**2**",
            "",
            "| 模块 | 问题 |",
            "|---|---|",
            "| query | <script>alert(1)</script> |",
        ]
    )
    report.write_text(markdown, encoding="utf-8")

    with TestClient(module.create_app(tmp_path)) as client:
        rendered = client.get(f"/reports/{report.name}")
        raw = client.get(f"/raw/{report.name}")

    assert rendered.status_code == 200
    assert "<h1>反馈日报（2026-08-04）</h1>" in rendered.text
    assert "<table>" in rendered.text
    assert "<strong>2</strong>" in rendered.text
    assert "<script>alert(1)</script>" not in rendered.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered.text
    assert ".report-link[hidden] { display: none; }" in rendered.text
    assert raw.status_code == 200
    assert raw.text == markdown
    assert raw.headers["content-type"].startswith("text/markdown")


def test_report_server_preserves_escaped_pipes_in_table_cells(tmp_path: Path):
    """日报转义的管道符应留在单元格内，不能被误判为列分隔符。"""
    module = _load_script()
    report = tmp_path / "反馈日报-2026-08-04.md"
    report.write_text(
        "| 模块 | 问题 |\n|---|---|\n| query | A \\| B |",
        encoding="utf-8",
    )

    with TestClient(module.create_app(tmp_path)) as client:
        response = client.get(f"/reports/{report.name}")

    assert response.status_code == 200
    assert response.text.count("<td>") == 2
    assert "<td>A | B</td>" in response.text


def test_report_server_renders_mermaid_pie_without_external_script(tmp_path: Path):
    """两张日报分布图应紧凑并排，原始表格默认折叠。"""
    module = _load_script()
    report = tmp_path / "反馈日报-2026-08-04.md"
    report.write_text(
        "\n".join(
            [
                "<!-- feedback-distribution-grid:start -->",
                "<!-- feedback-distribution-panel:start -->",
                "```mermaid",
                "pie showData",
                "    title 反馈类型分布",
                '    "bug" : 2',
                '    "ux" : 1',
                "```",
                "<details>",
                "<summary>查看反馈类型数据表</summary>",
                "| 类型 | 数量 |",
                "|---|---:|",
                "| bug | 2 |",
                "| ux | 1 |",
                "</details>",
                "<!-- feedback-distribution-panel:end -->",
                "<!-- feedback-distribution-panel:start -->",
                "```mermaid",
                "pie showData",
                "    title 问题严重度分布",
                '    "high" : 2',
                '    "medium" : 1',
                "```",
                "<details>",
                "<summary>查看问题严重度数据表</summary>",
                "| 严重度 | 数量 |",
                "|---|---:|",
                "| high | 2 |",
                "| medium | 1 |",
                "</details>",
                "<!-- feedback-distribution-panel:end -->",
                "<!-- feedback-distribution-grid:end -->",
            ]
        ),
        encoding="utf-8",
    )

    with TestClient(module.create_app(tmp_path)) as client:
        response = client.get(f"/reports/{report.name}")

    assert response.status_code == 200
    assert response.text.count('<figure class="mermaid-chart" role="img"') == 2
    assert '<div class="distribution-grid">' in response.text
    assert response.text.count('<section class="distribution-panel">') == 2
    assert '<details class="data-table">' in response.text
    assert "查看反馈类型数据表" in response.text
    assert 'aria-label="问题严重度分布；high 2，66.7%' in response.text
    assert "conic-gradient(" in response.text
    assert "high" in response.text
    assert "66.7%" in response.text
    assert ".distribution-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));" in response.text
    assert "@media (max-width: 1180px)" not in response.text
    assert ".distribution-grid { grid-template-columns: 1fr; }" in response.text
    assert "cdn.jsdelivr.net" not in response.text
    assert "mermaid.min.js" not in response.text


def test_report_server_safely_falls_back_for_unsupported_mermaid(tmp_path: Path):
    """未实现的 Mermaid 类型应显示转义源码，不能执行其中的 HTML。"""
    module = _load_script()
    report = tmp_path / "反馈日报-2026-08-04.md"
    report.write_text(
        "```mermaid\nflowchart LR\nA[<script>alert(1)</script>] --> B\n```",
        encoding="utf-8",
    )

    with TestClient(module.create_app(tmp_path)) as client:
        response = client.get(f"/reports/{report.name}")

    assert response.status_code == 200
    assert '<pre><code class="language-mermaid">' in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_report_server_renders_problem_distribution_tables_side_by_side(tmp_path: Path):
    """问题来源和状态表应组成桌面双列，并在移动端回落单列。"""
    module = _load_script()
    report = tmp_path / "反馈日报-2026-08-04.md"
    report.write_text(
        "\n".join(
            [
                "<!-- feedback-problem-distribution-grid:start -->",
                "<!-- feedback-problem-distribution-panel:start -->",
                "### 来源",
                "| 来源 | 数量 |",
                "|---|---:|",
                "| cli | 8 |",
                "<!-- feedback-problem-distribution-panel:end -->",
                "<!-- feedback-problem-distribution-panel:start -->",
                "### 状态",
                "| 状态 | 数量 |",
                "|---|---:|",
                "| new | 6 |",
                "<!-- feedback-problem-distribution-panel:end -->",
                "<!-- feedback-problem-distribution-grid:end -->",
            ]
        ),
        encoding="utf-8",
    )

    with TestClient(module.create_app(tmp_path)) as client:
        response = client.get(f"/reports/{report.name}")

    assert response.status_code == 200
    assert '<div class="summary-table-grid">' in response.text
    assert response.text.count('<section class="summary-table-panel">') == 2
    assert ".summary-table-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));" in response.text
    assert ".summary-table-grid { grid-template-columns: 1fr; }" in response.text


def test_report_server_accepts_generated_date_range_name(tmp_path: Path):
    """跨日期查询生成的默认日报文件名应正常列出和读取。"""
    module = _load_script()
    report = tmp_path / "反馈日报-2026-08-01_2026-08-04.md"
    report.write_text("# 区间日报", encoding="utf-8")

    with TestClient(module.create_app(tmp_path)) as client:
        listing = client.get("/api/reports")
        rendered = client.get(f"/reports/{report.name}")

    assert [item["name"] for item in listing.json()["reports"]] == [report.name]
    assert rendered.status_code == 200
    assert "<h1>区间日报</h1>" in rendered.text


def test_report_server_accepts_generated_weekly_report_name(tmp_path: Path):
    """周期报告生成器发布的周报应正常列出和读取。"""
    module = _load_script()
    report = tmp_path / "反馈周报-2026-07-27_2026-08-02.md"
    report.write_text("# 反馈周报", encoding="utf-8")

    with TestClient(module.create_app(tmp_path)) as client:
        listing = client.get("/api/reports")
        rendered = client.get(f"/reports/{report.name}")

    assert [item["name"] for item in listing.json()["reports"]] == [report.name]
    assert rendered.status_code == 200
    assert "<h1>反馈周报</h1>" in rendered.text


def test_report_server_home_redirect_has_security_headers(tmp_path: Path):
    """首页重定向也必须携带与内容响应一致的安全头。"""
    module = _load_script()
    (tmp_path / "反馈日报-2026-08-04.md").write_text("# 日报", encoding="utf-8")

    with TestClient(module.create_app(tmp_path)) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_report_server_handles_invalid_utf8_with_security_headers(tmp_path: Path):
    """损坏报告应返回受控错误，不能绕过安全响应头。"""
    module = _load_script()
    report = tmp_path / "反馈日报-2026-08-04-损坏.md"
    report.write_bytes(b"\xff\xfe")

    with TestClient(module.create_app(tmp_path)) as client:
        rendered = client.get(f"/reports/{report.name}")
        raw = client.get(f"/raw/{report.name}")

    for response in (rendered, raw):
        assert response.status_code == 500
        assert response.text == "Report unavailable"
        assert response.headers["cache-control"] == "no-store"
        assert "default-src 'none'" in response.headers["content-security-policy"]


def test_report_server_rejects_non_markdown_and_path_traversal(tmp_path: Path):
    """服务不得读取报告目录外文件或非 Markdown 文件。"""
    module = _load_script()
    (tmp_path / "secret.json").write_text('{"api_key":"secret"}', encoding="utf-8")
    (tmp_path / "credentials.md").write_text("api_key: secret", encoding="utf-8")
    outside = tmp_path.parent / "outside.md"
    outside.write_text("secret", encoding="utf-8")

    with TestClient(module.create_app(tmp_path)) as client:
        non_markdown = client.get("/raw/secret.json")
        non_report_markdown = client.get("/raw/credentials.md")
        traversal = client.get("/raw/%2E%2E/outside.md")

    assert non_markdown.status_code == 404
    assert non_report_markdown.status_code == 404
    assert traversal.status_code == 404


def test_report_server_does_not_list_symlinks_outside_report_dir(tmp_path: Path):
    """目录外 Markdown 的符号链接不得泄露内容或文件元数据。"""
    module = _load_script()
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("external secret", encoding="utf-8")
    linked = report_dir / "反馈日报-2026-08-04.md"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"当前环境不支持创建符号链接: {exc}")

    with TestClient(module.create_app(report_dir)) as client:
        listing = client.get("/api/reports")
        raw = client.get(f"/raw/{linked.name}")

    assert listing.json() == {"reports": []}
    assert linked.name not in listing.text
    assert raw.status_code == 404


def test_report_server_skips_report_that_disappears_during_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """扫描中的单文件异常不能影响其余报告列表和健康检查。"""
    module = _load_script()
    available = tmp_path / "反馈日报-2026-08-04.md"
    unavailable = tmp_path / "反馈日报-2026-08-03.md"
    available.write_text("# 可用", encoding="utf-8")
    unavailable.write_text("# 替换中", encoding="utf-8")
    original_stat = Path.stat

    def flaky_stat(path: Path, *args: object, **kwargs: object):
        if path == unavailable:
            raise FileNotFoundError(path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    with TestClient(module.create_app(tmp_path)) as client:
        listing = client.get("/api/reports")
        health = client.get("/health")

    assert [item["name"] for item in listing.json()["reports"]] == [available.name]
    assert health.json() == {"status": "ok", "report_count": 1}


def test_report_server_health_exposes_no_report_content(tmp_path: Path):
    """健康检查只返回服务状态和报告数量。"""
    module = _load_script()
    (tmp_path / "反馈日报-2026-08-04.md").write_text("private report", encoding="utf-8")

    with TestClient(module.create_app(tmp_path)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "report_count": 1}
    assert "private report" not in response.text


def test_report_server_uses_unoccupied_default_port():
    """默认端口应避开 OpsCLI MCP 使用的 8765。"""
    module = _load_script()

    assert module.DEFAULT_PORT == 8780


def test_report_server_allows_explicit_private_lan_host(tmp_path: Path):
    """显式配置的私有 IPv4 Host 应可访问，其他局域网 Host 仍被拒绝。"""
    module = _load_script()
    allowed_hosts = module._trusted_hosts(module._host("10.6.53.56"))

    with TestClient(
        module.create_app(tmp_path, allowed_hosts=allowed_hosts),
        base_url="http://10.6.53.56",
    ) as client:
        allowed = client.get("/health")
        rejected = client.get("/health", headers={"Host": "10.6.53.57"})

    assert allowed.status_code == 200
    assert rejected.status_code == 400


@pytest.mark.parametrize("host", ["0.0.0.0", "8.8.8.8", "feedback.local"])
def test_report_server_rejects_unsafe_bind_hosts(host: str):
    """服务不得监听所有网卡、公网地址或无法约束的主机名。"""
    module = _load_script()

    with pytest.raises(argparse.ArgumentTypeError):
        module._host(host)
