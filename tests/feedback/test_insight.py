"""feedback insight CLI 行为测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import respx
from typer.testing import CliRunner

from opscli.feedback.commands.cli import app
from opscli.feedback.services.insight import (
    FeedbackInsightManager,
    FeedbackTaxonomyStore,
    InsightModelConfig,
    OpenAICompatibleInsightClient,
    aggregate_feedback_classifications,
)


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
                        "batch_ref": item["batch_ref"],
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
                "--taxonomy-file",
                str(tmp_path / "taxonomy.json"),
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
    model = response["data"]["model"]
    assert len(model.pop("prompt_hash")) == 64
    assert model == {
        "provider": "openai_compatible",
        "model": "feedback-classifier",
        "batch_size": 2,
        "batch_count": 2,
        "prompt_version": "v1",
        "classified_count": 3,
        "reused_count": 0,
        "taxonomy_revision": 1,
    }
    assert route.call_count == 2
    assert model_requests[0]["existing_problem_taxonomy"] == []
    assert [item["batch_ref"] for item in model_requests[0]["feedbacks"]] == ["1", "2"]
    assert model_requests[1]["existing_problem_taxonomy"] == [
        {
            "module": "query",
            "problem_key": "field_mapping_failure",
            "problem_summary": "字段别名映射失败",
        }
    ]

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer model-secret"
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 300.0,
        "write": 10.0,
        "pool": 10.0,
    }
    request_text = request.content.decode("utf-8")
    assert "alice@example.com" not in request_text
    assert "current-1" not in request_text
    assert '"user_id"' not in request_text
    assert "model-secret" not in request_text
    assert "content-secret" not in "".join(
        json.dumps(item, ensure_ascii=False) for item in model_requests
    )


def test_taxonomy_store_reuses_known_signal_without_model_call(tmp_path: Path):
    """跨运行命中同一错误信号时应复用持久分类，避免重复调用模型。"""
    taxonomy_path = tmp_path / "feedback-taxonomy.json"
    store = FeedbackTaxonomyStore(taxonomy_path)
    calls: list[list[dict]] = []

    class RecordingClient:
        config = SimpleNamespace(batch_size=100, model="feedback-classifier")

        def classify(self, feedbacks, existing_problem_taxonomy):
            calls.append(feedbacks)
            return [
                {
                    "feedback_uuid": item["feedback_uuid"],
                    "module": "query",
                    "problem_key": "field_not_found",
                    "problem_category": "字段映射",
                    "problem_summary": "查询字段不存在",
                    "recommended_work": "修正字段映射并增加回归测试",
                    "confidence": 0.96,
                }
                for item in feedbacks
            ]

    first = FeedbackInsightManager(RecordingClient(), taxonomy_store=store).analyze(
        {
            "current_feedbacks": [
                {
                    "feedback_uuid": "first-1",
                    "system_alias": "ops",
                    "mcp_tool_name": "query_simple",
                    "error_message": "REMOTE_ERROR: field 42 not found",
                    "severity": "high",
                }
            ],
            "comparison_feedbacks": [],
        }
    )

    class NoCallClient:
        config = SimpleNamespace(batch_size=100, model="feedback-classifier")

        def classify(self, feedbacks, existing_problem_taxonomy):
            raise AssertionError("持久 taxonomy 命中后不应调用模型")

    second = FeedbackInsightManager(NoCallClient(), taxonomy_store=store).analyze(
        {
            "current_feedbacks": [
                {
                    "feedback_uuid": "second-1",
                    "system_alias": "ops",
                    "mcp_tool_name": "query_simple",
                    "error_message": "REMOTE_ERROR: field 99 not found",
                    "severity": "medium",
                }
            ],
            "comparison_feedbacks": [],
        }
    )

    persisted = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert first["model"]["classified_count"] == 1
    assert first["model"]["reused_count"] == 0
    assert second["model"]["classified_count"] == 0
    assert second["model"]["reused_count"] == 1
    assert second["problems"][0]["problem_key"] == "field_not_found"
    assert persisted["schema_version"] == "1.0"
    assert persisted["revision"] == 1
    assert len(persisted["signal_fingerprints"]) == 1
    assert "REMOTE_ERROR" not in taxonomy_path.read_text(encoding="utf-8")


def test_taxonomy_store_preserves_meaningful_status_and_error_codes(tmp_path: Path):
    """HTTP 状态和结构化错误码不同的信号不得归并。"""
    store = FeedbackTaxonomyStore(tmp_path / "feedback-taxonomy.json")
    feedback = {
        "feedback_uuid": "first",
        "system_alias": "ops",
        "mcp_tool_name": "query_simple",
        "error_code": "REMOTE_HTTP_ERROR",
        "error_message": "HTTP 401 for field 42",
    }
    classification = {
        "feedback_uuid": "first",
        "module": "auth",
        "problem_key": "unauthorized",
        "problem_category": "认证",
        "problem_summary": "请求未授权",
        "recommended_work": "刷新认证后重试",
        "confidence": 0.95,
    }
    state = store.persist(store.load(), [feedback], {"first": classification})

    assert store.match(
        state,
        {**feedback, "feedback_uuid": "same", "error_message": "HTTP 401 for field 99"},
    ) is not None
    assert store.match(
        state,
        {**feedback, "feedback_uuid": "different", "error_message": "HTTP 500 for field 99"},
    ) is None
    assert store.match(
        state,
        {**feedback, "feedback_uuid": "different-code", "error_code": "BUSINESS_2002"},
    ) is None


def test_taxonomy_store_does_not_persist_low_confidence_classification(tmp_path: Path):
    """待复核分类不得固化为后续运行自动命中的 taxonomy。"""
    store = FeedbackTaxonomyStore(tmp_path / "feedback-taxonomy.json")
    feedback = {"feedback_uuid": "low", "error_message": "field 42 not found"}
    classification = {
        "feedback_uuid": "low",
        "module": "query",
        "problem_key": "uncertain_field_error",
        "problem_category": "待复核",
        "problem_summary": "字段问题待复核",
        "recommended_work": "人工确认根因",
        "confidence": 0.6,
    }

    state = store.persist(store.load(), [feedback], {"low": classification})

    assert state["revision"] == 0
    assert state["items"] == []
    assert state["signal_fingerprints"] == {}
    assert not store.path.exists()


def test_taxonomy_store_reloads_latest_state_before_atomic_merge(tmp_path: Path):
    """使用陈旧 state 写入时也必须保留其他运行已落盘的分类。"""
    store = FeedbackTaxonomyStore(tmp_path / "feedback-taxonomy.json")
    stale_state = store.load()

    def persist_one(feedback_uuid: str, error_message: str, problem_key: str, state: dict):
        feedback = {"feedback_uuid": feedback_uuid, "error_message": error_message}
        classification = {
            "feedback_uuid": feedback_uuid,
            "module": "query",
            "problem_key": problem_key,
            "problem_category": "查询",
            "problem_summary": problem_key,
            "recommended_work": "修复并回归",
            "confidence": 0.95,
        }
        return store.persist(state, [feedback], {feedback_uuid: classification})

    persist_one("first", "field 42 not found", "field_not_found", store.load())
    persist_one("second", "request timeout after attempt 2", "request_timeout", stale_state)
    persisted = store.load()

    assert persisted["revision"] == 2
    assert {item["problem_key"] for item in persisted["items"]} == {
        "field_not_found",
        "request_timeout",
    }
    assert len(persisted["signal_fingerprints"]) == 2


def test_repeated_signal_persists_highest_confidence_semantics(tmp_path: Path):
    """重复信号不得借后续高置信度固化首条低置信度语义。"""
    store = FeedbackTaxonomyStore(tmp_path / "feedback-taxonomy.json")

    class MixedConfidenceClient:
        config = SimpleNamespace(batch_size=100, model="feedback-classifier")

        def classify(self, feedbacks, existing_problem_taxonomy):
            return [
                {
                    "feedback_uuid": feedbacks[0]["feedback_uuid"],
                    "module": "unknown",
                    "problem_key": "uncertain_error",
                    "problem_category": "待复核",
                    "problem_summary": "不确定错误",
                    "recommended_work": "人工确认",
                    "confidence": 0.6,
                },
                {
                    "feedback_uuid": feedbacks[1]["feedback_uuid"],
                    "module": "query",
                    "problem_key": "field_not_found",
                    "problem_category": "字段映射",
                    "problem_summary": "查询字段不存在",
                    "recommended_work": "修正字段映射",
                    "confidence": 0.95,
                },
            ]

    FeedbackInsightManager(MixedConfidenceClient(), taxonomy_store=store).analyze(
        {
            "current_feedbacks": [
                {"feedback_uuid": "low", "error_message": "field 42 not found"},
                {"feedback_uuid": "high", "error_message": "field 99 not found"},
            ],
            "comparison_feedbacks": [],
        }
    )
    persisted = store.load()

    assert {item["problem_key"] for item in persisted["items"]} == {"field_not_found"}


def test_taxonomy_store_selects_highest_confidence_for_duplicate_fingerprint(tmp_path: Path):
    """存储层必须统一协调来自 Codex 等调用方的重复指纹分类。"""
    store = FeedbackTaxonomyStore(tmp_path / "feedback-taxonomy.json")
    feedbacks = [
        {"feedback_uuid": "first", "error_message": "field 42 not found"},
        {"feedback_uuid": "second", "error_message": "field 99 not found"},
    ]
    classifications = {
        "first": {
            "feedback_uuid": "first",
            "module": "unknown",
            "problem_key": "wrong_guess",
            "problem_category": "待复核",
            "problem_summary": "错误猜测",
            "recommended_work": "人工确认",
            "confidence": 0.8,
        },
        "second": {
            "feedback_uuid": "second",
            "module": "query",
            "problem_key": "field_not_found",
            "problem_category": "字段映射",
            "problem_summary": "查询字段不存在",
            "recommended_work": "修正字段映射",
            "confidence": 0.95,
        },
    }

    state = store.persist(store.load(), feedbacks, classifications)
    matched = store.match(state, {**feedbacks[0], "feedback_uuid": "later"})

    assert matched is not None
    assert matched["problem_key"] == "field_not_found"
    assert matched["confidence"] == 0.95


def test_taxonomy_store_does_not_downgrade_existing_fingerprint(tmp_path: Path):
    """较晚完成的低置信度运行不得覆盖磁盘中的高置信度分类。"""
    store = FeedbackTaxonomyStore(tmp_path / "feedback-taxonomy.json")
    feedback = {"feedback_uuid": "same", "error_message": "field 42 not found"}

    def classification(problem_key: str, confidence: float) -> dict:
        return {
            "feedback_uuid": "same",
            "module": "query",
            "problem_key": problem_key,
            "problem_category": "字段映射",
            "problem_summary": problem_key,
            "recommended_work": "修正字段映射",
            "confidence": confidence,
        }

    store.persist(
        store.load(),
        [feedback],
        {"same": classification("field_not_found", 0.99)},
    )
    store.persist(
        store.load(),
        [feedback],
        {"same": classification("wrong_guess", 0.8)},
    )
    matched = store.match(store.load(), feedback)

    assert matched is not None
    assert matched["problem_key"] == "field_not_found"
    assert matched["confidence"] == 0.99


def test_aggregate_feedback_classifications_keeps_counts_and_priority_deterministic():
    """Codex 只提供语义分类，次数、趋势和优先级仍由本地规则计算。"""
    payload = {
        "period": {"label": "2026-08-05"},
        "comparison_period": {"label": "2026-08-04"},
        "current_feedbacks": [
            {
                "feedback_uuid": "current-1",
                "severity": "critical",
                "user_key": "user-a",
                "error_message": "field 42 not found",
            }
        ],
        "comparison_feedbacks": [
            {
                "feedback_uuid": "previous-1",
                "severity": "high",
                "user_key": "user-a",
                "error_message": "field 41 not found",
            }
        ],
    }
    classifications = [
        {
            "feedback_uuid": feedback_uuid,
            "module": "query",
            "problem_key": "field_mapping_failed",
            "problem_category": "字段映射",
            "problem_summary": "字段映射失败",
            "recommended_work": "统一字段解析入口并增加回归测试",
            "confidence": 0.95,
        }
        for feedback_uuid in ("current-1", "previous-1")
    ]

    result = aggregate_feedback_classifications(
        payload,
        classifications,
        model_metadata={"provider": "codex_app", "model": "scheduled-codex"},
    )

    assert result["problems"][0]["current_count"] == 1
    assert result["problems"][0]["previous_count"] == 1
    assert result["problems"][0]["priority"] == "P0"
    assert result["model"] == {
        "provider": "codex_app",
        "model": "scheduled-codex",
    }


def test_model_config_defaults_batch_size_to_100(tmp_path: Path):
    """未显式配置时生产批次应默认使用 100 条。"""
    config_path = tmp_path / "model.json"
    config_path.write_text(
        json.dumps(
            {
                "endpoint": "https://llm.example.test/v1/chat/completions",
                "api_key": "model-secret",
                "model": "feedback-classifier",
            }
        ),
        encoding="utf-8",
    )

    assert InsightModelConfig.load(config_path).batch_size == 100


def test_model_request_retries_once_after_transient_http_error():
    """单批网络错误应重试一次并保留本地 UUID 映射。"""
    client = OpenAICompatibleInsightClient(
        InsightModelConfig(
            endpoint="https://llm.example.test/v1/chat/completions",
            api_key="model-secret",
            model="feedback-classifier",
        )
    )
    attempts = 0

    def model_response(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "classifications": [
                                        {
                                            "batch_ref": "1",
                                            "module": "query",
                                            "problem_key": "request_timeout",
                                            "problem_category": "可用性",
                                            "problem_summary": "查询请求超时",
                                            "recommended_work": "检查服务延迟并补充重试",
                                            "confidence": 0.9,
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://llm.example.test/v1/chat/completions").mock(
            side_effect=model_response
        )
        result = client.classify(
            [{"feedback_uuid": "feedback-1", "period": "current", "title": "查询超时"}],
            [],
        )

    assert route.call_count == 2
    assert result[0]["feedback_uuid"] == "feedback-1"


def test_model_request_retries_once_after_truncated_json():
    """大批模型响应截断时应重新请求该批次。"""
    client = OpenAICompatibleInsightClient(
        InsightModelConfig(
            endpoint="https://llm.example.test/v1/chat/completions",
            api_key="model-secret",
            model="feedback-classifier",
        )
    )
    attempts = 0

    def model_response(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        content = "{"
        if attempts == 2:
            content = json.dumps(
                {
                    "classifications": [
                        {
                            "batch_ref": "1",
                            "module": "query",
                            "problem_key": "invalid_response",
                            "problem_category": "可用性",
                            "problem_summary": "模型响应截断",
                            "recommended_work": "重试当前分类批次",
                            "confidence": 0.9,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://llm.example.test/v1/chat/completions").mock(
            side_effect=model_response
        )
        result = client.classify(
            [{"feedback_uuid": "feedback-1", "period": "current", "title": "响应异常"}],
            [],
        )

    assert route.call_count == 2
    assert result[0]["feedback_uuid"] == "feedback-1"


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
