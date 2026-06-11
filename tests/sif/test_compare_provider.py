import json
from pathlib import Path
from uuid import uuid4

import pytest

from opscli.sif.domain.models import SifRunRequest
from opscli.sif.compare.provider import SifCompareProvider


class FakeCompareClient:
    def __init__(self):
        self.post_calls = []

    def download_post(self, path, *, payload, country=None):
        self.post_calls.append((path, payload, country))
        return b"PK\x03\x04compare"


def test_compare_provider_writes_all_exports():
    output_dir = Path("output") / "test-artifacts" / f"sif-compare-{uuid4().hex}"
    client = FakeCompareClient()
    provider = SifCompareProvider(client=client)

    result = provider.run(
        SifRunRequest(
            feature="多产品对比",
            asin="B075WPKK5P,B07KVV8RFF,B07QQ21GL2",
            site="US",
            time_piece_value="30",
            output_dir=str(output_dir),
            job_id="job-compare",
        ),
        default_output_dir=output_dir,
    )

    root = output_dir / "job-compare"
    assert result.summary["asin_count"] == 3
    assert len(result.exports) == 5
    assert result.exports["compare_sales_xlsx"].filename.startswith("对比销量_3个ASIN_")
    assert result.exports["compare_traffic_words_xlsx"].filename.startswith("对比流量词_3个ASIN_")
    assert result.exports["compare_traffic_score_xlsx"].filename.startswith("对比流量分_3个ASIN_")
    assert result.exports["compare_my_traffic_keywords_xlsx"].filename.startswith("重点流量词_3个ASIN_")
    assert result.exports["compare_my_ad_keywords_xlsx"].filename.startswith("重点广告词_3个ASIN_")
    assert len(client.post_calls) == 5
    sales_payload = client.post_calls[0][1]
    assert sales_payload["pageSize"] == 100
    assert sales_payload["timePieceValue"] == "30"
    assert client.post_calls[1][1]["showType"] == 1
    assert client.post_calls[2][1]["showType"] == 2
    assert client.post_calls[3][1]["listType"] == 1
    assert client.post_calls[4][1]["listType"] == 2
    payload = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "sif_compare.v1"


def test_compare_provider_sections_download_only_ad_keywords():
    output_dir = Path("output") / "test-artifacts" / f"sif-compare-section-{uuid4().hex}"
    client = FakeCompareClient()
    provider = SifCompareProvider(client=client)

    result = provider.run(
        SifRunRequest(
            feature="多产品对比",
            asin="B075WPKK5P,B07KVV8RFF",
            site="US",
            sections=["重点广告词"],
            page_size=20,
            output_dir=str(output_dir),
            job_id="job-compare",
        ),
        default_output_dir=output_dir,
    )

    assert list(result.exports) == ["compare_my_ad_keywords_xlsx"]
    assert len(client.post_calls) == 1
    assert client.post_calls[0][1]["listType"] == 2
    assert client.post_calls[0][1]["myPageSize"] == 20


def test_compare_provider_requires_multiple_asins():
    provider = SifCompareProvider(client=FakeCompareClient())

    with pytest.raises(ValueError):
        provider.run(
            SifRunRequest(feature="多产品对比", asin="B075WPKK5P", site="US"),
            default_output_dir=Path("output/test-artifacts"),
        )
