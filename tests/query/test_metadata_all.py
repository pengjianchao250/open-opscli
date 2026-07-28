"""QueryClient/QueryManager 全量元数据单测。"""
from pathlib import Path

import httpx
import respx

from opscli.query.services.manager import QueryManager
from opscli.query.transport.client import QueryClient


@respx.mock
def test_fetch_query_metadata_include_all_fields():
    """include_all_fields=True 时请求带 include_all_fields=1。"""
    route = respx.get(url__regex=r".*/datasets/query-metadata.*").mock(
        return_value=httpx.Response(
            200, json={"code": 0, "data": {"datasets": [], "fields": [{"field_name": "x"}]}}
        )
    )
    client = QueryClient()
    # 绕过真实认证：注入空鉴权
    client._get_auth = lambda system: ({}, {})  # type: ignore[method-assign]
    client.fetch_query_metadata(include_all_fields=True)
    assert route.called
    assert "include_all_fields=1" in str(route.calls.last.request.url)


@respx.mock
def test_metadata_all_uses_cache(tmp_path: Path):
    """metadata_all 首次拉取全量并缓存，二次命中不再请求。"""
    route = respx.get(url__regex=r".*/datasets/query-metadata.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"datasets": [{"dataset_alias": "ds_a"}], "fields": [{"field_name": "x"}]},
            },
        )
    )
    mgr = QueryManager()
    mgr.client._get_auth = lambda system: ({}, {})  # type: ignore[method-assign]

    r1 = mgr.metadata_all(user_email="u@x.com", base_dir=tmp_path)
    assert r1.from_cache is False
    assert r1.payload["fields"] == [{"field_name": "x"}]
    assert route.call_count == 1

    r2 = mgr.metadata_all(user_email="u@x.com", base_dir=tmp_path)
    assert r2.from_cache is True
    assert route.call_count == 1  # 命中缓存，未再请求
