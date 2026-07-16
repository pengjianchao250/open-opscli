import json
from pathlib import Path

from opscli.asin_data.services.usage_log import append_usage_event


def test_append_usage_event_writes_sanitized_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"

    append_usage_event(
        command="basic",
        params={
            "asins": ["B086M58PQ3"],
            "site": "US",
            "jwt": "secret-jwt",
            "nested": {
                "Authorization": "Bearer secret",
                "cookie": "session=secret",
                "domain": "listing",
            },
        },
        status="success",
        elapsed_seconds=0.1236,
        path=path,
    )

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["command"] == "basic"
    assert event["status"] == "success"
    assert event["elapsed_seconds"] == 0.124
    assert event["params"] == {
        "asins": ["B086M58PQ3"],
        "site": "US",
        "jwt": "[REDACTED]",
        "nested": {
            "Authorization": "[REDACTED]",
            "cookie": "[REDACTED]",
            "domain": "listing",
        },
    }
    assert event["timestamp"]


def test_append_usage_event_records_error_without_credentials(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"

    append_usage_event(
        command="bi",
        params={"asin": "B086M58PQ3", "api_key": "secret"},
        status="error",
        elapsed_seconds=1.0,
        error={"code": "BAD_DATE", "message": "date_from is invalid"},
        path=path,
    )

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["params"]["api_key"] == "[REDACTED]"
    assert event["error"] == {"code": "BAD_DATE", "message": "date_from is invalid"}


def test_append_usage_event_does_not_break_request_when_log_write_fails(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("occupied", encoding="utf-8")

    append_usage_event(
        command="category-top",
        params={"category": "Bed Frames"},
        status="success",
        elapsed_seconds=0.1,
        path=parent_file / "usage.jsonl",
    )
