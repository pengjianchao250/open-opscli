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
