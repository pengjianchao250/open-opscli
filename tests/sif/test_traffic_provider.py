import json
from pathlib import Path
from uuid import uuid4

from opscli.sif.domain.models import SifRunRequest
from opscli.sif.traffic.provider import SifTrafficProvider


class FakeTrafficClient:
    def __init__(self):
        self.get_calls = []
        self.post_calls = []

    def download_get(self, path, *, query, country=None, headers=None):
        self.get_calls.append((path, query, country, headers))
        return b"PK\x03\x04structure"

    def download_post(self, path, *, payload, country=None):
        self.post_calls.append((path, payload, country))
        return b"PK\x03\x04post"


def test_traffic_provider_writes_three_exports_and_referer():
    output_dir = Path("output") / "test-artifacts" / f"sif-traffic-{uuid4().hex}"
    client = FakeTrafficClient()
    provider = SifTrafficProvider(client=client)

    result = provider.run(
        SifRunRequest(
            feature="查流量",
            asin="B01NBNDC1T",
            site="美国站",
            output_dir=str(output_dir),
            job_id="job-traffic",
        ),
        default_output_dir=output_dir,
    )

    root = output_dir / "job-traffic"
    assert result.site == "US"
    assert len(result.exports) == 3
    assert result.exports["traffic_structure_xlsx"].filename.startswith("流量结构_B01NBNDC1T_")
    assert result.exports["traffic_keywords_xlsx"].filename.startswith("反查流量词_B01NBNDC1T_")
    assert result.exports["multi_nf_keywords_xlsx"].filename.startswith("多变体自然位_B01NBNDC1T_")
    assert (root / "params.json").exists()
    assert (root / "raw.json").exists()
    assert (root / "result.json").exists()
    assert client.get_calls[0][3]["Referer"].startswith("https://www.sif.com/Traffic")
    payload = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "sif_traffic.v1"
    assert payload["summary"]["export_count"] == 3
    assert "password" not in (root / "params.json").read_text(encoding="utf-8").lower()


def test_traffic_provider_sections_download_only_structure():
    output_dir = Path("output") / "test-artifacts" / f"sif-traffic-section-{uuid4().hex}"
    client = FakeTrafficClient()
    provider = SifTrafficProvider(client=client)

    result = provider.run(
        SifRunRequest(
            feature="查流量",
            asin="B01NBNDC1T",
            site="US",
            sections=["流量结构"],
            output_dir=str(output_dir),
            job_id="job-traffic",
        ),
        default_output_dir=output_dir,
    )

    assert list(result.exports) == ["traffic_structure_xlsx"]
    assert len(client.get_calls) == 1
    assert len(client.post_calls) == 0


def test_traffic_provider_page_size_overrides_keyword_payloads():
    output_dir = Path("output") / "test-artifacts" / f"sif-traffic-page-size-{uuid4().hex}"
    client = FakeTrafficClient()
    provider = SifTrafficProvider(client=client)

    provider.run(
        SifRunRequest(
            feature="查流量",
            asin="B01NBNDC1T",
            site="US",
            sections=["反查流量词"],
            page_size=20,
            output_dir=str(output_dir),
            job_id="job-traffic",
        ),
        default_output_dir=output_dir,
    )

    assert client.post_calls[0][1]["pageSize"] == 20
