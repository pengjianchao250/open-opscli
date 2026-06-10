import json
from pathlib import Path
from uuid import uuid4

from opscli.sif.domain.models import SifRunRequest
from opscli.sif.ranking.provider import SifRankingProvider
from opscli.sif.ranking.scenarios import RANKING_DOWNLOAD_PATH, RANKING_LIST_PATH


class FakeRankingClient:
    def __init__(self):
        self.json_calls = []
        self.post_calls = []

    def post_json(self, path, *, payload, country=None):
        self.json_calls.append((path, payload, country))
        return {"code": 1, "data": {"list": [{"asin": payload["asin"]}]}}

    def download_post(self, path, *, payload, country=None):
        self.post_calls.append((path, payload, country))
        return b"PK\x03\x04ranking"


def test_ranking_provider_writes_list_response_and_export():
    output_dir = Path("output") / "test-artifacts" / f"sif-ranking-{uuid4().hex}"
    client = FakeRankingClient()
    provider = SifRankingProvider(client=client)

    result = provider.run(
        SifRunRequest(
            feature="查排名",
            asin="b0bmw2985v",
            site="美国站",
            granularity="month",
            page_size=20,
            output_dir=str(output_dir),
            job_id="job-ranking",
        ),
        default_output_dir=output_dir,
    )

    root = output_dir / "job-ranking"
    assert result.site == "US"
    assert result.asin == "B0BMW2985V"
    assert result.exports["daily_ranking_xlsx"].filename.startswith("每日排名_B0BMW2985V_")
    assert client.json_calls == [(RANKING_LIST_PATH, client.json_calls[0][1], "US")]
    assert client.json_calls[0][1]["pageSize"] == 20
    assert client.post_calls[0][0] == RANKING_DOWNLOAD_PATH
    assert client.post_calls[0][1]["granularity"] == "month"
    payload = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "sif_ranking.v1"
    assert payload["summary"]["list_item_count"] == 1
    assert payload["list_response"]["data"]["list"][0]["asin"] == "B0BMW2985V"
