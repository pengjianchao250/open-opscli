import json
from pathlib import Path
from uuid import uuid4

from opscli.sif.domain.models import SifRunRequest
from opscli.sif.operation_time_machine.provider import SifOperationTimeMachineProvider
from opscli.sif.operation_time_machine.scenarios import OPERATION_TIME_MACHINE_DOWNLOAD_PATH, OPERATION_TIME_MACHINE_LIST_PATH


class FakeOperationTimeMachineClient:
    def __init__(self):
        self.json_calls = []
        self.post_calls = []

    def post_json(self, path, *, payload, country=None):
        self.json_calls.append((path, payload, country))
        return {"code": 1, "data": {"rows": [{"asin": payload["asin"]}]}}

    def download_post(self, path, *, payload, country=None):
        self.post_calls.append((path, payload, country))
        return b"PK\x03\x04operation"


def test_operation_time_machine_provider_supports_keyword_count_change_section():
    output_dir = Path("output") / "test-artifacts" / f"sif-operation-{uuid4().hex}"
    client = FakeOperationTimeMachineClient()
    provider = SifOperationTimeMachineProvider(client=client)

    result = provider.run(
        SifRunRequest(
            feature="运营时光机",
            asin="B01NBNDC1T",
            site="US",
            granularity="week",
            last_months=12,
            sections=["流量词数量变化"],
            output_dir=str(output_dir),
            job_id="job-operation",
        ),
        default_output_dir=output_dir,
    )

    root = output_dir / "job-operation"
    assert list(result.exports) == ["operation_keyword_count_change_xlsx"]
    assert result.exports["operation_keyword_count_change_xlsx"].filename.startswith("运营时光机_流量词数量变化_B01NBNDC1T_")
    assert client.json_calls[0][0] == OPERATION_TIME_MACHINE_LIST_PATH
    assert client.json_calls[0][1]["type"] == "all"
    assert client.json_calls[0][1]["lastMonths"] == 12
    assert client.post_calls[0][0] == OPERATION_TIME_MACHINE_DOWNLOAD_PATH
    payload = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "sif_operation_time_machine.v1"
    assert payload["summary"]["list_item_count"] == 1
