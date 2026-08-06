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


def test_run_feedback_insight_computes_process_timeout_from_batch_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """日报应按反馈数和配置批次计算有上限的子进程超时。"""
    module = _load_script()
    captured: dict[str, object] = {}
    config_path = tmp_path / "model-config.json"
    config_path.write_text(json.dumps({"batch_size": 50}), encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_INSIGHT_CONFIG", config_path)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        return module.subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"success": True, "data": {"problems": []}}),
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.run_feedback_insight(
        {
            "current_feedbacks": [{"feedback_uuid": str(index)} for index in range(101)],
            "comparison_feedbacks": [],
        },
    )

    assert result == {"problems": []}
    assert captured["timeout"] == 1860.0
    assert "--config-file" not in captured["command"]


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
    assert markdown.count("```mermaid") == 2
    assert "title 反馈类型分布" in markdown
    assert '"bug" : 1' in markdown
    assert '"data_issue" : 1' in markdown
    assert '"query_result" : 1' in markdown
    assert "title 问题严重度分布" in markdown
    assert '"high" : 1' in markdown
    assert '"medium" : 1' in markdown
    assert "## 二、分布概览" in markdown
    assert markdown.count("<!-- feedback-distribution-panel:start -->") == 2
    assert markdown.count("<details>") == 2
    assert "<summary>查看反馈类型数据表</summary>" in markdown
    assert "<summary>查看问题严重度数据表</summary>" in markdown
    assert "<!-- feedback-problem-distribution-grid:start -->" in markdown
    assert markdown.count("<!-- feedback-problem-distribution-panel:start -->") == 2
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
    assert "[详细文档查看](https://ops.xenkee.com/dashboard/share/3e2W4spQ)" in summary


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


def test_insight_mode_compares_previous_period_and_renders_module_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """洞察模式应读取上一周期，脱敏详情并渲染模块问题、优先级和建议。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    list_calls: list[dict] = []
    insight_input: dict = {}

    monkeypatch.setattr(module, "load_api_key", lambda: "feedback-secret")

    def fake_list(self, params):
        list_calls.append(dict(params))
        if params["date_from"] == "2026-07-20 00:00:00":
            rows = [
                {
                    "feedback_uuid": "current-1",
                    "source": "mcp",
                    "feedback_type": "bug",
                    "severity": "high",
                    "title": "字段映射失败 alice@example.com",
                    "status": "new",
                    "failed_call_count": 1,
                    "user_id": 101,
                    "user_email": "alice@example.com",
                    "created_at": "2026-07-20T01:00:00Z",
                }
            ]
        else:
            rows = [
                {
                    "feedback_uuid": "previous-1",
                    "source": "cli",
                    "feedback_type": "bug",
                    "severity": "medium",
                    "title": "查询字段不存在",
                    "status": "triaged",
                    "failed_call_count": 1,
                    "user_id": 101,
                    "created_at": "2026-07-19T01:00:00Z",
                }
            ]
        return {"code": 200, "msg": "成功", "data": {"list": rows, "total": 1}}

    def fake_batch_detail(self, feedback_uuids, feedback_type=None):
        return {
            "code": 200,
            "msg": "成功",
            "data": [
                {
                    "feedback_uuid": feedback_uuid,
                    "content": "字段别名无法映射 token=do-not-send Authorization: Bearer bearer-secret",
                    "payload": {"secret": "raw-payload"},
                    "context": {"cwd": "C:\\Users\\alice\\project"},
                    "execution_summary": {
                        "failed_calls": [
                            {
                                "error_message": "REMOTE_BUSINESS_ERROR: field not found",
                                "reason": "字段解析入口不一致",
                                "fix_suggestion": "统一字段解析入口",
                            }
                        ]
                    },
                }
                for feedback_uuid in feedback_uuids
            ],
        }

    def fake_insight(payload, config_path=None):
        insight_input.update(payload)
        assert config_path == Path("model-config.json")
        return {
            "problems": [
                {
                    "module": "query",
                    "problem_summary": "字段别名映射失败",
                    "current_count": 1,
                    "previous_count": 1,
                    "change_percent": 0.0,
                    "affected_users": 1,
                    "priority": "P2",
                    "recommended_work": "统一字段解析入口并补充回归测试",
                }
            ],
            "modules": [
                {
                    "module": "query",
                    "problem_count": 1,
                    "feedback_count": 1,
                    "highest_priority": "P2",
                }
            ],
        }

    monkeypatch.setattr(module.FeedbackQueryClient, "list_feedbacks", fake_list)
    monkeypatch.setattr(module.FeedbackQueryClient, "batch_detail", fake_batch_detail)
    monkeypatch.setattr(module, "run_feedback_insight", fake_insight, raising=False)

    exit_code = module.main(
        [
            "--date-from",
            "2026-07-20 00:00:00",
            "--date-to",
            "2026-07-20 23:59:59",
            "--insight",
            "--insight-config",
            "model-config.json",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    markdown = Path(output["output"]).read_text(encoding="utf-8")

    assert exit_code == 0
    assert [call["date_from"] for call in list_calls] == [
        "2026-07-20 00:00:00",
        "2026-07-19 00:00:00",
    ]
    assert insight_input["period"]["label"] == "2026-07-20"
    assert insight_input["comparison_period"]["label"] == "2026-07-19"
    assert len(insight_input["current_feedbacks"]) == 1
    serialized_input = json.dumps(insight_input, ensure_ascii=False)
    assert "alice@example.com" not in serialized_input
    assert "raw-payload" not in serialized_input
    assert "C:\\Users\\alice" not in serialized_input
    assert "do-not-send" not in serialized_input
    assert "bearer-secret" not in serialized_input
    assert "REMOTE_BUSINESS_ERROR: field not found" in serialized_input
    assert "## 四、模块问题洞察" in markdown
    assert "| query | 字段别名映射失败 | 1 | 1 | 0.0% | P2 | 统一字段解析入口并补充回归测试 |" in markdown
    assert "| high | bug | 字段映射失败" in markdown
    assert "`current-1`" in markdown
    assert output["insight"] is True


def test_wecom_insight_summary_prioritizes_module_count_and_recommended_work():
    """洞察提醒应优先展示高优问题的模块、次数和建议工作。"""
    module = _load_script()
    window = module.ReportWindow(
        "2026-07-20 00:00:00",
        "2026-07-20 23:59:59",
        "2026-07-20",
    )
    insight = {
        "problems": [
            {
                "module": "query",
                "problem_summary": "字段别名映射失败",
                "current_count": 12,
                "previous_count": 4,
                "change_percent": 200.0,
                "priority": "P1",
                "recommended_work": "统一字段解析入口并补充回归测试",
            },
            {
                "module": "docs",
                "problem_summary": "示例缺少参数",
                "current_count": 1,
                "previous_count": 0,
                "change_percent": None,
                "priority": "P3",
                "recommended_work": "补充文档",
            },
            {
                "module": "auth",
                "problem_summary": "疑似认证失败",
                "current_count": 20,
                "previous_count": 2,
                "change_percent": 900.0,
                "priority": "P1",
                "recommended_work": "人工复核分类",
                "needs_review": True,
            },
        ]
    }

    summary = module.render_wecom_summary([], window, insight)

    assert "**P0 / P1 模块提醒**" in summary
    assert "[P1] query：字段别名映射失败（12 次，较上一周期 +200.0%）" in summary
    assert "建议：统一字段解析入口并补充回归测试" in summary
    assert "示例缺少参数" not in summary
    assert "疑似认证失败" not in summary


def test_insight_failure_falls_back_to_base_report_and_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """模型不可用时仍应生成并发送基础日报，不能丢失原有提醒。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    sent: dict[str, str] = {}

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
                        "feedback_uuid": f"feedback-{params['date_from'][:10]}",
                        "feedback_type": "bug",
                        "severity": "high",
                        "source": "mcp",
                        "title": "查询持续失败",
                        "status": "new",
                    }
                ],
                "total": 1,
            },
        },
    )
    monkeypatch.setattr(
        module.FeedbackQueryClient,
        "batch_detail",
        lambda self, feedback_uuids, feedback_type=None: {
            "code": 200,
            "msg": "成功",
            "data": {"list": [{"feedback_uuid": value} for value in feedback_uuids]},
        },
    )
    monkeypatch.setattr(
        module,
        "run_feedback_insight",
        lambda *args, **kwargs: (_ for _ in ()).throw(module.DailyReportError("模型超时")),
    )
    monkeypatch.setattr(
        module,
        "send_wecom_summary",
        lambda content: sent.update(content=content),
    )

    exit_code = module.main(
        [
            "--date-from",
            "2026-07-20 00:00:00",
            "--date-to",
            "2026-07-20 23:59:59",
            "--insight",
            "--send",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    markdown = Path(output["output"]).read_text(encoding="utf-8")

    assert exit_code == 0
    assert output["insight"] is False
    assert output["insight_degraded"] is True
    assert "AI 洞察生成失败，本期已降级为基础日报" in markdown
    assert "查询持续失败" in markdown
    assert "AI 洞察生成失败，本期已降级为基础日报" in sent["content"]
    assert "查询持续失败" in sent["content"]
    assert "模型超时" not in sent["content"]
