"""SSE 解析与发布句柄持久化测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import PublishSession
from opscli.app.services.session import PublishSessionStore
from opscli.app.services.sse import parse_sse


def test_parse_sse_ignores_heartbeat_and_supports_done() -> None:
    frames = list(parse_sse([
        ": ping",
        "",
        "data: {\"seq\":1,",
        "data: \"status\":\"healthy\"}",
        "",
        "event: done",
        "data: {}",
        "",
    ]))

    assert len(frames) == 2
    assert frames[0].data == {"seq": 1, "status": "healthy"}
    assert frames[1].event == "done"


def test_session_store_round_trip_and_clear(tmp_path: Path) -> None:
    store = PublishSessionStore(base_dir=tmp_path)
    session = PublishSession(
        release_id=7,
        last_seq=3,
        slug="demo-app",
        commit_sha="a" * 40,
        started_at="2026-08-31T00:00:00+00:00",
    )

    store.save(session)

    assert store.load("demo-app") == session
    store.clear("demo-app")
    assert not store.path_for("demo-app").exists()


def test_corrupt_session_is_not_guessed(tmp_path: Path) -> None:
    store = PublishSessionStore(base_dir=tmp_path)
    path = store.path_for("demo-app")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"release_id": "bad"}), encoding="utf-8")

    with pytest.raises(AppProjectError) as caught:
        store.load("demo-app")

    assert caught.value.code == "APP-SESSION-INVALID"

