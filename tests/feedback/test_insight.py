"""feedback insight CLI 行为测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import respx
from typer.testing import CliRunner

from opscli.feedback.commands.cli import app
from opscli.feedback.services.insight import FeedbackInsightManager


runner = CliRunner()


def test_insight_classifies_and_aggregates_current_and_previous_periods(tmp_path: Path):
    """CLI 应脱敏调用模型，并确定性计算周期次数、趋势和优先级。"""
    input_path = tmp_path / "feedbacks.json"
    config_path = tmp_path / "model.json"
    input_path.write_text(
        json.dumps(
            {
                "period": {"label": "最近7天"},
                "comparison_period": {"label": "前7天"},
                "current_feedbacks": [
                    {
                        "feedback_uuid": "current-1",
                        "severity": "high",
                        "source": "mcp",
                        "user_id": 101,
                        "user_email": "alice@example.com",
                        "title": "query_simple 字段别名映射失败",
                        "error_message": "REMOTE_BUSINESS_ERROR: field 42 not found",
                        "content": "Authorization: Bearer content-secret",
                        "skill_name": "ops-dataset-query",
                    },
                    {
                        "feedback_uuid": "current-2",
                        "severity": "high",
                        "source": "cli",
                        "user_id": 202,
                        "title": "查询字段不存在",
                        "command_name": "opscli query simple",
                    },
                ],
                "comparison_feedbacks": [
                    {
                        "feedback_uuid": "previous-1",
                        "severity": "medium",
                        "source": "mcp",
                        "user_id": 101,
                        "title": "query_simple field not found",
                        "error_message": "REMOTE_BUSINESS_ERROR: field 99 not found",
                        "skill_name": "ops-dataset-query",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps(
            {
                "endpoint": "https://llm.example.test/v1/chat/completions",
                "api_key": "model-secret",
                "model": "feedback-classifier",
                "batch_size": 2,
            }
        ),
        encoding="utf-8",
    )

    with respx.mock(assert_all_called=True) as router:
        model_requests: list[dict] = []

        def model_response(request: httpx.Request) -> httpx.Response:
            request_payload = json.loads(request.content)
            user_payload = json.loads(request_payload["messages"][1]["content"])
            model_requests.append(user_payload)
            model_output = {
                "classifications": [
                    {
                        "feedback_uuid": item["feedback_uuid"],
                        "module": "auth" if item["period"] == "comparison" else "query",
                        "problem_key": (
                            "field_mapping_failure_previous"
                            if item["period"] == "comparison"
                            else "field_mapping_failure"
                        ),
                        "problem_category": "code_bug",
                        "problem_summary": "字段别名映射失败",
                        "recommended_work": "统一字段解析入口并补充回归测试",
                        "confidence": 0.92,
                    }
                        for item in user_payload["feedbacks"]
                ]
            }
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps(model_output, ensure_ascii=False)}}
                    ]
                },
            )

        route = router.post("https://llm.example.test/v1/chat/completions").mock(
            side_effect=model_response
        )
        result = runner.invoke(
            app,
            [
                "insight",
                "--input-file",
                str(input_path),
                "--config-file",
                str(config_path),
            ],
        )

    assert result.exit_code == 0, result.output
    response = json.loads(result.output)
    problem = response["data"]["problems"][0]
    assert problem == {
        "module": "query",
        "problem_key": "field_mapping_failure",
        "problem_category": "code_bug",
        "problem_summary": "字段别名映射失败",
        "current_count": 2,
        "previous_count": 1,
        "change_percent": 100.0,
        "affected_users": 2,
        "severity": "high",
        "priority": "P1",
        "priority_score": 74,
        "recommended_work": "统一字段解析入口并补充回归测试",
        "confidence": 0.92,
        "needs_review": False,
        "sample_feedback_uuids": ["current-1", "current-2"],
    }
    assert response["data"]["modules"] == [
        {"module": "query", "problem_count": 1, "feedback_count": 2, "highest_priority": "P1"}
    ]
    assert response["data"]["model"] == {
        "provider": "openai_compatible",
        "model": "feedback-classifier",
    }
    assert route.call_count == 2
    assert model_requests[0]["existing_problem_taxonomy"] == []
    assert model_requests[1]["existing_problem_taxonomy"] == [
        {
            "module": "query",
            "problem_key": "field_mapping_failure",
            "problem_summary": "字段别名映射失败",
        }
    ]

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer model-secret"
    request_text = request.content.decode("utf-8")
    assert "alice@example.com" not in request_text
    assert '"user_id"' not in request_text
    assert "model-secret" not in request_text
    assert "content-secret" not in "".join(
        json.dumps(item, ensure_ascii=False) for item in model_requests
    )


def test_insight_rejects_plain_http_for_non_loopback_model_endpoint(tmp_path: Path):
    """模型密钥和反馈不得通过非本机明文 HTTP 发送。"""
    input_path = tmp_path / "feedbacks.json"
    config_path = tmp_path / "model.json"
    input_path.write_text(
        json.dumps(
            {
                "current_feedbacks": [
                    {"feedback_uuid": "current-1", "title": "查询失败"}
                ],
                "comparison_feedbacks": [],
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps(
            {
                "endpoint": "http://llm.example.test/v1/chat/completions",
                "api_key": "model-secret",
                "model": "feedback-classifier",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["insight", "--input-file", str(input_path), "--config-file", str(config_path)],
    )

    assert result.exit_code == 1
    response = json.loads(result.output)
    assert response["error"]["code"] == "INSIGHT_CONFIG_ERROR"
    assert "HTTPS" in response["error"]["message"]
    assert "model-secret" not in result.output


def test_insight_does_not_force_merge_generic_titles_without_error_signal():
    """相同通用标题但不同模型问题键不能被确定性规则误合并。"""

    class FakeClient:
        config = SimpleNamespace(model="fake-model", batch_size=50)

        def classify(self, feedbacks, existing_problem_taxonomy):
            return [
                {
                    "feedback_uuid": item["feedback_uuid"],
                    "module": "query",
                    "problem_key": "permission_denied" if index == 0 else "request_timeout",
                    "problem_category": "permission" if index == 0 else "availability",
                    "problem_summary": "权限不足" if index == 0 else "请求超时",
                    "recommended_work": "检查权限" if index == 0 else "检查服务延迟",
                    "confidence": 0.9,
                }
                for index, item in enumerate(feedbacks)
            ]

    result = FeedbackInsightManager(FakeClient()).analyze(
        {
            "current_feedbacks": [
                {"feedback_uuid": "feedback-1", "title": "查询失败", "severity": "medium"},
                {"feedback_uuid": "feedback-2", "title": "查询失败", "severity": "medium"},
            ],
            "comparison_feedbacks": [],
        }
    )

    assert [item["problem_key"] for item in result["problems"]] == [
        "permission_denied",
        "request_timeout",
    ]
