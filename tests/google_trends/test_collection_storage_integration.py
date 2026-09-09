"""Google Trends 共享数据沉淀适配测试。"""

import json
from pathlib import Path
from types import SimpleNamespace

from opscli.google_trends.collection_storage_integration import (
    GOOGLE_TRENDS_CACHE_SCOPE,
    GoogleTrendsCollectionReconciler,
    GoogleTrendsCollectionSubmitter,
    build_google_trends_cache_identity,
)
from opscli.google_trends.domain.models import (
    GoogleTrendsScenarioRequest,
    GoogleTrendsScenarioResult,
)


def test_google_trends_submitter_adds_mcp_environment(tmp_path: Path):
    """成功任务应转换为带 MCP 环境信息的通用提交。"""

    class FakeRuntime:
        settings = SimpleNamespace(data_environment="production")

        def __init__(self):
            self.submissions = []

        def submit(self, submission):
            self.submissions.append(submission)
            return True

    runtime = FakeRuntime()
    request = GoogleTrendsScenarioRequest(
        scenario="trends",
        geo="US",
        params={"q": "flashlight"},
        job_id="job-1",
    )
    result = GoogleTrendsScenarioResult.empty(
        job_id="job-1",
        scenario=request.scenario,
        geo=request.geo,
        root_dir=tmp_path,
        params_path=tmp_path / "params.json",
        raw_path=tmp_path / "raw.json",
        result_path=tmp_path / "result.json",
    )

    accepted = GoogleTrendsCollectionSubmitter(runtime)(request=request, result=result)

    assert accepted is True
    [submission] = runtime.submissions
    assert submission.source_system == "google_trends"
    assert submission.source_job_id == "job-1"
    assert submission.producer_service == "mcp"
    assert submission.scenario == "trends"
    assert submission.site == "US"
    assert submission.data_environment == "production"
    assert submission.ingestion_mode == "live"
    assert submission.result_path == Path(result.result_path).resolve()
    assert submission.cache_key == build_google_trends_cache_identity(request)[1]
    assert submission.cache_scope == GOOGLE_TRENDS_CACHE_SCOPE


def test_google_trends_reconciler_returns_only_missing_successes(tmp_path: Path):
    """启动对账应补交 cutover 后尚未进入 Outbox 的成功任务。"""

    class FakeOutbox:
        def contains(self, *, source_system, source_job_id, data_environment):
            assert source_system == "google_trends"
            assert data_environment == "debug"
            return source_job_id == "job-existing"

    output_dir = tmp_path / "google-trends-runs"
    for job_id in ("job-existing", "job-missing"):
        root = output_dir / job_id
        root.mkdir(parents=True)
        result_path = root / "result.json"
        params_path = root / "params.json"
        params_path.write_text(
            json.dumps(
                {
                    "request": {
                        "scenario": "trends",
                        "geo": "US",
                        "params": {"q": "flashlight"},
                        "export_format": "xls",
                    },
                    "normalized_params": {
                        "q": "flashlight",
                        "geo": "US",
                        "data_type": "TIMESERIES",
                    },
                }
            ),
            encoding="utf-8",
        )
        result_path.write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "scenario": "trends",
                    "geo": "US",
                    "result_path": str(result_path),
                    "params_path": str(params_path),
                    "row_count": 2,
                }
            ),
            encoding="utf-8",
        )
    reconciler = GoogleTrendsCollectionReconciler(
        output_dir=output_dir,
        data_environment="debug",
        outbox=FakeOutbox(),
    )

    batch = reconciler.reconcile(
        cutover_at="2020-01-01T00:00:00+00:00",
        cursor=0,
        limit=10,
    )

    assert [item.source_job_id for item in batch.submissions] == ["job-missing"]
    [submission] = batch.submissions
    assert submission.scenario == "trends"
    assert submission.site == "US"
    assert submission.data_environment == "debug"
    assert submission.completed_at is not None
    assert submission.cache_key
    assert submission.cache_scope == GOOGLE_TRENDS_CACHE_SCOPE
    assert submission.result_metadata["row_count"] == 2
    assert batch.next_cursor > 0
