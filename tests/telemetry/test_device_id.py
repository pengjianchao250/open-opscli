# tests/telemetry/test_device_id.py
"""device_id 模块单元测试。"""

import uuid
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    """每个测试前清除模块级缓存，确保测试隔离。"""
    import opscli.telemetry.device_id as did
    monkeypatch.setattr(did, "_cached", None)


def test_get_device_id_returns_valid_uuid(tmp_path, monkeypatch):
    """首次调用应返回合法 UUID v4 字符串。"""
    import opscli.telemetry.device_id as did
    monkeypatch.setattr(did, "_DEVICE_ID_FILE", tmp_path / "device_id")

    result = did.get_device_id()

    uuid.UUID(result)  # 不合法时抛出 ValueError


def test_get_device_id_persists_to_file(tmp_path, monkeypatch):
    """首次调用后应将 device_id 写入文件。"""
    import opscli.telemetry.device_id as did
    device_file = tmp_path / "device_id"
    monkeypatch.setattr(did, "_DEVICE_ID_FILE", device_file)

    did.get_device_id()

    assert device_file.exists()
    assert len(device_file.read_text().strip()) == 36  # UUID 长度


def test_get_device_id_returns_same_value_on_second_call(tmp_path, monkeypatch):
    """同一进程内两次调用应返回相同 ID（内存缓存）。"""
    import opscli.telemetry.device_id as did
    monkeypatch.setattr(did, "_DEVICE_ID_FILE", tmp_path / "device_id")

    id1 = did.get_device_id()
    id2 = did.get_device_id()

    assert id1 == id2


def test_get_device_id_reads_existing_file(tmp_path, monkeypatch):
    """文件已存在时应读取文件内容，而非重新生成。"""
    import opscli.telemetry.device_id as did
    device_file = tmp_path / "device_id"
    existing_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    device_file.write_text(existing_id)
    monkeypatch.setattr(did, "_DEVICE_ID_FILE", device_file)

    result = did.get_device_id()

    assert result == existing_id
