import sys
from types import ModuleType

import pytest

from opscli.google_trends.api.client import GoogleTrendsApiClient
from opscli.google_trends.api.client import _patch_pytrends_retry_compatibility
from opscli.google_trends.domain.exceptions import GoogleTrendsConfigError


def test_patch_pytrends_retry_accepts_method_whitelist(monkeypatch):
    calls = []

    class RetryV2:
        def __init__(self, *args, allowed_methods=None, **kwargs):
            calls.append({"args": args, "allowed_methods": allowed_methods, "kwargs": kwargs})

    pytrends_package = ModuleType("pytrends")
    pytrends_package.__path__ = []
    pytrends_request = ModuleType("pytrends.request")
    pytrends_request.Retry = RetryV2
    monkeypatch.setitem(sys.modules, "pytrends", pytrends_package)
    monkeypatch.setitem(sys.modules, "pytrends.request", pytrends_request)

    _patch_pytrends_retry_compatibility()
    pytrends_request.Retry(total=1, method_whitelist=frozenset(["GET", "POST"]))

    assert pytrends_request._opscli_retry_compat_patched is True
    assert calls == [
        {
            "args": (),
            "allowed_methods": frozenset(["GET", "POST"]),
            "kwargs": {"total": 1},
        }
    ]


def test_patch_pytrends_retry_leaves_urllib3_1_signature_unchanged(monkeypatch):
    class RetryV1:
        def __init__(self, *args, method_whitelist=None, **kwargs):
            pass

    pytrends_package = ModuleType("pytrends")
    pytrends_package.__path__ = []
    pytrends_request = ModuleType("pytrends.request")
    pytrends_request.Retry = RetryV1
    monkeypatch.setitem(sys.modules, "pytrends", pytrends_package)
    monkeypatch.setitem(sys.modules, "pytrends.request", pytrends_request)

    _patch_pytrends_retry_compatibility()

    assert pytrends_request.Retry is RetryV1
    assert not hasattr(pytrends_request, "_opscli_retry_compat_patched")


@pytest.mark.parametrize("scenario", ["trending-searches", "realtime-trending", "related-topics"])
def test_unavailable_scenarios_fail_before_pytrends_request(monkeypatch, scenario):
    client = GoogleTrendsApiClient()

    def fail_if_called():
        raise AssertionError("pytrends request should not be created for unavailable scenarios")

    monkeypatch.setattr(client, "_trend_req", fail_if_called)

    with pytest.raises(GoogleTrendsConfigError, match="暂不可用"):
        client.run(scenario, {"pn": "US"})
