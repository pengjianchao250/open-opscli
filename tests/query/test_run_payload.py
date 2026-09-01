"""QueryManager.run_payload 的单元测试（REST API 执行路径）。

run_payload 是 run() 的无文件版本：REST 调用方在远端，payload 直接来自
请求体；校验与归因逻辑必须与 run() 完全一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opscli.query.domain.exceptions import InvalidPayloadError
from opscli.query.services.manager import QueryManager


class FakeQueryClient:
    """记录调用参数的 QueryClient 替身。"""

    def __init__(self):
        self.calls: list[dict] = []

    def cli_query(self, payload, extra_headers=None):
        self.calls.append({"payload": payload, "extra_headers": extra_headers})
        return {"rows": [], "meta": {"rowCount": 0}}


@pytest.fixture()
def manager():
    instance = QueryManager()
    instance.client = FakeQueryClient()
    return instance


def test_run_payload_forwards_valid_payload(manager):
    """合法 payload 原样转发到 cli_query，无归因时不附加请求头。"""
    payload = {"tableId": 15, "query": {"select": []}}

    result = manager.run_payload(payload)

    assert result == {"rows": [], "meta": {"rowCount": 0}}
    assert manager.client.calls == [
        {"payload": payload, "extra_headers": None}
    ]


def test_run_payload_attaches_attribution_headers(manager):
    """归因三元组以请求头形式透传，不写入 payload。"""
    payload = {"tableId": 15, "query": {}}

    manager.run_payload(
        payload,
        intent_code="intent_x",
        selection_source="intent_route",
        match_record_id=7,
    )

    call = manager.client.calls[0]
    assert call["payload"] == payload
    assert call["extra_headers"] == {
        "X-Intent-Code": "intent_x",
        "X-Selection-Source": "intent_route",
        "X-Match-Record-Id": "7",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"query": {}},  # 缺 tableId
        {"tableId": 15},  # 缺 query 对象
        {"tableId": 15, "query": "not-a-dict"},
    ],
    ids=["missing-table-id", "missing-query", "query-not-dict"],
)
def test_run_payload_rejects_invalid_structure(manager, payload):
    """最小结构校验失败必须拦截在本地，不发起远端请求。"""
    with pytest.raises(InvalidPayloadError):
        manager.run_payload(payload)

    assert manager.client.calls == []


def test_run_delegates_to_run_payload(manager, tmp_path: Path):
    """run() 读文件后委托 run_payload，两条执行路径共用同一校验与转发逻辑。"""
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(
        json.dumps({"tableId": 15, "query": {"select": []}}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = manager.run(payload_path=str(payload_file))

    assert result == {"rows": [], "meta": {"rowCount": 0}}
    assert len(manager.client.calls) == 1
    assert manager.client.calls[0]["payload"] == {"tableId": 15, "query": {"select": []}}
