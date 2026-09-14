"""Keepa 上游错误码映射回归测试。"""

from __future__ import annotations

import httpx
import pytest

from opscli.keepa.api.client import _parse_json_response
from opscli.keepa.domain.exceptions import KeepaApiError


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_code"),
    [
        (401, {"error": "invalid key"}, "KEEPA_AUTH_ERROR"),
        (403, {"error": "forbidden"}, "KEEPA_FORBIDDEN"),
        (429, {"error": "too many requests"}, "KEEPA_RATE_LIMITED"),
        (400, {"error": "insufficient tokens"}, "KEEPA_QUOTA_INSUFFICIENT"),
    ],
)
def test_keepa_upstream_errors_have_stable_codes(
    status_code: int,
    payload: dict[str, str],
    expected_code: str,
) -> None:
    """Keepa HTTP/业务错误应映射为调用方可分支处理的错误码。"""
    response = httpx.Response(status_code, json=payload)

    with pytest.raises(KeepaApiError) as captured:
        _parse_json_response(response)

    assert captured.value.code == expected_code


def test_keepa_upstream_error_logs_bounded_diagnostic_without_api_key(caplog) -> None:
    """上游错误日志应包含分类字段，但不能记录 API Key 或完整响应。"""
    response = httpx.Response(
        429,
        json={
            "error": {"code": "RATE_LIMIT", "message": "too many requests"},
            "tokensLeft": 0,
            "refillIn": 1200,
            "secret": "keepa-secret-value",
        },
    )

    with caplog.at_level("WARNING", logger="opscli.keepa.api"):
        with pytest.raises(KeepaApiError):
            _parse_json_response(response, secrets=("keepa-secret-value",))

    message = "\n".join(record.getMessage() for record in caplog.records)
    assert "[KEEPA-DIAG] upstream_error" in message
    assert "status=429" in message
    assert "upstream_code=RATE_LIMIT" in message
    assert "tokens_left=0" in message
    assert "keepa-secret-value" not in message
    assert "secret" not in message
