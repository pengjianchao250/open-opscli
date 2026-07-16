import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from opscli.mcp import ops_credentials
from opscli.mcp.tools import seller_sprite as seller_sprite_tools
from opscli.mcp.server import _quota_wrap


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _route_credential_test_seams(monkeypatch):
    """让既有工具测试替身经统一凭证模块生效，且不读取真实本机凭证。"""
    original_auth_pair = ops_credentials._get_auth_pair
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_auth_pair",
        original_auth_pair,
        raising=False,
    )
    monkeypatch.setattr(
        ops_credentials,
        "_get_auth_pair",
        lambda system, session_id, jwt: seller_sprite_tools._get_auth_pair(
            system,
            session_id,
            jwt,
        ),
    )
    monkeypatch.setattr(
        ops_credentials,
        "_get_authenticated_user_email",
        lambda: seller_sprite_tools._get_current_mcp_user_email(),
    )


class DummyManager:
    def scenarios(self):
        return [{"scenario_id": "keyword-reverse", "title": "关键词反查"}]


class DummyScheduler:
    last_request = None
    last_mcp_user_email = None
    last_enqueue_kwargs = None
    enqueue_calls = 0

    async def enqueue(self, request, **kwargs):
        self.__class__.last_request = request
        self.__class__.last_mcp_user_email = kwargs.get("mcp_user_email")
        self.__class__.last_enqueue_kwargs = kwargs
        self.__class__.enqueue_calls += 1
        return {
            "job_id": request.job_id or "job-async-1",
            "scenario": request.scenario,
            "site": request.site,
            "period": request.period,
            "state": "queued",
            "stage": "queued",
            "position": 1,
        }

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "state": "queued",
            "stage": "queued",
            "position": 2,
            "row_count": 1,
            "export": {"path": f"/tmp/{job_id}.xlsx", "filename": f"{job_id}.xlsx"},
        }


class EnqueueOnlyScheduler:
    async def enqueue(self, request, **kwargs):
        return {
            "job_id": request.job_id or "job-queued-1",
            "state": "queued",
            "stage": "queued",
            "position": 1,
            "created_at": "2026-07-10T10:00:00+08:00",
        }

    def job_status(self, job_id):
        raise AssertionError("seller_sprite_run 入队后不应隐藏轮询")


class FailingScheduler:
    async def enqueue(self, request, **kwargs):
        raise RuntimeError("enqueue boom")


class NoNormalizeScheduler:
    last_request = None
    last_mcp_user_email = None
    enqueue_calls = 0

    async def enqueue(self, request, **kwargs):
        self.__class__.last_request = request
        self.__class__.last_mcp_user_email = kwargs.get("mcp_user_email")
        self.__class__.enqueue_calls += 1
        return {
            "job_id": request.job_id,
            "scenario": request.scenario,
            "site": request.site,
            "period": request.period,
            "state": "queued",
            "stage": "queued",
            "position": 1,
        }


def _make_store(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    return SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")


def _patch_job_owner(
    monkeypatch,
    *,
    current_user: str | None = "mcp-user@example.com",
    owner_user: str | None = "mcp-user@example.com",
    scenario: str = "keyword-reverse",
):
    """为普通任务状态测试注入当前用户和 MCP 调用记录。"""
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: current_user)
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: SimpleNamespace(
            get_mcp_run=lambda job_id: {
                "job_id": job_id,
                "user_email": owner_user,
                "scenario": scenario,
            }
        ),
    )


class StatusWaitScheduler:
    """记录有界状态等待期间的调度器生命周期调用。"""

    def __init__(self, states):
        self.states = list(states)
        self.status_calls = 0
        self.start_calls = 0
        self.close_calls = 0

    async def start(self):
        self.start_calls += 1

    async def close(self):
        self.close_calls += 1

    def job_status(self, job_id):
        index = min(self.status_calls, len(self.states) - 1)
        self.status_calls += 1
        return {
            "job_id": job_id,
            "state": self.states[index],
            "stage": self.states[index],
        }


class FakeWaitClock:
    """通过假的 monotonic 与 sleep 记录等待边界，避免测试真实等待。"""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class BatchOwnerStore:
    """记录批量状态预授权顺序，并模拟缺记录与任务生命周期方法。"""

    def __init__(self, records):
        self.records = dict(records)
        self.get_calls = []
        self.fail_calls = 0
        self.cancel_calls = 0

    def get_mcp_run(self, job_id):
        self.get_calls.append(job_id)
        if job_id not in self.records:
            raise ValueError(f"MCP 调用记录不存在：{job_id}")
        return self.records[job_id]

    def fail_task(self, **kwargs):
        self.fail_calls += 1

    def cancel_task(self, **kwargs):
        self.cancel_calls += 1


class BatchStatusWaitScheduler:
    """按任务分别推进状态快照，记录批量等待期间的 scheduler 生命周期。"""

    def __init__(self, states_by_job):
        self.states_by_job = {
            job_id: list(states)
            for job_id, states in states_by_job.items()
        }
        self.status_counts = {job_id: 0 for job_id in self.states_by_job}
        self.status_calls = []
        self.start_calls = 0
        self.close_calls = 0

    async def start(self):
        self.start_calls += 1

    async def close(self):
        self.close_calls += 1

    def job_status(self, job_id):
        states = self.states_by_job[job_id]
        index = min(self.status_counts[job_id], len(states) - 1)
        self.status_counts[job_id] += 1
        self.status_calls.append(job_id)
        return {
            "job_id": job_id,
            "state": states[index],
            "stage": states[index],
        }


def _batch_owner_record(job_id, *, user_email="mcp-user@example.com", scenario="keyword-reverse"):
    """构造普通批量状态测试使用的 MCP 调用记录。"""
    return {
        "job_id": job_id,
        "user_email": user_email,
        "scenario": scenario,
    }


def _patch_batch_owner_store(monkeypatch, store, *, current_user="mcp-user@example.com"):
    """注入批量状态测试所需的当前用户与队列仓储。"""
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: current_user)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)


def test_seller_sprite_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda: DummyManager())

    result = _run(seller_sprite_tools.seller_sprite_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "keyword-reverse"


def test_seller_sprite_spec_must_read_includes_scenario_param_manual():
    result = _run(seller_sprite_tools.seller_sprite_spec_must_read())

    assert result["success"] is True
    assert "# 卖家精灵场景参数手册" in result["data"]["spec"]
    assert "seller_sprite_listing_analysis_submit" in result["data"]["spec"]
    assert "`seller_sprite_run` 生产入口会明确拒绝 `listing-analysis`" in result["data"]["spec"]


def test_seller_sprite_skill_and_formal_docs_require_durable_bounded_tracking():
    repo_root = Path(__file__).resolve().parents[2]
    skill_dir = repo_root / "opscli" / "skills" / "templates" / "ops-seller-sprite"
    documents = {
        "SKILL.md": (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
        "SKILL_MCP.md": (skill_dir / "SKILL_MCP.md").read_text(encoding="utf-8"),
        "卖家精灵MCP接口直连接入说明.md": (
            repo_root / "docs" / "spec" / "卖家精灵MCP接口直连接入说明.md"
        ).read_text(encoding="utf-8"),
        "卖家精灵MCP异步任务化优化方案.md": (
            repo_root / "docs" / "plans" / "卖家精灵MCP异步任务化优化方案.md"
        ).read_text(encoding="utf-8"),
    }

    required_contracts = [
        "立即持久化入队",
        "`seller_sprite_job_status(job_id, wait_seconds=30)`",
        "`seller_sprite_jobs_status(job_ids, wait_seconds=30)`",
        "3–4 个",
        "90–120 秒",
        "同一轮",
        "`queued`、`running`、`ready=false`",
        "等待窗口到期",
        "保留全部未完成 `job_id`",
        "完整 pending 集合",
        "`继续` / `查结果`",
        "不得重新提交",
        "不得重新消耗额度",
        "`run` 消耗额度；状态和导出不消耗额度",
        "submit/status/result",
        "Listing Analysis",
        "不得传入 `seller_sprite_jobs_status`",
    ]
    for name, content in documents.items():
        for contract in required_contracts:
            assert contract in content, f"{name} 缺少契约：{contract}"
        assert "`seller_sprite_run` 生产入口会明确拒绝 `listing-analysis`" in content, (
            f"{name} 未记录 generic Listing Analysis 的生产拒绝契约"
        )
        assert re.search(
            r"Listing Analysis(?: 的)? `job_id` 不得传入 `seller_sprite_jobs_status`",
            content,
        ), f"{name} 未明确 Listing Analysis 仅排除普通批量状态"

    mcp_skill = documents["SKILL_MCP.md"]
    formal_spec = documents["卖家精灵MCP接口直连接入说明.md"]
    for content in (mcp_skill, formal_spec):
        assert "顶层 `success=true` 只表示工具请求成功" in content
        assert "不会取消、标记失败或重新入队" in content

    assert '`seller_sprite_job_status(job_id="job-1", wait_seconds=30)`' in formal_spec
    assert (
        '`seller_sprite_jobs_status(job_ids=["job-a", "job-b"], wait_seconds=30)`'
        in formal_spec
    )
    json_examples = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", formal_spec, re.S)]
    queued_examples = []
    running_examples = []
    for example in json_examples:
        data = example.get("data", {})
        snapshots = data.get("jobs", [data])
        queued_examples.extend(job for job in snapshots if job.get("state") == "queued")
        running_examples.extend(job for job in snapshots if job.get("state") == "running")

    assert queued_examples
    assert all(
        isinstance(job.get("position"), int) and job["position"] >= 1
        for job in queued_examples
    )
    assert running_examples
    assert all("position" in job and job["position"] is None for job in running_examples)

    combined_docs = "\n".join(documents.values())
    assert "不得传入普通单任务或批量状态工具" not in combined_docs
    assert "包括 `seller_sprite_job_status` 和 `seller_sprite_jobs_status`" not in combined_docs
    assert "不得传入普通单任务状态工具" not in combined_docs
    assert "不得传入 `seller_sprite_jobs_status`" in combined_docs
    assert "不要使用普通单任务状态工具" not in combined_docs
    assert "当前注册场景" in formal_spec
    manual_checklist = formal_spec.split("## 手动验证清单", 1)[1].split("## 2026-05-22 本地验证记录", 1)[0]
    assert "返回 4 个场景" not in manual_checklist
    assert "4 个场景分别" not in manual_checklist
    assert "seller_sprite_job_status(job_id, wait_seconds=30)" in manual_checklist
    assert "seller_sprite_jobs_status(job_ids, wait_seconds=30)" in manual_checklist

    historical_plan = documents["卖家精灵MCP异步任务化优化方案.md"]
    assert "当前契约" in historical_plan
    assert "历史诊断" in historical_plan
    assert "已被当前契约取代" in historical_plan
    assert "立即持久化入队" in historical_plan
    assert "pending 不是失败" in historical_plan
    assert "不得重新提交" in historical_plan
    assert "完整 pending 集合" in historical_plan

    obsolete_contracts = [
        "`queued` 阶段继续等",
        "进入 `running` 后最多再等 8 分钟",
        "只有任务进入 `running` 后超过 8 分钟",
        "自动轮询 60 到 90 秒",
        "自动切换为异步任务",
        "内部自动决定同步或异步",
        "如果后端判断需要异步",
        "每 5 到 10 秒一次",
        "60 到 90 秒内完成",
        "复用对话上下文中的 `job_id` 查询状态",
        "长任务优先使用异步模式",
        "queue_duration",
        "running_duration",
    ]
    for name, content in documents.items():
        for obsolete in obsolete_contracts:
            assert obsolete not in content, f"{name} 仍含旧契约：{obsolete}"


def test_seller_sprite_identity_proxy_uses_shared_authenticated_email_resolver(monkeypatch):
    """SellerSprite 创建、所有权和额度共用的代理必须委托共享 resolver。"""
    from opscli.mcp.tools import helpers

    monkeypatch.setattr(
        helpers,
        "_get_authenticated_user_email",
        lambda: "resolved@example.com",
    )

    assert seller_sprite_tools._get_current_mcp_user_email() == "resolved@example.com"


def test_seller_sprite_quota_status_returns_snapshot(monkeypatch):
    class FakeLimiter:
        def quota_snapshot(self, tool_name, identity):
            assert tool_name == "seller_sprite_run"
            assert identity == "email:mcp-user@example.com"
            return {
                "service": "seller_sprite",
                "limit": 5,
                "used": 2,
                "remaining": 3,
                "failures": 0,
                "reset_at": "2026-06-24T00:00:00+08:00",
            }

    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr("opscli.mcp.tools.seller_sprite.get_quota_limiter", lambda: FakeLimiter())

    result = _run(seller_sprite_tools.seller_sprite_quota_status())

    assert result["success"] is True
    assert result["data"]["remaining"] == 3


def test_seller_sprite_quota_status_returns_error_when_user_email_missing(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: None)

    result = _run(seller_sprite_tools.seller_sprite_quota_status())

    assert result["success"] is False
    assert "邮箱" in result["error"]["message"]


def test_seller_sprite_run_rejects_listing_analysis_before_any_side_effect(monkeypatch):
    """通用入口必须在认证、构造请求和队列访问前拒绝 Listing Analysis。"""
    reject_side_effect = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Listing Analysis 通用入口拒绝前不应触发副作用")
    )
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", reject_side_effect)
    monkeypatch.setattr(seller_sprite_tools, "_build_request", reject_side_effect)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", reject_side_effect)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", reject_side_effect)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario=" listing-analysis ",
            params={"asin": "B0TEST123"},
        )
    )

    assert result["success"] is False
    assert "seller_sprite_listing_analysis_submit" in result["error"]["message"]


def test_seller_sprite_run_accepts_params_json_string(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params='{"asin":"B07YRMT36L"}',
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-async-1"
    assert result["data"]["state"] == "queued"
    assert result["data"]["position"] == 1
    assert DummyScheduler.last_request.params == {"asin": "B07YRMT36L"}
    assert DummyScheduler.last_request.page_size == 100
    assert DummyScheduler.last_request.export_format == "json"
    assert DummyScheduler.last_request.mode == "browser-route"
    assert DummyScheduler.enqueue_calls == 1
    assert DummyScheduler.last_mcp_user_email == "mcp-user@example.com"


def test_listing_analysis_submit_rejects_whitespace_owner_before_enqueue(monkeypatch):
    """专用 submit 不得把空白邮箱降级成 queue-only 入队。"""
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda *args: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "   ")
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_scheduler",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("空白 owner 不得获取 scheduler")),
    )

    result = _run(
        seller_sprite_tools.seller_sprite_listing_analysis_submit(
            asin="B0TEST123",
        )
    )

    assert result["success"] is False
    assert "邮箱缺失" in result["error"]["message"]


def test_listing_analysis_submit_enqueues_without_run_wait(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "listing-job-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_listing_analysis_submit(
            asin="b0test123",
            station="global",
            site="US",
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "listing-job-1"
    assert result["data"]["state"] == "queued"
    assert DummyScheduler.last_request.scenario == "listing-analysis"
    assert DummyScheduler.last_request.params == {"asin": "B0TEST123", "station": "GLOBAL"}
    assert DummyScheduler.last_request.mode == "browser-route"
    assert DummyScheduler.enqueue_calls == 1



def test_listing_analysis_status_returns_local_queue_state(monkeypatch):
    class LocalOnlyScheduler:
        def job_status(self, job_id):
            return {"job_id": job_id, "scenario": "listing-analysis", "state": "running", "stage": "running"}

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "mcp-user@example.com"}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: LocalOnlyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["state"] == "running"
    assert result["data"]["ready"] is False



def test_listing_analysis_history_status_uses_history_get_endpoint(monkeypatch):
    class FakeManager:
        def __init__(self, **kwargs):
            self.account_provider = type("AccountProvider", (), {"get_default": lambda self: object()})()

    class FakeClient:
        calls = []

        def __init__(self, *, account):
            self.account = account

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def has_login_cookies(self):
            return True

        async def login(self):
            raise AssertionError("cached browser cookies should be used for history status")

        async def get_json(self, url, params, *, referer=None):
            self.__class__.calls.append({"url": url, "params": params, "referer": referer})
            return {
                "code": "OK",
                "success": True,
                "data": {
                    "items": [
                        {
                            "taskId": "f1f297d499620bd41177fa5455ff8001",
                            "taskStatus": "COMPLETED",
                            "tabTitle": "US(B0FQJR6RTS) | 全景分析 | Listing数据深度解析报告",
                            "module": "LA",
                        }
                    ]
                },
            }

        async def post_json(self, *args, **kwargs):
            raise AssertionError("task/history must follow the page GET request shape")

    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", FakeManager)
    monkeypatch.setattr("opscli.seller_sprite.api.client.SellerSpriteApiClient", FakeClient)

    result = _run(
        seller_sprite_tools._fetch_listing_analysis_history_status(
            asin="B0FQJR6RTS",
            session_id="sid",
            jwt="jwt",
        )
    )

    assert result["task_id"] == "f1f297d499620bd41177fa5455ff8001"
    assert FakeClient.calls == [
        {
            "url": "/v3/api/ai-analysis/task/history",
            "params": {"page": 1, "pageSize": 20, "keywords": "", "modules": ""},
            "referer": "https://www.sellersprite.com/v3/ai-history?module=LA",
        }
    ]


def test_listing_analysis_status_relogs_and_retries_expired_history_session(monkeypatch):
    from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError

    class SubmittedScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"asin": "B08Z6X4NK3", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "params_json": {"asin": "B08Z6X4NK3", "station": "GLOBAL"},
            }

    class FakeManager:
        def __init__(self, **kwargs):
            self.account_provider = type(
                "AccountProvider",
                (),
                {"get_default": lambda self: object()},
            )()

    class ExpiredThenReadyClient:
        history_calls = 0
        login_calls = 0

        def __init__(self, *, account):
            self.account = account

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def has_login_cookies(self):
            return True

        async def login(self):
            self.__class__.login_calls += 1
            return {"logged_in": True}

        async def get_json(self, url, params, *, referer=None):
            self.__class__.history_calls += 1
            if self.__class__.history_calls == 1:
                raise SellerSpriteApiError(
                    "卖家精灵登录态失效",
                    api_code="ERR_GLOBAL_SESSION_EXPIRED",
                )
            return {
                "code": "OK",
                "data": {
                    "items": [
                        {
                            "taskId": "task-ready-after-relogin",
                            "taskStatus": "COMPLETED",
                            "tabTitle": "US(B08Z6X4NK3) | 全景分析 | Listing数据深度解析报告",
                            "module": "LA",
                        }
                    ]
                },
            }

    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", FakeManager)
    monkeypatch.setattr(
        "opscli.seller_sprite.api.client.SellerSpriteApiClient",
        ExpiredThenReadyClient,
    )
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_scheduler",
        lambda **kwargs: SubmittedScheduler(),
    )
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_current_mcp_user_email",
        lambda: "mcp-user@example.com",
    )
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-expired"))

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["task_id"] == "task-ready-after-relogin"
    assert ExpiredThenReadyClient.login_calls == 1
    assert ExpiredThenReadyClient.history_calls == 2



def test_listing_analysis_status_reads_history_by_asin(monkeypatch):
    class SubmittedScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "stage": "finished",
                "data": [{"taskId": "task-1", "asin": "B0FQJR6RTS", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "params_json": {"asin": "B0FQJR6RTS", "station": "GLOBAL"},
            }

    async def fake_history_status(*, asin, session_id, jwt):
        assert asin == "B0FQJR6RTS"
        assert session_id == "sid"
        assert jwt == "jwt"
        return {
            "task_id": "86ead00315941d0810d9b564e2986013",
            "ready": True,
            "failed": False,
            "remote": {
                "code": "OK",
                "data": {
                    "items": [
                        {
                            "taskId": "86ead00315941d0810d9b564e2986013",
                            "taskStatus": "COMPLETED",
                            "tabTitle": "US(B0FQJR6RTS) | 文案质量分析 | Listing数据深度解析报告",
                            "module": "LA",
                        }
                    ]
                },
            },
        }

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: SubmittedScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_history_status", fake_history_status, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["task_id"] == "86ead00315941d0810d9b564e2986013"



def test_listing_analysis_status_rejects_other_user_job(monkeypatch):
    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "owner@example.com"}

    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "intruder@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-1"))

    assert result["success"] is False
    assert "无权读取" in result["error"]["message"]


def test_listing_analysis_status_rejects_non_listing_analysis_job(monkeypatch):
    _patch_job_owner(monkeypatch, scenario="keyword-reverse")

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("job-regular"))

    assert result["success"] is False
    assert "不是 Listing Analysis" in result["error"]["message"]


def test_listing_analysis_result_reports_not_ready(monkeypatch):
    class PendingScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "mcp-user@example.com"}

    async def fake_remote_status(*args, **kwargs):
        return {"task_id": "task-1", "ready": False, "remote": {"data": {"taskStatus": "RUNNING"}}}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: PendingScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_remote_status)
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert result["data"]["task_id"] == "task-1"



def test_listing_analysis_result_prefers_history_task_id_over_submit_placeholder(monkeypatch):
    class ReadyTaskScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "asin": "B0FQJR6RTS", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "params_json": {"asin": "B0FQJR6RTS", "station": "GLOBAL"},
            }

    async def fake_history_status(*, asin, session_id, jwt):
        assert asin == "B0FQJR6RTS"
        return {
            "task_id": "f1f297d499620bd41177fa5455ff8001",
            "ready": True,
            "failed": False,
            "remote_status": "COMPLETED",
            "history_item": {
                "taskId": "f1f297d499620bd41177fa5455ff8001",
                "taskStatus": "COMPLETED",
                "tabTitle": "US(B0FQJR6RTS) | 全景分析 | Listing数据深度解析报告",
                "module": "LA",
            },
            "remote": {"code": "OK", "success": True},
        }

    async def fake_report_result(*, task_id, session_id, jwt):
        assert task_id == "f1f297d499620bd41177fa5455ff8001"
        return {"task_id": task_id, "ready": False, "failed": False, "analyzing": True, "remote": None}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: ReadyTaskScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_history_status", fake_history_status)
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_report_result)
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["task_id"] == "f1f297d499620bd41177fa5455ff8001"



def test_listing_analysis_result_uses_report_page_when_history_task_ready(monkeypatch):
    class ReadyTaskScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "asin": "B0FQJR6RTS", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "params_json": {"asin": "B0FQJR6RTS", "station": "GLOBAL"},
            }

    async def fail_old_remote_status(*args, **kwargs):
        raise AssertionError("result must open ai-report through browser-route instead of old task API")

    async def fake_history_status(*, asin, session_id, jwt):
        assert asin == "B0FQJR6RTS"
        return {"task_id": "task-1", "ready": True, "failed": False, "remote_status": "COMPLETED", "remote": {}}

    async def fake_report_result(*, task_id, session_id, jwt):
        assert task_id == "task-1"
        assert session_id == "sid"
        assert jwt == "jwt"
        return {"task_id": "task-1", "ready": False, "failed": False, "analyzing": True, "remote": None}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: ReadyTaskScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_remote_status", fail_old_remote_status)
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_history_status", fake_history_status)
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_report_result, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert result["data"]["analyzing"] is True
    assert result["data"]["task_id"] == "task-1"



def test_listing_analysis_result_marks_remote_failure(monkeypatch):
    class FailedScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "contentReady": False}],
            }

    class RecordingStore:
        def __init__(self):
            self.fail_task_call = None
            self.finish_mcp_run_failed_call = None

        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "mcp-user@example.com"}

        def fail_task(self, **kwargs):
            self.fail_task_call = kwargs

        def finish_mcp_run_failed(self, job_id, error_payload):
            self.finish_mcp_run_failed_call = {"job_id": job_id, "error_payload": error_payload}

    async def fake_remote_status(*args, **kwargs):
        return {
            "task_id": "task-1",
            "ready": False,
            "failed": True,
            "remote": {"data": {"taskStatus": "FAILED", "message": "AI task failed"}},
        }

    store = RecordingStore()
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: FailedScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_remote_status)
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["failed"] is True
    assert result["data"]["state"] == "failed"
    assert store.fail_task_call["job_id"] == "listing-job-1"
    assert store.finish_mcp_run_failed_call["error_payload"]["code"] == "SELLER_SPRITE_LISTING_ANALYSIS_FAILED"



def test_listing_analysis_result_persists_ready_remote_payload(monkeypatch, tmp_path):
    root_dir = tmp_path / "listing-job-1"

    class ReadyScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "site": "US",
                "period": "30d",
                "state": "succeeded",
                "root_dir": str(root_dir),
                "data": [{"taskId": "task-1", "contentReady": False}],
            }

    class RecordingStore:
        def __init__(self):
            self.finish_task_call = None
            self.finish_mcp_run_success_call = None

        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "mcp-user@example.com"}

        def finish_task(self, **kwargs):
            self.finish_task_call = kwargs

        def finish_mcp_run_success(self, job_id, row_count, export_payload):
            self.finish_mcp_run_success_call = {
                "job_id": job_id,
                "row_count": row_count,
                "export_payload": export_payload,
            }

    async def fake_remote_status(*args, **kwargs):
        return {
            "task_id": "task-1",
            "ready": True,
            "failed": False,
            "remote": {
                "code": "OK",
                "data": {
                    "taskId": "task-1",
                    "taskStatus": "COMPLETED",
                    "content": "Listing 分析正文",
                    "htmlContent": "<p>Listing 分析正文</p>",
                    "completedTime": "2026-07-09 12:00:00",
                },
            },
        }

    store = RecordingStore()
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: ReadyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_remote_status)
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["row_count"] == 1
    assert result["data"]["data"][0]["content"] == "Listing 分析正文"
    assert result["data"]["export"]["format"] == "json"
    assert Path(result["data"]["result_path"]).exists()
    assert Path(result["data"]["raw_path"]).exists()
    assert Path(result["data"]["export"]["path"]).exists()
    assert store.finish_task_call["job_id"] == "listing-job-1"
    assert store.finish_task_call["row_count"] == 1
    assert store.finish_mcp_run_success_call["export_payload"]["format"] == "json"



def test_seller_sprite_start_returns_queued_job(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_current_mcp_user_email",
        lambda: "mcp-user@example.com",
    )
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_start(
            scenario="product-research",
            site="US",
            period="30d",
            params={"nodeIdPaths": ["1055398:1063306:1063312:10824421"]},
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-async-1"
    assert result["data"]["state"] == "queued"
    assert DummyScheduler.enqueue_calls == 1
    assert DummyScheduler.last_request.scenario == "product-research"
    assert DummyScheduler.last_request.params == {
        "nodeIdPaths": ["1055398:1063306:1063312:10824421"]
    }
    assert DummyScheduler.last_request.export_format == "json"
    assert DummyScheduler.last_request.mode == "browser-route"


def test_seller_sprite_run_always_enqueues(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="product-research",
            site="US",
            period="30d",
            params={"nodeIdPaths": ["1055398:1063306:1063312:10824421"]},
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-async-1"
    assert result["data"]["state"] == "queued"
    assert DummyScheduler.enqueue_calls == 1
    assert DummyScheduler.last_mcp_user_email == "mcp-user@example.com"


def test_seller_sprite_run_returns_complete_queued_status_without_polling(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    scheduler = EnqueueOnlyScheduler()
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-queued-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params={"asin": "B07YRMT36L"},
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"] == {
        "job_id": "job-queued-1",
        "state": "queued",
        "stage": "queued",
        "position": 1,
        "created_at": "2026-07-10T10:00:00+08:00",
    }


def test_seller_sprite_export_returns_owned_export_info(monkeypatch):
    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())

    result = _run(seller_sprite_tools.seller_sprite_export("job-1"))

    assert result["success"] is True
    assert result["data"]["path"] == "/tmp/job-1.xlsx"
    assert result["data"]["url"].startswith("file://")


def test_seller_sprite_export_does_not_mutate_scheduler_export_mapping(monkeypatch):
    export = {"path": "/tmp/job-1.xlsx", "filename": "job-1.xlsx"}

    class SharedExportScheduler:
        def job_status(self, job_id):
            return {"job_id": job_id, "export": export}

    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_scheduler",
        lambda **kwargs: SharedExportScheduler(),
    )

    result = _run(seller_sprite_tools.seller_sprite_export("job-1"))

    assert result["success"] is True
    assert result["data"]["url"].startswith("file://")
    assert export == {"path": "/tmp/job-1.xlsx", "filename": "job-1.xlsx"}


def test_seller_sprite_export_rejects_other_user_job_before_reading_scheduler(monkeypatch):
    _patch_job_owner(
        monkeypatch,
        current_user="intruder@example.com",
        owner_user="owner@example.com",
    )
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_scheduler",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("越权导出不应读取任务状态")),
    )

    result = _run(seller_sprite_tools.seller_sprite_export("job-private"))

    assert result["success"] is False
    assert "无权读取" in result["error"]["message"]


def test_seller_sprite_job_status_reads_owned_scheduler(monkeypatch):
    _patch_job_owner(monkeypatch, current_user=" MCP-USER@example.com ")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2"))

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-2"
    assert result["data"]["state"] == "queued"
    assert result["data"]["position"] == 2


def test_seller_sprite_job_status_rejects_other_user_job(monkeypatch):
    _patch_job_owner(
        monkeypatch,
        current_user="intruder@example.com",
        owner_user="owner@example.com",
    )

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-private"))

    assert result["success"] is False
    assert "无权读取" in result["error"]["message"]


@pytest.mark.parametrize("current_user", [None, "   "])
def test_seller_sprite_job_status_rejects_missing_current_user(monkeypatch, current_user):
    _patch_job_owner(monkeypatch, current_user=current_user)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2"))

    assert result["success"] is False
    assert "邮箱缺失" in result["error"]["message"]


@pytest.mark.parametrize("owner_user", [None, "   "])
def test_seller_sprite_job_status_rejects_missing_owner_user(monkeypatch, owner_user):
    _patch_job_owner(monkeypatch, owner_user=owner_user)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2"))

    assert result["success"] is False
    assert "任务所有者邮箱缺失" in result["error"]["message"]


def test_seller_sprite_job_status_rejects_missing_mcp_run_record(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: SimpleNamespace(
            get_mcp_run=lambda job_id: (_ for _ in ()).throw(
                ValueError(f"MCP 调用记录不存在：{job_id}")
            )
        ),
    )

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-missing"))

    assert result["success"] is False
    assert "调用记录不存在" in result["error"]["message"]


def test_seller_sprite_status_waiter_explicitly_requires_complete_collection_preauthorization():
    waiter = seller_sprite_tools._wait_for_preauthorized_seller_sprite_job_statuses

    assert "完整集合" in waiter.__doc__
    assert "预授权" in waiter.__doc__
    assert "不执行授权" in waiter.__doc__


def test_seller_sprite_job_status_wait_zero_reads_once_without_start(monkeypatch):
    scheduler = StatusWaitScheduler(["queued"])
    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=0))

    assert result["success"] is True
    assert result["data"]["state"] == "queued"
    assert scheduler.status_calls == 1
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


@pytest.mark.parametrize("state", ["succeeded", "failed"])
def test_seller_sprite_job_status_initial_terminal_does_not_start_scheduler(monkeypatch, state):
    scheduler = StatusWaitScheduler([state])
    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=30))

    assert result["success"] is True
    assert result["data"]["state"] == state
    assert scheduler.status_calls == 1
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_job_status_positive_wait_observes_terminal_without_starting_scheduler(
    monkeypatch,
):
    class ObserverOnlyScheduler(StatusWaitScheduler):
        async def start(self):
            raise AssertionError("状态观察者不得启动 scheduler")

    scheduler = ObserverOnlyScheduler(["queued", "succeeded"])
    clock = FakeWaitClock()
    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep, raising=False)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=30))

    assert result["success"] is True
    assert result["data"]["state"] == "succeeded"
    assert clock.sleeps == [5]
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_job_status_wait_expires_after_30_seconds(monkeypatch):
    scheduler = StatusWaitScheduler(["queued"])
    clock = FakeWaitClock()
    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep, raising=False)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=30))

    assert result["success"] is True
    assert result["data"]["state"] == "queued"
    assert clock.sleeps == [5, 5, 5, 5, 5, 5]
    assert scheduler.status_calls == 7
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_job_status_uses_remaining_time_for_last_sleep(monkeypatch):
    scheduler = StatusWaitScheduler(["queued"])
    clock = FakeWaitClock()
    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep, raising=False)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=12))

    assert result["success"] is True
    assert result["data"]["state"] == "queued"
    assert clock.sleeps == [5, 5, 2]
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_job_status_oversleep_returns_last_snapshot_without_expired_read(monkeypatch):
    scheduler = StatusWaitScheduler(["queued", "succeeded"])
    clock = FakeWaitClock()

    async def oversleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds + 1

    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", oversleep, raising=False)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=5))

    assert result["success"] is True
    assert result["data"]["state"] == "queued"
    assert clock.sleeps == [5]
    assert scheduler.status_calls == 1
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_job_status_clamps_wait_above_30_seconds(monkeypatch):
    scheduler = StatusWaitScheduler(["running"])
    clock = FakeWaitClock()
    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep, raising=False)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=99))

    assert result["success"] is True
    assert result["data"]["state"] == "running"
    assert clock.sleeps == [5, 5, 5, 5, 5, 5]
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_job_status_clamps_negative_wait_to_zero(monkeypatch):
    scheduler = StatusWaitScheduler(["queued"])
    clock = FakeWaitClock()
    _patch_job_owner(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep, raising=False)

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=-8))

    assert result["success"] is True
    assert result["data"]["state"] == "queued"
    assert clock.sleeps == []
    assert scheduler.status_calls == 1
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_job_status_cancellation_propagates_without_stopping_task(monkeypatch):
    scheduler = StatusWaitScheduler(["queued"])

    class LifecycleStore:
        def __init__(self):
            self.fail_calls = 0
            self.cancel_calls = 0

        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "scenario": "keyword-reverse",
            }

        def fail_task(self, **kwargs):
            self.fail_calls += 1

        def cancel_task(self, **kwargs):
            self.cancel_calls += 1

    async def cancel_sleep(seconds):
        raise asyncio.CancelledError()

    store = LifecycleStore()
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", lambda: 0.0, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", cancel_sleep, raising=False)

    with pytest.raises(asyncio.CancelledError):
        _run(seller_sprite_tools.seller_sprite_job_status("job-2", wait_seconds=30))

    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0
    assert store.fail_calls == 0
    assert store.cancel_calls == 0


def test_seller_sprite_jobs_status_rejects_empty_job_ids(monkeypatch):
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: (_ for _ in ()).throw(AssertionError("空列表不应读取任务记录")),
    )

    result = _run(seller_sprite_tools.seller_sprite_jobs_status([]))

    assert result["success"] is False
    assert result["data"] is None
    assert "至少提供 1 个" in result["error"]["message"]


def test_seller_sprite_jobs_status_rejects_more_than_50_job_ids(monkeypatch):
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: (_ for _ in ()).throw(AssertionError("超过上限不应读取任务记录")),
    )

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(
            [f"job-{index}" for index in range(51)]
        )
    )

    assert result["success"] is False
    assert result["data"] is None
    assert "最多提供 50 个" in result["error"]["message"]


def test_seller_sprite_jobs_status_rejects_51_raw_ids_before_deduplication(monkeypatch):
    """原始输入数量上限必须先于去重校验。"""
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: (_ for _ in ()).throw(AssertionError("原始数量超限不应读取任务记录")),
    )

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(["duplicate-job"] * 51)
    )

    assert result["success"] is False
    assert "最多提供 50 个" in result["error"]["message"]


def test_seller_sprite_jobs_status_accepts_exactly_50_job_ids(monkeypatch):
    job_ids = [f"job-{index}" for index in range(50)]
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in job_ids})
    scheduler = BatchStatusWaitScheduler({job_id: ["queued"] for job_id in job_ids})
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)

    result = _run(seller_sprite_tools.seller_sprite_jobs_status(job_ids))

    assert result["success"] is True
    assert result["data"]["summary"]["total"] == 50
    assert [job["job_id"] for job in result["data"]["jobs"]] == job_ids


def test_seller_sprite_jobs_status_uses_one_queue_store_for_50_ids(monkeypatch):
    job_ids = [f"job-{index}" for index in range(50)]
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in job_ids})
    scheduler = BatchStatusWaitScheduler({job_id: ["queued"] for job_id in job_ids})
    store_factory_calls = 0

    def get_store():
        nonlocal store_factory_calls
        store_factory_calls += 1
        return store

    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_current_mcp_user_email",
        lambda: "mcp-user@example.com",
    )
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", get_store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)

    result = _run(seller_sprite_tools.seller_sprite_jobs_status(job_ids))

    assert result["success"] is True
    assert list(result["data"]) == ["ready", "summary", "jobs"]
    assert store_factory_calls == 1
    assert store.get_calls == job_ids


@pytest.mark.parametrize("job_ids", [["job-1", ""], ["job-1", "   "]])
def test_seller_sprite_jobs_status_rejects_blank_job_id(monkeypatch, job_ids):
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: (_ for _ in ()).throw(AssertionError("空白 ID 不应读取任务记录")),
    )

    result = _run(seller_sprite_tools.seller_sprite_jobs_status(job_ids))

    assert result["success"] is False
    assert result["data"] is None
    assert "job_id 不能为空" in result["error"]["message"]


def test_seller_sprite_jobs_status_strips_deduplicates_and_preserves_order(monkeypatch):
    job_ids = ["job-2", "job-1", "job-3"]
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in job_ids})
    scheduler = BatchStatusWaitScheduler({job_id: ["queued"] for job_id in job_ids})
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(
            [" job-2 ", "job-1", "job-2", " job-3 ", "job-1"],
        )
    )

    assert result["success"] is True
    assert [job["job_id"] for job in result["data"]["jobs"]] == job_ids
    assert store.get_calls == job_ids
    assert scheduler.status_calls == job_ids


def test_seller_sprite_jobs_status_preauthorizes_complete_collection_before_status_reads(
    monkeypatch,
):
    job_ids = ["job-1", "job-2", "job-3"]
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in job_ids})

    class PreauthorizationScheduler(BatchStatusWaitScheduler):
        def job_status(self, job_id):
            assert store.get_calls == job_ids
            return super().job_status(job_id)

    scheduler = PreauthorizationScheduler({job_id: ["queued"] for job_id in job_ids})
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)

    result = _run(seller_sprite_tools.seller_sprite_jobs_status(job_ids))

    assert result["success"] is True
    assert scheduler.status_calls == job_ids


def test_seller_sprite_jobs_status_rejects_missing_job_uniformly_after_full_validation(
    monkeypatch,
):
    job_ids = ["job-1", "job-missing", "job-after"]
    store = BatchOwnerStore(
        {
            "job-1": _batch_owner_record("job-1"),
            "job-after": _batch_owner_record("job-after"),
        }
    )
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_scheduler",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("缺记录时不应取得 scheduler")),
    )

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(
            ["job-1", "job-missing", " job-after ", "job-1", "job-missing"]
        )
    )

    assert result["success"] is False
    assert result["data"] is None
    assert store.get_calls == job_ids
    assert result["error"] == {
        "code": "ValueError",
        "message": "一个或多个卖家精灵任务不可用",
    }


def test_seller_sprite_jobs_status_rejects_other_user_uniformly_after_full_validation(
    monkeypatch,
):
    job_ids = ["job-1", "job-private", "job-after"]
    store = BatchOwnerStore(
        {
            "job-1": _batch_owner_record("job-1"),
            "job-private": _batch_owner_record(
                "job-private",
                user_email="owner@example.com",
            ),
            "job-after": _batch_owner_record("job-after"),
        }
    )
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_scheduler",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("越权时不应取得 scheduler")),
    )

    result = _run(seller_sprite_tools.seller_sprite_jobs_status(job_ids))

    assert result["success"] is False
    assert result["data"] is None
    assert store.get_calls == job_ids
    assert result["error"] == {
        "code": "ValueError",
        "message": "一个或多个卖家精灵任务不可用",
    }


def test_seller_sprite_jobs_status_rejects_listing_analysis_uniformly_after_full_validation(
    monkeypatch,
):
    job_ids = ["job-1", "listing-job-1", "job-after"]
    store = BatchOwnerStore(
        {
            "job-1": _batch_owner_record("job-1"),
            "listing-job-1": _batch_owner_record(
                "listing-job-1",
                scenario="listing-analysis",
            ),
            "job-after": _batch_owner_record("job-after"),
        }
    )
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_scheduler",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Listing Analysis 不应取得普通批量 scheduler")
        ),
    )

    result = _run(seller_sprite_tools.seller_sprite_jobs_status(job_ids))

    assert result["success"] is False
    assert result["data"] is None
    assert store.get_calls == job_ids
    assert result["error"] == {
        "code": "ValueError",
        "message": "一个或多个卖家精灵任务不可用",
    }


def test_seller_sprite_jobs_status_returns_mixed_summary_and_preserves_future_state(
    monkeypatch,
):
    states = {
        "job-queued": ["queued"],
        "job-running": ["running"],
        "job-succeeded": ["succeeded"],
        "job-failed": ["failed"],
        "job-future": ["pausing"],
    }
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in states})
    scheduler = BatchStatusWaitScheduler(states)
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)

    result = _run(seller_sprite_tools.seller_sprite_jobs_status(list(states)))

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert result["data"]["summary"] == {
        "total": 5,
        "queued": 1,
        "running": 1,
        "succeeded": 1,
        "failed": 1,
    }
    assert list(result["data"]["summary"]) == [
        "total",
        "queued",
        "running",
        "succeeded",
        "failed",
    ]
    assert [job["state"] for job in result["data"]["jobs"]] == [
        "queued",
        "running",
        "succeeded",
        "failed",
        "pausing",
    ]


def test_seller_sprite_jobs_status_initial_terminal_returns_immediately(monkeypatch):
    states = {"job-1": ["succeeded"], "job-2": ["failed"]}
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in states})
    scheduler = BatchStatusWaitScheduler(states)
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(list(states), wait_seconds=30)
    )

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["summary"] == {
        "total": 2,
        "queued": 0,
        "running": 0,
        "succeeded": 1,
        "failed": 1,
    }
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0
    assert scheduler.status_calls == ["job-1", "job-2"]


def test_seller_sprite_jobs_status_waits_until_all_jobs_terminal(monkeypatch):
    states = {
        "job-1": ["queued", "succeeded"],
        "job-2": ["running", "failed"],
    }
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in states})
    scheduler = BatchStatusWaitScheduler(states)
    clock = FakeWaitClock()
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep)

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(list(states), wait_seconds=30)
    )

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["summary"] == {
        "total": 2,
        "queued": 0,
        "running": 0,
        "succeeded": 1,
        "failed": 1,
    }
    assert clock.sleeps == [5]
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_jobs_status_timeout_returns_latest_snapshot(monkeypatch):
    states = {
        "job-1": ["queued", "running"],
        "job-2": ["queued", "queued", "running"],
    }
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in states})
    scheduler = BatchStatusWaitScheduler(states)
    clock = FakeWaitClock()
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep)

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(list(states), wait_seconds=12)
    )

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert result["data"]["summary"] == {
        "total": 2,
        "queued": 0,
        "running": 2,
        "succeeded": 0,
        "failed": 0,
    }
    assert [job["state"] for job in result["data"]["jobs"]] == ["running", "running"]
    assert clock.sleeps == [5, 5, 2]
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_jobs_status_clamps_wait_above_30_seconds(monkeypatch):
    job_ids = ["job-1", "job-2"]
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in job_ids})
    scheduler = BatchStatusWaitScheduler({job_id: ["queued"] for job_id in job_ids})
    clock = FakeWaitClock()
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep)

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(job_ids, wait_seconds=99)
    )

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert clock.sleeps == [5, 5, 5, 5, 5, 5]
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_jobs_status_clamps_negative_wait_to_zero(monkeypatch):
    job_ids = ["job-1", "job-2"]
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in job_ids})
    scheduler = BatchStatusWaitScheduler({job_id: ["queued"] for job_id in job_ids})
    clock = FakeWaitClock()
    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", clock.monotonic)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", clock.sleep)

    result = _run(
        seller_sprite_tools.seller_sprite_jobs_status(job_ids, wait_seconds=-8)
    )

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert clock.sleeps == []
    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0


def test_seller_sprite_jobs_status_cancellation_preserves_task_lifecycle(monkeypatch):
    job_ids = ["job-1", "job-2"]
    store = BatchOwnerStore({job_id: _batch_owner_record(job_id) for job_id in job_ids})
    scheduler = BatchStatusWaitScheduler({job_id: ["queued"] for job_id in job_ids})

    async def cancel_sleep(seconds):
        raise asyncio.CancelledError()

    _patch_batch_owner_store(monkeypatch, store)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_monotonic", lambda: 0.0)
    monkeypatch.setattr(seller_sprite_tools, "_status_wait_sleep", cancel_sleep)

    with pytest.raises(asyncio.CancelledError):
        _run(seller_sprite_tools.seller_sprite_jobs_status(job_ids, wait_seconds=30))

    assert scheduler.start_calls == 0
    assert scheduler.close_calls == 0
    assert store.fail_calls == 0
    assert store.cancel_calls == 0


def test_seller_sprite_jobs_status_is_public_while_start_remains_hidden():
    names = [tool.__name__ for tool in seller_sprite_tools._ALL_TOOLS]

    assert "seller_sprite_jobs_status" in names
    assert "seller_sprite_start" not in names


def test_seller_sprite_run_is_wrapped_by_quota(monkeypatch):
    called = {"service": 0}

    class BlockingLimiter:
        async def before_call(self, tool_name):
            assert tool_name == "seller_sprite_run"
            return type(
                "Decision",
                (),
                {
                    "allowed": False,
                    "error_response": {
                        "success": False,
                        "data": None,
                        "error": {"code": "MCP_QUOTA_EXCEEDED", "message": "超出每日调用限额"},
                        "quota": {"service": "seller_sprite", "limit": 5, "used": 5, "remaining": 0},
                    },
                },
            )()

        async def after_call(self, ticket, response):
            raise AssertionError("blocked calls must not settle quota")

    async def limited_tool():
        called["service"] += 1
        return {"success": True, "data": {}, "error": None}

    limited_tool.__name__ = "seller_sprite_run"
    wrapped = _quota_wrap(limited_tool, limiter=BlockingLimiter())

    result = _run(wrapped())

    assert called["service"] == 0
    assert result["success"] is False
    assert result["error"]["code"] == "MCP_QUOTA_EXCEEDED"



def test_listing_analysis_submit_is_wrapped_by_seller_sprite_quota():
    called = {"service": 0}

    class BlockingLimiter:
        async def before_call(self, tool_name):
            assert tool_name == "seller_sprite_listing_analysis_submit"
            return type(
                "Decision",
                (),
                {
                    "allowed": False,
                    "error_response": {
                        "success": False,
                        "data": None,
                        "error": {"code": "MCP_QUOTA_EXCEEDED", "message": "超出每日调用限额"},
                        "quota": {"service": "seller_sprite", "limit": 5, "used": 5, "remaining": 0},
                    },
                },
            )()

        async def after_call(self, ticket, response):
            raise AssertionError("blocked calls must not settle quota")

    async def limited_tool():
        called["service"] += 1
        return {"success": True, "data": {}, "error": None}

    limited_tool.__name__ = "seller_sprite_listing_analysis_submit"
    wrapped = _quota_wrap(limited_tool, limiter=BlockingLimiter())

    result = _run(wrapped())

    assert called["service"] == 0
    assert result["success"] is False
    assert result["error"]["code"] == "MCP_QUOTA_EXCEEDED"


def test_seller_sprite_non_run_tools_are_not_wrapped_by_quota():
    called = {"service": 0}

    async def scenarios_tool():
        called["service"] += 1
        return {"success": True, "data": [], "error": None}

    scenarios_tool.__name__ = "seller_sprite_scenarios"
    wrapped = _quota_wrap(scenarios_tool)

    result = _run(wrapped())

    assert called["service"] == 1
    assert result["success"] is True


def test_seller_sprite_run_queue_collision_does_not_create_owner_record(monkeypatch, tmp_path):
    """公共通用入口的 queue-only 碰撞必须由真实原子调度接口整体回滚。"""
    from opscli.seller_sprite.config import SellerSpriteSettings
    from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore
    from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=SellerSpriteScenarioRequest(
            scenario="keyword-reverse",
            site="US",
            period="30d",
            params={"asin": "B0ORIGINAL"},
            job_id="collision-job",
        ),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "original",
    )
    scheduler = SellerSpriteTaskScheduler(
        store=store,
        settings=SellerSpriteSettings(output_dir=tmp_path),
        auto_start=False,
    )
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda *args: ("sid", "jwt"))
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_current_mcp_user_email",
        lambda: "intruder@example.com",
    )
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            params={"asin": "B0INTRUDER"},
            job_id="collision-job",
        )
    )

    assert result["success"] is False
    with pytest.raises(ValueError, match="MCP 调用记录不存在"):
        store.get_mcp_run("collision-job")
    assert store.get_request("collision-job").params == {"asin": "B0ORIGINAL"}


def test_listing_analysis_submit_passes_owner_to_atomic_scheduler(monkeypatch):
    """Listing Analysis 专用提交也必须通过同一 owned enqueue 接口。"""
    scheduler = DummyScheduler()
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda *args: ("sid", "jwt"))
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_current_mcp_user_email",
        lambda: "mcp-user@example.com",
    )
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: (_ for _ in ()).throw(AssertionError("入口不得独立写 owner")),
    )
    DummyScheduler.last_mcp_user_email = None

    result = _run(
        seller_sprite_tools.seller_sprite_listing_analysis_submit(
            asin="B0TEST123",
            job_id="listing-atomic-job",
        )
    )

    assert result["success"] is True
    assert DummyScheduler.last_mcp_user_email == "mcp-user@example.com"
    assert DummyScheduler.last_enqueue_kwargs == {
        "credential_scope": "default",
        "expected_user_email": "mcp-user@example.com",
        "mcp_user_email": "mcp-user@example.com",
    }


def test_seller_sprite_run_passes_owner_to_atomic_scheduler(monkeypatch):
    """通用 run 必须把所有权交给 scheduler 原子写入，不再直接访问 Store。"""
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: (_ for _ in ()).throw(AssertionError("入口不得独立写 owner")),
    )
    DummyScheduler.enqueue_calls = 0
    DummyScheduler.last_mcp_user_email = None

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params={"asin": "B07YRMT36L", "keywords": ["router"]},
            export_format="json",
            job_id="mcp-job-run-1",
        )
    )

    assert result["success"] is True
    assert DummyScheduler.enqueue_calls == 1
    assert DummyScheduler.last_mcp_user_email == "mcp-user@example.com"
    assert DummyScheduler.last_request.job_id == "mcp-job-run-1"
    assert DummyScheduler.last_enqueue_kwargs == {
        "credential_scope": "default",
        "expected_user_email": "mcp-user@example.com",
        "mcp_user_email": "mcp-user@example.com",
    }


def test_seller_sprite_run_rejects_whitespace_only_current_user_before_persisting(
    monkeypatch,
    tmp_path,
):
    store = _make_store(tmp_path)
    DummyScheduler.enqueue_calls = 0
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-whitespace-user")
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "   ")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            params={"asin": "B07YRMT36L"},
        )
    )

    assert result["success"] is False
    assert "邮箱缺失" in result["error"]["message"]
    assert DummyScheduler.enqueue_calls == 0
    with pytest.raises(ValueError, match="调用记录不存在"):
        store.get_mcp_run("job-whitespace-user")


def test_seller_sprite_run_ignores_legacy_explicit_auth_for_remote_mcp(monkeypatch):
    from opscli.mcp.ops_credentials import OpsCredentialBinding

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())

    async def ensure_binding(*, provided_session, provided_jwt):
        assert provided_session == "explicit-session"
        assert provided_jwt == "explicit-jwt"
        return OpsCredentialBinding(
            credential_scope="isolated-user-scope",
            user_email="mcp-user@example.com",
            session_id="isolated-session",
            jwt="isolated-jwt",
        )

    monkeypatch.setattr(seller_sprite_tools, "ensure_ops_credentials", ensure_binding)
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_queue_store",
        lambda: (_ for _ in ()).throw(AssertionError("入口不得独立写 owner")),
    )
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            params={"asin": "B07YRMT36L"},
            job_id="mcp-job-explicit-auth",
            session_id="explicit-session",
            jwt="explicit-jwt",
        )
    )

    assert result["success"] is True
    assert DummyScheduler.enqueue_calls == 1
    assert DummyScheduler.last_enqueue_kwargs == {
        "credential_scope": "isolated-user-scope",
        "expected_user_email": "mcp-user@example.com",
        "mcp_user_email": "mcp-user@example.com",
    }


def test_seller_sprite_run_enqueue_failure_does_not_create_owner_record(monkeypatch, tmp_path):
    """原子入队失败时不得保留可授权的 failed owner 记录。"""
    store = _make_store(tmp_path)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: FailingScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="product-research",
            params={"asin": "B0FAIL1234"},
            job_id="mcp-job-run-failed",
        )
    )

    assert result["success"] is False
    with pytest.raises(ValueError, match="MCP 调用记录不存在"):
        store.get_mcp_run("mcp-job-run-failed")


def test_seller_sprite_run_returns_error_when_mcp_user_email_missing(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    DummyScheduler.enqueue_calls = 0
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: None)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            params={"asin": "B07YRMT36L"},
        )
    )

    assert result["success"] is False
    assert "邮箱" in result["error"]["message"]
    assert DummyScheduler.enqueue_calls == 0
    try:
        store.get_mcp_run("job-async-1")
        raise AssertionError("邮箱缺失时不应创建 MCP 调用记录")
    except ValueError:
        pass


def test_seller_sprite_run_prepares_request_before_atomic_scheduler_enqueue(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: NoNormalizeScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    NoNormalizeScheduler.enqueue_calls = 0
    NoNormalizeScheduler.last_mcp_user_email = None

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="jp",
            period="nearly",
            params={"asin": "B07YRMT36L"},
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-async-1"
    assert result["data"]["site"] == "JP"
    assert result["data"]["period"] == "nearly"
    assert NoNormalizeScheduler.enqueue_calls == 1
    assert NoNormalizeScheduler.last_request.job_id == "job-async-1"
    assert NoNormalizeScheduler.last_mcp_user_email == "mcp-user@example.com"
