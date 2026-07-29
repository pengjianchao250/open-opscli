"""Collector Monitor 配置公开契约测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from opscli.collector_monitor.config import (
    MonitorSettings,
    load_settings,
    validate_database_paths,
    validate_settings,
)
from opscli.collector_monitor.server import build_service


def test_load_settings_uses_safe_defaults(tmp_path: Path) -> None:
    """默认配置应落在 CONFIG_DIR 下，并仅监听本机地址。"""
    settings = load_settings(environ={}, config_dir=tmp_path)

    assert settings == MonitorSettings(
        queue_db_path=tmp_path / "seller_sprite" / "task_queue.sqlite3",
        state_db_path=tmp_path / "collector_monitor" / "state.sqlite3",
        monitor_url="http://127.0.0.1:8767",
        collector_mcp_url=None,
        collector_mcp_api_key_file=None,
        poll_interval=10.0,
        stalled_threshold=300.0,
        queue_threshold=300.0,
        runtime_stale_threshold=300.0,
        orphan_required_scans=2,
        alert_cooldown=1800.0,
        webhook_file=None,
        host="127.0.0.1",
        port=8767,
        collector_probe_timeout=5.0,
    )


def test_load_settings_reads_prefixed_environment(tmp_path: Path) -> None:
    """所有公开设置都应支持统一前缀的环境变量。"""
    env = {
        "OPSCLI_COLLECTOR_MONITOR_QUEUE_DB_PATH": str(tmp_path / "queue.sqlite3"),
        "OPSCLI_COLLECTOR_MONITOR_STATE_DB_PATH": str(tmp_path / "monitor.sqlite3"),
        "OPSCLI_COLLECTOR_MONITOR_URL": "http://monitor.internal:9000/",
        "OPSCLI_COLLECTOR_MONITOR_COLLECTOR_MCP_URL": "https://collector.example/mcp",
        "OPSCLI_COLLECTOR_MONITOR_COLLECTOR_MCP_API_KEY_FILE": str(tmp_path / "mcp.key"),
        "OPSCLI_COLLECTOR_MONITOR_POLL_INTERVAL": "2.5",
        "OPSCLI_COLLECTOR_MONITOR_STALLED_THRESHOLD": "601",
        "OPSCLI_COLLECTOR_MONITOR_QUEUE_THRESHOLD": "602",
        "OPSCLI_COLLECTOR_MONITOR_RUNTIME_STALE_THRESHOLD": "90",
        "OPSCLI_COLLECTOR_MONITOR_ORPHAN_REQUIRED_SCANS": "3",
        "OPSCLI_COLLECTOR_MONITOR_ALERT_COOLDOWN": "60",
        "OPSCLI_COLLECTOR_MONITOR_WEBHOOK_FILE": str(tmp_path / "wecom.json"),
        "OPSCLI_COLLECTOR_MONITOR_HOST": "0.0.0.0",
        "OPSCLI_COLLECTOR_MONITOR_PORT": "9876",
        "OPSCLI_COLLECTOR_MONITOR_COLLECTOR_PROBE_TIMEOUT": "1.5",
    }

    settings = load_settings(environ=env, config_dir=tmp_path)

    assert settings.queue_db_path == tmp_path / "queue.sqlite3"
    assert settings.state_db_path == tmp_path / "monitor.sqlite3"
    assert settings.monitor_url == "http://monitor.internal:9000"
    assert settings.collector_mcp_url == "https://collector.example/mcp"
    assert settings.collector_mcp_api_key_file == tmp_path / "mcp.key"
    assert settings.poll_interval == 2.5
    assert settings.stalled_threshold == 601.0
    assert settings.queue_threshold == 602.0
    assert settings.runtime_stale_threshold == 90.0
    assert settings.orphan_required_scans == 3
    assert settings.alert_cooldown == 60.0
    assert settings.webhook_file == tmp_path / "wecom.json"
    assert settings.host == "0.0.0.0"
    assert settings.port == 9876
    assert settings.collector_probe_timeout == 1.5


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("POLL_INTERVAL", "0"),
        ("ORPHAN_REQUIRED_SCANS", "0"),
        ("PORT", "70000"),
        ("RUNTIME_STALE_THRESHOLD", "not-a-number"),
        ("STALLED_THRESHOLD", "NaN"),
        ("QUEUE_THRESHOLD", "Infinity"),
    ],
)
def test_load_settings_rejects_invalid_values(tmp_path: Path, name: str, value: str) -> None:
    """非法数值配置应在服务启动前给出清晰错误。"""
    with pytest.raises(ValueError, match=name.lower().replace("_", " ")):
        load_settings(
            environ={f"OPSCLI_COLLECTOR_MONITOR_{name}": value},
            config_dir=tmp_path,
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://collector.example/mcp",
        "http://localhost:8766/mcp",
        "http://127.0.0.1:8766/mcp",
        "http://[::1]:8766/mcp",
    ],
)
def test_api_key_file_requires_https_or_loopback_collector_url(
    tmp_path: Path,
    url: str,
) -> None:
    """密钥文件只能配合 HTTPS 或明确回环 HTTP 地址。"""
    env = {
        "OPSCLI_COLLECTOR_MONITOR_COLLECTOR_MCP_URL": url,
        "OPSCLI_COLLECTOR_MONITOR_COLLECTOR_MCP_API_KEY_FILE": str(tmp_path / "mcp.key"),
    }

    assert load_settings(environ=env, config_dir=tmp_path).collector_mcp_url == url


def test_api_key_file_rejects_plaintext_remote_url_for_loaded_and_manual_settings(
    tmp_path: Path,
) -> None:
    """环境加载和手工设置都不得绕过远端 HTTP 密钥保护。"""
    env = {
        "OPSCLI_COLLECTOR_MONITOR_COLLECTOR_MCP_URL": "http://collector.example/mcp",
        "OPSCLI_COLLECTOR_MONITOR_COLLECTOR_MCP_API_KEY_FILE": str(tmp_path / "mcp.key"),
    }
    with pytest.raises(ValueError, match="must use HTTPS"):
        load_settings(environ=env, config_dir=tmp_path)

    settings = load_settings(environ={}, config_dir=tmp_path)
    unsafe = replace(
        settings,
        collector_mcp_url="http://collector.example/mcp",
        collector_mcp_api_key_file=tmp_path / "mcp.key",
    )
    with pytest.raises(ValueError, match="must use HTTPS"):
        validate_settings(unsafe)
    with pytest.raises(ValueError, match="must use HTTPS"):
        build_service(unsafe)


def test_manual_settings_reject_non_finite_threshold(tmp_path: Path) -> None:
    """手工构造配置也必须拒绝非有限阈值。"""
    settings = load_settings(environ={}, config_dir=tmp_path)

    with pytest.raises(ValueError, match="stalled threshold must be finite"):
        validate_settings(replace(settings, stalled_threshold=float("nan")))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("orphan_required_scans", float("nan"), "orphan required scans must be an integer"),
        ("orphan_required_scans", float("inf"), "orphan required scans must be an integer"),
        ("orphan_required_scans", 2.0, "orphan required scans must be an integer"),
        ("orphan_required_scans", True, "orphan required scans must be an integer"),
        ("port", float("nan"), "port must be an integer"),
        ("port", float("inf"), "port must be an integer"),
        ("port", 8767.0, "port must be an integer"),
        ("port", False, "port must be an integer"),
    ],
)
def test_manual_settings_require_strict_integers(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    """手工构造的扫描次数和端口必须是严格整数。"""
    settings = load_settings(environ={}, config_dir=tmp_path)

    with pytest.raises(ValueError, match=message):
        validate_settings(replace(settings, **{field: value}))


def test_database_paths_reject_hard_link_alias(tmp_path: Path) -> None:
    """状态库硬链接别名不得绕过业务库物理文件隔离。"""
    queue_path = tmp_path / "queue.sqlite3"
    state_path = tmp_path / "state.sqlite3"
    queue_path.write_bytes(b"queue")
    state_path.hardlink_to(queue_path)

    with pytest.raises(ValueError, match="different physical files"):
        validate_database_paths(queue_path, state_path)
