import json
from pathlib import Path
from uuid import uuid4

from opscli.sif.domain.models import SifRunRequest
from opscli.sif.product_time_machine.provider import SifProductTimeMachineProvider
from opscli.sif.product_time_machine.scenarios import PRODUCT_TIME_MACHINE_DOWNLOAD_PATH, PRODUCT_TIME_MACHINE_LIST_PATH


class FakeProductTimeMachineClient:
    def __init__(self):
        self.json_calls = []
        self.post_calls = []

    def post_json(self, path, *, payload, country=None):
        self.json_calls.append((path, payload, country))
        return {"code": 1, "data": {"items": [{"keyword": payload["keyword"]}]}}

    def download_post(self, path, *, payload, country=None):
        self.post_calls.append((path, payload, country))
        return b"PK\x03\x04product"


def test_product_time_machine_provider_uses_keyword_not_asin():
    output_dir = Path("output") / "test-artifacts" / f"sif-product-time-{uuid4().hex}"
    client = FakeProductTimeMachineClient()
    provider = SifProductTimeMachineProvider(client=client)

    result = provider.run(
        SifRunRequest(
            feature="产品时光机",
            keyword="balloon pump",
            site="US",
            time_piece_type="month",
            time_piece_value="2026-02",
            page_size=20,
            output_dir=str(output_dir),
            job_id="job-product-time",
        ),
        default_output_dir=output_dir,
    )

    root = output_dir / "job-product-time"
    assert result.keyword == "balloon pump"
    assert result.asin is None
    assert result.exports["product_time_machine_xlsx"].filename.startswith("产品时光机_balloon_pump_")
    assert client.json_calls[0][0] == PRODUCT_TIME_MACHINE_LIST_PATH
    assert client.json_calls[0][1]["keyword"] == "balloon pump"
    assert client.json_calls[0][1]["pageSize"] == 20
    assert client.post_calls[0][0] == PRODUCT_TIME_MACHINE_DOWNLOAD_PATH
    assert client.post_calls[0][1]["timePieceType"] == "month"
    payload = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "sif_product_time_machine.v1"
    assert payload["keyword"] == "balloon pump"
