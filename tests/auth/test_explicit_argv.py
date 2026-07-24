"""CLI 入口显式授权参数 argv 预解析测试。

覆盖 opscli/cli.py 中 _extract_explicit_credentials 的两种写法解析与校验规则：
- 支持 --flag=value 与 --flag value 两种形式
- 强制要求：提供任一 jwt 时必须同时提供 --session-id
"""
from __future__ import annotations

import pytest

from opscli.cli import _extract_explicit_credentials


def test_extract_equals_form():
    """--flag=value 形式应被正确摘出，并从 argv 中移除。"""
    cleaned, creds = _extract_explicit_credentials(
        ["query", "simple", "--table-id", "35", "--ops-jwt-token=ojwt", "--session-id=sid"]
    )
    assert cleaned == ["query", "simple", "--table-id", "35"]
    assert creds is not None
    assert creds.ops_jwt == "ojwt"
    assert creds.session_id == "sid"
    assert creds.polaris_jwt is None


def test_extract_space_form():
    """--flag value（空格）形式应被正确摘出。"""
    cleaned, creds = _extract_explicit_credentials(
        ["query", "simple", "--session-id", "sid", "--polaris-jwt-token", "pjwt"]
    )
    assert cleaned == ["query", "simple"]
    assert creds.session_id == "sid"
    assert creds.polaris_jwt == "pjwt"


def test_extract_both_jwts():
    """可同时提供 ops 与 polaris 两个 JWT。"""
    _, creds = _extract_explicit_credentials(
        ["--ops-jwt-token=o", "--polaris-jwt-token=p", "--session-id=s"]
    )
    assert creds.ops_jwt == "o"
    assert creds.polaris_jwt == "p"


def test_no_flags_returns_none():
    """未提供任何显式参数时 creds 为 None，argv 原样保留。"""
    argv = ["query", "simple", "--table-id", "35"]
    cleaned, creds = _extract_explicit_credentials(argv)
    assert cleaned == argv
    assert creds is None


def test_session_only_is_valid():
    """仅提供 --session-id（不给 jwt）是合法的显式模式。"""
    _, creds = _extract_explicit_credentials(["query", "simple", "--session-id=sid"])
    assert creds is not None
    assert creds.session_id == "sid"
    assert creds.ops_jwt is None


def test_jwt_without_session_raises():
    """提供 jwt 但缺 --session-id 时必须报错（强制 session-id）。"""
    with pytest.raises(SystemExit):
        _extract_explicit_credentials(["query", "simple", "--ops-jwt-token=ojwt"])


def test_run_entry_sets_context_and_cleans_argv(monkeypatch):
    """run() 应把显式参数注入上下文，并从 sys.argv 中移除后再交给 Typer。"""
    import sys as _sys

    from opscli import cli as cli_module
    from opscli.auth.context import get_explicit_credentials, set_explicit_credentials

    set_explicit_credentials(None)
    captured = {}

    def fake_app():
        # app() 运行时读取被清理后的 argv 与已注入的上下文
        captured["argv"] = list(_sys.argv)
        captured["creds"] = get_explicit_credentials()

    monkeypatch.setattr(cli_module, "app", fake_app)
    monkeypatch.setattr(
        _sys,
        "argv",
        ["opscli", "query", "simple", "--table-id", "35", "--ops-jwt-token=ojwt", "--session-id=sid"],
    )

    cli_module.run()

    # 显式参数已从 argv 移除
    assert captured["argv"] == ["opscli", "query", "simple", "--table-id", "35"]
    # 上下文已注入
    assert captured["creds"] is not None
    assert captured["creds"].ops_jwt == "ojwt"
    assert captured["creds"].session_id == "sid"
    set_explicit_credentials(None)
