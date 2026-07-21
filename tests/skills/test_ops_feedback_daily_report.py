"""反馈 Markdown 日报和企业微信推送契约测试。"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest


SCRIPT_PATH = Path("opscli/skills/templates/ops-feedback-query/scripts/daily_feedback_report.py")


def _load_script() -> ModuleType:
    """从 Skill 模板加载日报脚本。"""
    spec = importlib.util.spec_from_file_location("ops_feedback_daily_report", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_report_window_uses_previous_shanghai_day():
    """未指定日期时必须统计上海时区的完整昨日。"""
    module = _load_script()
    now = datetime(2026, 7, 21, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    window = module.resolve_report_window(None, None, now=now)

    assert window.date_from == "2026-07-20 00:00:00"
    assert window.date_to == "2026-07-20 23:59:59"
    assert window.label == "2026-07-20"


def test_report_command_paginates_deduplicates_and_writes_safe_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """日报命令应完整翻页、按 UUID 去重并排除敏感字段。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    calls: list[dict] = []
    pages = {
        1: [
            {
                "feedback_uuid": "fb-high",
                "source": "mcp",
                "feedback_type": "bug",
                "severity": "high",
                "title": "查询字段不存在 secret@example.com C:\\Users\\alice\\secret.txt [详情](https://example.com)",
                "status": "new",
                "failed_call_count": 2,
                "user_id": 3100,
                "user_email": "secret@example.com",
                "created_at": "2026-07-20T01:00:00Z",
            },
            {
                "feedback_uuid": "fb-result",
                "source": "cli",
                "feedback_type": "query_result",
                "severity": "low",
                "title": "任务完成",
                "status": "resolved",
                "failed_call_count": 0,
                "created_at": "2026-07-20T02:00:00Z",
            },
        ],
        2: [
            {
                "feedback_uuid": "fb-high",
                "source": "mcp",
                "feedback_type": "bug",
                "severity": "high",
                "title": "查询字段不存在 secret@example.com C:\\Users\\alice\\secret.txt [详情](https://example.com)",
                "status": "new",
                "failed_call_count": 2,
                "created_at": "2026-07-20T01:00:00Z",
            },
            {
                "feedback_uuid": "fb-medium",
                "source": "skill",
                "feedback_type": "data_issue",
                "severity": "medium",
                "title": "库存数据延迟",
                "status": "triaged",
                "failed_call_count": 1,
                "created_at": "2026-07-20T03:00:00Z",
            },
        ],
        3: [],
    }

    monkeypatch.setattr(module, "load_api_key", lambda: "feedback-secret")

    def fake_list(self, params):
        calls.append(dict(params))
        rows = pages[params["page"]]
        return {"code": 200, "msg": "成功", "data": {"list": rows, "total": 4}}

    monkeypatch.setattr(module.FeedbackQueryClient, "list_feedbacks", fake_list)

    exit_code = module.main(
        [
            "--date-from",
            "2026-07-20 00:00:00",
            "--date-to",
            "2026-07-20 23:59:59",
            "--per-page",
            "2",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    report_path = Path(output["output"])
    markdown = report_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert [call["page"] for call in calls] == [1, 2, 3]
    assert all(call["feedback_type"] == "all" for call in calls)
    assert all(call["date_from"] == "2026-07-20 00:00:00" for call in calls)
    assert output["feedback_count"] == 3
    assert output["sent"] is False
    assert "# 反馈日报（2026-07-20）" in markdown
    assert "| high | 1 |" in markdown
    assert "查询字段不存在" in markdown
    assert "secret@example.com" not in markdown
    assert "C:\\Users\\alice\\secret.txt" not in markdown
    assert "[详情](https://example.com)" not in markdown
    assert "2026-07-20 09:00:00" in markdown
    assert "2026-07-20T01:00:00Z" not in markdown
    assert "3100" not in markdown
    assert "feedback-secret" not in markdown


def test_wecom_summary_groups_duplicate_severe_titles():
    """企微重点问题应按严重度和标题聚合，避免重复标题占用展示名额。"""
    module = _load_script()
    window = module.ReportWindow(
        "2026-07-20 00:00:00",
        "2026-07-20 23:59:59",
        "2026-07-20",
    )
    feedbacks = [
        {
            "feedback_uuid": f"asin-{index}",
            "feedback_type": "bug",
            "severity": "high",
            "title": "asin-data basic 批次失败（US）",
        }
        for index in range(5)
    ]
    feedbacks.extend(
        {
            "feedback_uuid": f"other-{index}",
            "feedback_type": "bug",
            "severity": "high",
            "title": f"其他问题 {index}",
        }
        for index in range(1, 7)
    )

    summary = module.render_wecom_summary(feedbacks, window)

    assert summary.count("asin-data basic 批次失败（US）") == 1
    assert "asin-data basic 批次失败（US）（5 条）" in summary
    assert "另有 2 类 Critical / High 问题（共 2 条反馈）" in summary


def test_send_option_calls_opscli_notify_with_markdown_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """显式发送时 Skill 应通过正式 opscli notify 命令发送 Markdown。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    called: dict = {}

    monkeypatch.setattr(module, "load_api_key", lambda: "feedback-secret")
    monkeypatch.setattr(
        module.FeedbackQueryClient,
        "list_feedbacks",
        lambda self, params: {
            "code": 200,
            "msg": "成功",
            "data": {
                "list": [
                    {
                        "feedback_uuid": "fb-critical",
                        "source": "mcp",
                        "feedback_type": "bug",
                        "severity": "critical",
                        "title": "数据结果错误",
                        "status": "new",
                        "failed_call_count": 1,
                        "created_at": "2026-07-20T01:00:00Z",
                    }
                ]
                if params["page"] == 1
                else [],
                "total": 1,
            },
        },
    )

    def fake_run(command, **kwargs):
        called.update(command=command, **kwargs)
        content_path = Path(command[command.index("--content-file") + 1])
        called["content"] = content_path.read_text(encoding="utf-8")
        return module.subprocess.CompletedProcess(command, 0, stdout='{"success": true}', stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    exit_code = module.main(
        [
            "--date-from",
            "2026-07-20 00:00:00",
            "--date-to",
            "2026-07-20 23:59:59",
            "--send",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert called["command"][:3] == ["opscli", "notify", "wecom-markdown"]
    assert "--credentials-file" in called["command"]
    assert "--content-file" in called["command"]
    assert "反馈日报" in called["content"]
    assert "数据结果错误" in called["content"]
    assert "<font" not in called["content"]
    assert len(called["content"].encode("utf-8")) <= 4096
    assert called["timeout"] == 15.0
    assert output["sent"] is True


def test_notify_command_failure_returns_safe_daily_report_error(monkeypatch: pytest.MonkeyPatch):
    """opscli notify 失败时只透传结构化安全消息。"""
    module = _load_script()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: module.subprocess.CompletedProcess(
            args[0],
            1,
            stdout=json.dumps(
                {
                    "success": False,
                    "error": {"message": "企业微信机器人业务执行失败: errcode=93000"},
                }
            ),
            stderr="",
        ),
    )

    with pytest.raises(module.DailyReportError, match="errcode=93000"):
        module.send_wecom_summary("### 日报")
