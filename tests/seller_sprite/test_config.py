"""SellerSprite 持久存储配置合同测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opscli.collector_monitor.config import load_settings as load_monitor_settings
from opscli.seller_sprite.config import load_settings
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore


def test_queue_path_is_shared_by_collector_store_and_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一份 SellerSprite 队列配置应同时驱动写端与 Monitor 读端。"""
    queue_path = tmp_path / "shared" / "task_queue.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_QUEUE_DB_PATH", str(queue_path))
    monkeypatch.delenv("OPSCLI_COLLECTOR_MONITOR_QUEUE_DB_PATH", raising=False)

    seller_settings = load_settings()
    store = SellerSpriteTaskQueueStore()
    monitor_settings = load_monitor_settings(environ=dict(os.environ))

    assert seller_settings.queue_db_path == queue_path
    assert store.db_path == queue_path
    assert monitor_settings.queue_db_path == queue_path
    assert "queue_db_path" not in seller_settings.to_public_dict()


def test_monitor_rejects_conflicting_queue_paths(tmp_path: Path) -> None:
    """显式配置两个不同业务库时必须在 Monitor 启动前失败。"""
    with pytest.raises(ValueError, match="queue db path conflicts"):
        load_monitor_settings(
            environ={
                "OPSCLI_SELLER_SPRITE_QUEUE_DB_PATH": str(tmp_path / "collector.sqlite3"),
                "OPSCLI_COLLECTOR_MONITOR_QUEUE_DB_PATH": str(tmp_path / "monitor.sqlite3"),
            },
            config_dir=tmp_path,
        )


def test_shared_queue_path_is_normalized_to_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """相对路径必须在共享解析点规范化，避免两个服务按不同工作目录解释。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "OPSCLI_SELLER_SPRITE_QUEUE_DB_PATH",
        "runtime/task_queue.sqlite3",
    )

    assert load_settings().queue_db_path == (
        tmp_path / "runtime" / "task_queue.sqlite3"
    ).resolve()
